# 09 — API, Authentication & Embedding

> **Status: Implemented for tokens and roles (MAGBI-007).**
>
> A user logs in with email and password and receives an HS256 JWT (RS256 when `MAGBI_JWT_PRIVATE_KEY_PEM` is set). A host holds an opaque `v2_svc_` service token, stored only as a hash, and calls `POST /api/v1/embed/token`. The embed token carries RLS role names. A query applies those roles and ignores roles on the body. Workspace roles are admin, editor, and viewer.
>
> In the test environment, and when `MAGBI_INSECURE_ADMIN_API` is set, a request with no token is still allowed. Otherwise a missing token is 401. JWTs are not blocklisted; the TTL is the revocation window. The embed iframe and the JavaScript SDK are Sprint 10. SSO, WebSockets, and rate limits are later.

---

## What It Does

The API layer is the surface between MagBI's frontend (and any external
consumer) and its backend services. It handles:

- **REST endpoints** — CRUD for workspaces, datasets, reports; query execution;
  embed token generation; refresh management; admin operations
- **Authentication** — JWT-based, supporting standalone deployments and
  integrated (embedded) deployments
- **Embedding** — an iframe + JavaScript SDK that lets external products display
  MagBI reports inside their own UI
- **Real-time events** — WebSocket notifications for data refresh completion,
  report updates, and slow queries

### The numbers

- **40+ REST endpoints** across 7 route groups
- **4 workspace roles** (admin, editor, viewer, embed-only)
- **3 token types** (user token, service token, embed token)
- **1 WebSocket channel** per workspace for real-time events

---

## Why This Approach

### FastAPI as the server framework

**Why FastAPI over alternatives:**

| Framework | Strengths | Why rejected |
|-----------|-----------|-------------|
| **Django + DRF** | Mature, batteries-included, admin panel | Heavy ORM is unnecessary (we use raw SQL for DuckDB). Sync-first architecture fights our async I/O model. |
| **Flask** | Simple, minimal, well-understood | No native async support. No automatic OpenAPI generation. We would rebuild what FastAPI gives us. |
| **Express (Node.js)** | JavaScript everywhere, fast I/O | Python ecosystem for DuckDB/sqlglot. Two languages doubles the cognitive load. |
| **FastAPI** | **Chosen** | Native async, automatic OpenAPI docs from Pydantic models, dependency injection for auth, excellent performance via Uvicorn. |

FastAPI's killer feature for MagBI: **Pydantic models generate both validation
and OpenAPI docs.** We define a `SemanticQuery` Pydantic model once, and
FastAPI automatically validates incoming requests and generates Swagger
documentation. Zero boilerplate.

### JWT over sessions

**Sessions** store state on the server (in Redis or a database). Every request
includes a session cookie; the server looks up the session to find the user.

**JWT (JSON Web Tokens)** encode the user's identity and claims *inside* the
token itself. The server validates the token's signature without any lookup.

We chose JWT because:

1. **Stateless scaling** — any API server instance can validate a JWT without
   talking to a central session store. This matters when running multiple
   FastAPI instances behind a load balancer.
2. **Embed tokens** — when a report is embedded in an iframe, the iframe cannot
   share the parent page's cookies (different origin). JWT tokens travel in
   the `Authorization` header, which works across origins.
3. **Service tokens** — server-to-server calls (e.g., the ERP requesting an
   embed token) are cleaner with bearer tokens than with cookies.

**The cost:** JWT tokens cannot be revoked instantly. If a user is removed,
their token remains valid until it expires. We mitigate this with short TTLs
(1 hour for user tokens, 15 minutes for embed tokens) and an optional
revocation blocklist in Redis.

### Two authentication modes

MagBI serves two deployment patterns:

1. **Standalone mode** — MagBI is the only application. Users log in with
   email and password. MagBI manages its own user database. This is the
   simple case, like a self-hosted Metabase.

2. **Integrated mode** — MagBI is embedded inside another product (like MSD
   ERP). The host product handles authentication. It passes MagBI a service
   token, which MagBI trusts to identify the user and their permissions. The
   host product's backend calls MagBI's API to get embed tokens for its users.

Why two modes? Because forcing every deployment to integrate with an external
identity provider is hostile to small teams who just want to see their data.
And forcing every embedded deployment to maintain a separate login flow is
hostile to enterprises who already have SSO.

---

## How It Works

### REST API Overview

```
/api/v1/workspaces      — CRUD workspaces, member management
/api/v1/workspaces/{wid}/datasets —  CRUD datasets, model definition, connections
/api/v1/workspaces/{wid}/reports —  CRUD reports, report definition JSON
/api/v1/query          — Execute semantic queries, batch queries
/api/v1/embed          — Generate embed tokens, embed configuration
/api/v1/workspaces/{wid}/datasets/{did}/refresh — Trigger refresh, view history, cancel jobs
/api/v1/admin          — User management, audit log, metrics, service tokens
```

### Authentication Flow (Standalone Mode)

```
1. User → POST /api/auth/login { email, password }
2. Server verifies credentials against PostgreSQL
3. Server creates JWT:
   {
     "sub": "user-uuid",
     "email": "analyst@company.com",
     "workspaces": { "ws-1": "editor", "ws-2": "viewer" },
     "exp": <now + 1 hour>
   }
4. Server returns { "token": "eyJ...", "expiresAt": "..." }
5. Frontend stores token in memory (not localStorage — XSS risk)
6. Every subsequent request includes: Authorization: Bearer eyJ...
7. FastAPI dependency extracts and validates the JWT on every request
```

### Authentication Flow (Integrated Mode)

```
1. Host product (ERP) has a service token (long-lived, created by admin)
2. ERP backend → POST /api/embed/token
   Authorization: Bearer <service-token>
   Body: {
     "reportId": "report-uuid",
     "userId": "erp-user-123",
     "roles": ["RegionalManager"],
     "filters": [{ "table": "Region", "column": "Name", "values": ["East"] }]
   }
3. MagBI validates service token
4. MagBI resolves RLS: the "RegionalManager" role has filters that restrict
   data to the user's region
5. MagBI creates an embed token:
   {
     "sub": "erp-user-123",
     "reportId": "report-uuid",
     "securityFilters": [<resolved RLS filters>],
     "lockedFilters": [<additional locked filters>],
     "exp": <now + 15 minutes>
   }
6. MagBI returns { "token": "eyJ...", "embedUrl": "/embed/report-uuid" }
7. ERP frontend loads an iframe: <iframe src="/embed/report-uuid?token=eyJ...">
8. The iframe's MagBI viewer uses the embed token for all queries
9. Before expiry, the JS SDK requests a new token via postMessage to the parent
```

### Workspace Roles

| Role | Can view reports | Can edit reports | Can manage datasets | Can manage members |
|------|:---:|:---:|:---:|:---:|
| **Admin** | Yes | Yes | Yes | Yes |
| **Editor** | Yes | Yes | Yes | No |
| **Viewer** | Yes | No | No | No |
| **Embed-only** | Yes (via embed) | No | No | No |

Roles are per-workspace. A user can be an admin in one workspace and a viewer
in another. The embed-only role exists for service accounts that generate embed
tokens but never log in to the MagBI UI.

### Token Types

| Token | TTL | Who creates it | Use case |
|-------|-----|---------------|----------|
| **User token** | 1 hour | Login endpoint | Human users in the MagBI UI |
| **Service token** | No expiry (revocable) | Admin API | Server-to-server calls from the host product |
| **Embed token** | 15 minutes | Embed API (requires service token) | iframe viewers with resolved RLS and locked filters |

**Why 15 minutes for embed tokens?** Short enough that a stolen token is
useless quickly. Long enough that the JS SDK can refresh it silently. The SDK
requests a new token via `postMessage` to the parent window, which calls
the ERP backend, which calls MagBI's embed API. The user sees no interruption.

### The Embed SDK

The JavaScript SDK is a standalone file (`embed/sdk.ts`) that the host product
loads:

```html
<script src="https://magbi.example.com/sdk.js"></script>
<script>
  const report = magbi.embed(document.getElementById("report-container"), {
    embedUrl: "https://magbi.example.com/embed/report-uuid",
    token: "eyJ...",
  });

  // Listen for events
  report.on("loaded", () => console.log("Report ready"));
  report.on("filterChanged", (filters) => console.log("Filters:", filters));

  // Programmatic control
  report.setFilters([{ table: "Region", column: "Name", values: ["West"] }]);
  report.setTheme({ colors: ["#003366", "#0066cc", "#3399ff"] });
  report.refreshData();
</script>
```

The SDK:
1. Creates an iframe with the embed URL
2. Injects the token via postMessage
3. Exposes a typed API for programmatic control (setFilters, setTheme, etc.)
4. Handles token refresh — when the token nears expiry, it fires a
   `tokenExpiring` event. The host product's handler calls its own backend
   to get a new token.
5. Relays events from the report (loaded, filterChanged, error) to the host

### WebSocket Events

MagBI uses WebSockets for real-time notifications:

```
ws://magbi.example.com/ws?token=eyJ...

Channels:
  workspace:{id}  — events for all datasets and reports in a workspace

Events:
  dataset.refreshed  — a dataset finished refreshing (success or failure)
  report.updated     — a report definition was saved by another user
  query.slow         — a query exceeded the slow-query threshold
```

**Why WebSocket instead of SSE (Server-Sent Events)?** WebSocket is
bidirectional — the client can subscribe to specific channels. SSE is
server-to-client only, which is sufficient for notifications but does not
allow channel subscription without multiple SSE connections.

---

## Key Concepts

### What is a JWT?

A JSON Web Token is three base64-encoded parts separated by dots:

```
header.payload.signature
```

- **Header:** `{"alg": "HS256", "typ": "JWT"}` — the signing algorithm
- **Payload:** `{"sub": "user-123", "exp": 1698765432, ...}` — the claims
- **Signature:** `HMAC-SHA256(header + "." + payload, secret)` — proves
  the token was not tampered with

Any server that knows the secret can validate the signature. No database
lookup, no session store, no network call. This is why JWT scales: validation
is a local CPU operation.

**The caveat:** Anyone who has the secret can forge tokens. The secret must
never leave the server. In production, use RS256 (asymmetric) instead of HS256
so that the private key (for signing) stays on the auth server and the public
key (for verification) can be distributed to other services.

### What is RLS (Row-Level Security) in the context of embedding?

When a dashboard is embedded in an ERP, different users should see different
data. A regional manager should only see their region's data. This is RLS.

In MagBI, RLS works at the token level:

1. The dataset defines RLS roles: `RegionalManager` has filter
   `Region[Name] = @UserRegion`
2. When the ERP requests an embed token, it specifies the role and the user's
   region
3. MagBI **resolves** the role — replaces `@UserRegion` with `"East"` and bakes
   the resulting filter into the embed token
4. Every query executed with this token automatically includes
   `WHERE Region.Name = 'East'`
5. The filter is **locked** — the user cannot remove it, and `ALL(Region)` in a
   DAX formula does not override it

This is why embed tokens are short-lived — they contain the resolved security
context. If the user's permissions change, the next token will have the updated
filters.

### Rate limiting with sliding windows

To prevent abuse, the API limits requests per client:

```
100 requests per minute per user token
1000 requests per minute per service token
```

The implementation uses Redis' sorted sets:

1. Each request adds a timestamp to the user's sorted set:
   `ZADD rate:{user-id} {now} {request-id}`
2. Remove entries older than the window:
   `ZREMRANGEBYSCORE rate:{user-id} 0 {now - 60}`
3. Count remaining entries:
   `ZCARD rate:{user-id}`
4. If count > limit, return 429 Too Many Requests

This is a **sliding window** — it considers the actual distribution of requests
in the last 60 seconds, not a fixed bucket that resets on the minute boundary.

---

## Error Model

Every API error returns a consistent structure:

```json
{
  "error": {
    "code": "QUERY_TIMEOUT",
    "message": "Query exceeded the 30-second timeout",
    "details": {
      "queryId": "q-abc-123",
      "elapsed": 30.1
    }
  }
}
```

Error codes are namespaced by domain:
- `AUTH_*` — authentication and authorization errors
- `QUERY_*` — query engine errors
- `REFRESH_*` — data refresh errors
- `VALIDATION_*` — input validation errors

The frontend maps error codes to user-friendly messages. Agents map error
codes to recovery strategies.

---

## Strengths

- **Stateless auth scales horizontally** — add API servers without shared state
- **Two auth modes cover all deployments** — standalone and embedded
- **Embed tokens with resolved RLS** — security is baked into the token, not
  checked at query time (defense in depth: it is also checked at query time)
- **Automatic OpenAPI docs** — every endpoint is documented from the Pydantic
  models, always in sync with the code
- **WebSocket events** — UIs update in real time without polling

## Weaknesses & Risks

- **Token revocation** — a compromised token is valid until expiry. The Redis
  blocklist adds latency to every request. Short TTLs are the primary defense.
- **Service token security** — a leaked service token grants broad access.
  Mitigated by IP allowlisting and audit logging.
- **WebSocket scaling** — each connected client holds a WebSocket connection.
  At 10,000 concurrent viewers, this is 10,000 connections. Redis pub/sub
  helps distribute events, but sticky sessions or a dedicated WebSocket
  gateway may be needed.
- **CORS complexity** — embedding across origins requires careful CORS
  configuration. Misconfigured CORS either blocks legitimate embeds or opens
  the API to unwanted origins.
- **No GraphQL** — the REST API requires multiple round trips for some
  operations (list workspaces + list datasets in each). GraphQL would allow
  fetching everything in one request. We chose REST for simplicity; GraphQL
  is a possible future addition.

---

## For Agents

1. API routes live in `server/magbi/api/`. One file per route group.
2. Authentication logic is in `server/magbi/auth/`.
3. Every endpoint must declare its required role via a FastAPI dependency:
   `current_user: User = Depends(require_role("editor"))`
4. Never expose internal error details (stack traces, SQL queries) in API
   responses. Log them server-side; return only error codes and messages.
5. Embed tokens must always include resolved security filters. Never return
   an embed token without RLS resolution, even if the dataset has no RLS
   roles defined (in that case, the filters list is empty but present).
6. Rate limiting is applied via middleware. Do not add per-endpoint rate
   limits unless there is a specific abuse concern.
7. When adding a new endpoint:
   - Add it to the appropriate router in `server/magbi/api/`
   - Define request/response Pydantic models
   - Add role requirements
   - Update the API spec chapter and this knowledge base chapter

---

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [JWT.io — JSON Web Token Introduction](https://jwt.io/introduction)
- [RFC 7519 — JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519)
- [Power BI Embedded REST API](https://learn.microsoft.com/en-us/rest/api/power-bi/)
- [OWASP API Security Top 10](https://owasp.org/API-Security/)
- [Redis Rate Limiting Patterns](https://redis.io/commands/incr#pattern-rate-limiter)
