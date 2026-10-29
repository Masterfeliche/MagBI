# API and service layer specification

The REST API, authentication model, embedding protocol and server architecture
that tie every other component together. This is the glue: the report designer
talks to it, the viewer talks to it, the ERP embeds through it, and the admin
console manages workspaces through it.

| | |
|---|---|
| Written | 29 October 2026 |
| Status | Draft — not implemented |
| Depends on | Every other spec (dataset, query engine, report designer, visuals) |
| Stack | Python 3.12+, FastAPI, Uvicorn, PostgreSQL (metadata), Redis (cache + sessions), DuckDB (data) |

---

## Contents

1. [Design principles](#1-design-principles)
2. [Server architecture](#2-server-architecture)
3. [Authentication and authorisation](#3-authentication-and-authorisation)
4. [API overview](#4-api-overview)
5. [Workspaces API](#5-workspaces-api)
6. [Datasets API](#6-datasets-api)
7. [Reports API](#7-reports-api)
8. [Query API](#8-query-api)
9. [Embed API](#9-embed-api)
10. [Refresh API](#10-refresh-api)
11. [Admin API](#11-admin-api)
12. [WebSocket events](#12-websocket-events)
13. [Error model](#13-error-model)
14. [Rate limiting](#14-rate-limiting)
15. [Deployment](#15-deployment)

---

## 1. Design principles

1. **The API IS the product.** Every feature — authoring, viewing, embedding,
   administration — goes through the same REST API. The web frontend is a
   client of the API, not a special case.

2. **JWT everywhere.** Two token types: a **user token** (issued by the host
   application or v2's own login) and an **embed token** (scoped to one report,
   short-lived). No cookies, no sessions on the server.

3. **Workspace isolation.** Every resource (dataset, report, role) belongs to
   exactly one workspace. A workspace is the permission boundary — users are
   granted roles per workspace. Cross-workspace queries are not possible.

4. **Idempotent writes.** PUT and DELETE are idempotent. POST is used only for
   creation (returns 201) and for actions (embed token generation, refresh
   trigger). Every mutation returns the updated resource.

5. **OpenAPI first.** The API is defined as an OpenAPI 3.1 spec. FastAPI
   generates it automatically from the route definitions and Pydantic models.
   The spec is served at `/api/openapi.json` and Swagger UI at `/api/docs`.

---

## 2. Server architecture

```
                         ┌───────────────────────────────┐
                         │           Load Balancer        │
                         │         (nginx / Traefik)      │
                         └───────────┬───────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
              ┌─────▼─────┐  ┌──────▼──────┐  ┌─────▼─────┐
              │  API node  │  │  API node   │  │  API node  │
              │  (FastAPI)  │  │  (FastAPI)   │  │  (FastAPI)  │
              │  Uvicorn   │  │  Uvicorn    │  │  Uvicorn   │
              └─────┬─────┘  └──────┬──────┘  └─────┬─────┘
                    │                │                │
          ┌────────┼────────────────┼────────────────┼──────┐
          │        │                │                │      │
    ┌─────▼────┐ ┌─▼──────┐ ┌──────▼─────┐ ┌───────▼────┐ │
    │PostgreSQL│ │ Redis   │ │ DuckDB     │ │ Object     │ │
    │(metadata)│ │(cache,  │ │ files      │ │ store      │ │
    │          │ │ pubsub) │ │ (per       │ │ (uploads,  │ │
    │          │ │         │ │  dataset)  │ │  exports)  │ │
    └──────────┘ └─────────┘ └────────────┘ └────────────┘ │
          │                                                 │
    ┌─────▼─────────────────────────────────────────────────┘
    │  Refresh worker (Celery / ARQ)
    │  - Runs scheduled imports
    │  - Executes SQL against source DBs
    │  - Writes DuckDB files
    └───────────────────────────────────────────────────────
```

### 2.1 Components

| Component | Role | Scaling |
|---|---|---|
| **API node** | Handles HTTP requests, WebSocket connections, query execution | Horizontal (stateless) |
| **PostgreSQL** | Metadata store: workspaces, datasets, reports, users, roles, audit log | Single primary + read replicas |
| **Redis** | Query cache, embed token store, pub/sub for real-time events | Cluster mode |
| **DuckDB files** | One file per dataset (Import mode); stored on shared filesystem or object store | Shared storage (NFS, EFS, or S3 with FUSE) |
| **Object store** | Uploaded images, exported reports, DuckDB file archives | S3-compatible |
| **Refresh worker** | Background jobs: scheduled data imports, DuckDB file generation | Horizontal (Celery workers or ARQ) |

### 2.2 Request flow

A typical query request:

```
1. Client sends POST /api/v1/query with JWT in Authorization header
2. API node validates JWT → extracts user ID, workspace memberships
3. API node resolves the dataset → finds the DuckDB file path
4. API node resolves RLS → reads the user's role assignments from PostgreSQL
5. API node calls the query engine (in-process) with SemanticQuery + RLS predicates
6. Query engine compiles measures, generates SQL, executes on DuckDB
7. API node returns DSR JSON
```

For cached queries, step 5–6 is replaced by a Redis lookup.

---

## 3. Authentication and authorisation

### 3.1 Two authentication modes

| Mode | Who uses it | How it works |
|---|---|---|
| **Standalone** | v2 deployed as its own product | Users log in to v2 directly (email + password or SSO). v2 issues its own JWT. |
| **Integrated** | v2 embedded inside a host app (e.g., MSD ERP) | The host app authenticates the user and calls v2's API with a **service token** to get an **embed token** for the user. |

Both modes produce a JWT that the API validates on every request.

### 3.2 JWT structure

```json
{
  "sub": "user-42",
  "email": "david@magilatech.co.tz",
  "name": "David",
  "workspaces": [
    { "id": "ws-msd", "role": "editor" },
    { "id": "ws-demo", "role": "viewer" }
  ],
  "iat": 1730200000,
  "exp": 1730203600,
  "iss": "v2-bi",
  "aud": "v2-bi-api"
}
```

| Claim | Purpose |
|---|---|
| `sub` | User ID (stable, unique) |
| `email` | For display and RLS `@userEmail` parameter |
| `workspaces` | Which workspaces the user can access and their role |
| `exp` | Expiry (1 hour for user tokens, 15 minutes for embed tokens) |
| `iss` | Issuer: `v2-bi` for standalone, the host app's name for integrated |
| `aud` | Audience: always `v2-bi-api` |

### 3.3 Workspace roles

| Role | Permissions |
|---|---|
| **Admin** | Everything: manage workspace settings, members, datasets, reports, RLS, refresh schedules |
| **Editor** | Create and edit datasets and reports; trigger refreshes; cannot manage members |
| **Viewer** | View reports; interact (filter, drill, cross-filter); cannot edit or create |
| **Embed-only** | View a specific report via embed token; no direct API access |

### 3.4 Service tokens (for integrated mode)

The host application authenticates to v2 using a **service token** — a
long-lived API key stored in the host's configuration:

```
Authorization: Bearer v2_svc_xxxxxxxxxxxxxxxxx
```

Service tokens have workspace-level permissions and can:
- Generate embed tokens for any user in their workspace.
- Trigger data refreshes.
- Read report and dataset metadata.
- Cannot modify datasets or reports (that requires a user token with editor role).

### 3.5 Embed tokens

An embed token is a short-lived, scoped JWT that grants access to a specific
report for a specific user:

```json
{
  "sub": "user-42",
  "type": "embed",
  "reportId": "rpt-fleet-availability",
  "datasetId": "ds-transport",
  "workspaceId": "ws-msd",
  "permissions": ["view"],
  "rls": {
    "roles": ["DepartmentAccess"],
    "parameters": {
      "@userDepartments": ["dept-001", "dept-002"]
    }
  },
  "exp": 1730200900,
  "iss": "v2-bi",
  "aud": "v2-bi-embed"
}
```

The embed token:
- Has a short TTL (15 minutes). The host app's frontend refreshes it by
  calling the host's backend, which calls v2's embed token API.
- Carries resolved RLS parameters (the host app resolves user → departments).
- Is scoped to one report (or a list of reports).
- Cannot be used for management operations (edit, delete, create).

---

## 4. API overview

Base URL: `/api/v1`

| Group | Prefix | Auth |
|---|---|---|
| Workspaces | `/workspaces` | User token (admin) |
| Datasets | `/workspaces/{wid}/datasets` | User token (editor+) |
| Reports | `/workspaces/{wid}/reports` | User token (editor+) |
| Query | `/query` | User token or embed token |
| Embed | `/embed` | Service token |
| Refresh | `/workspaces/{wid}/datasets/{did}/refresh` | User token (editor+) or service token |
| Admin | `/admin` | User token (platform admin) |
| Auth | `/auth` | Public (login, token refresh) |

### 4.1 Common patterns

- **Pagination:** `?offset=0&limit=50` (default limit 50, max 200).
- **Filtering:** `?name=Transport&createdBy=user-42`.
- **Sorting:** `?sort=updatedAt:desc`.
- **Field selection:** `?fields=id,name,updatedAt` (reduces response size).
- **Timestamps:** All timestamps are ISO 8601 UTC.
- **IDs:** UUIDs (v4), prefixed by type: `ws-`, `ds-`, `rpt-`, `user-`.

---

## 5. Workspaces API

### 5.1 Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/workspaces` | List workspaces the user can access | User (any role) |
| `POST` | `/workspaces` | Create a workspace | User (platform admin) |
| `GET` | `/workspaces/{wid}` | Get workspace details | User (any role in workspace) |
| `PUT` | `/workspaces/{wid}` | Update workspace settings | User (admin) |
| `DELETE` | `/workspaces/{wid}` | Delete workspace (soft delete) | User (admin) |
| `GET` | `/workspaces/{wid}/members` | List workspace members | User (admin) |
| `POST` | `/workspaces/{wid}/members` | Add a member | User (admin) |
| `PUT` | `/workspaces/{wid}/members/{uid}` | Update member role | User (admin) |
| `DELETE` | `/workspaces/{wid}/members/{uid}` | Remove a member | User (admin) |

### 5.2 Workspace object

```json
{
  "id": "ws-msd",
  "name": "MSD ERP",
  "description": "Ministry of Social Development BI workspace",
  "theme": { /* ThemeOverrides */ },
  "settings": {
    "defaultRefreshSchedule": "daily",
    "maxDatasets": 50,
    "maxReports": 200,
    "embedEnabled": true
  },
  "createdAt": "2026-10-01T10:00:00Z",
  "updatedAt": "2026-10-29T14:00:00Z",
  "createdBy": "user-42",
  "memberCount": 12,
  "datasetCount": 8,
  "reportCount": 55
}
```

---

## 6. Datasets API

### 6.1 Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/workspaces/{wid}/datasets` | List datasets | User (viewer+) |
| `POST` | `/workspaces/{wid}/datasets` | Create a dataset | User (editor+) |
| `GET` | `/workspaces/{wid}/datasets/{did}` | Get dataset (full model) | User (viewer+) |
| `PUT` | `/workspaces/{wid}/datasets/{did}` | Update dataset model | User (editor+) |
| `DELETE` | `/workspaces/{wid}/datasets/{did}` | Delete dataset | User (admin) |
| `GET` | `/workspaces/{wid}/datasets/{did}/tables` | List tables | User (viewer+) |
| `GET` | `/workspaces/{wid}/datasets/{did}/tables/{name}/preview` | Preview rows (top 100) | User (editor+) |
| `GET` | `/workspaces/{wid}/datasets/{did}/measures` | List all measures | User (viewer+) |
| `POST` | `/workspaces/{wid}/datasets/{did}/measures` | Create a measure | User (editor+) |
| `PUT` | `/workspaces/{wid}/datasets/{did}/measures/{name}` | Update a measure | User (editor+) |
| `DELETE` | `/workspaces/{wid}/datasets/{did}/measures/{name}` | Delete a measure | User (editor+) |
| `POST` | `/workspaces/{wid}/datasets/{did}/validate` | Validate the model | User (editor+) |
| `GET` | `/workspaces/{wid}/datasets/{did}/model-history` | List model versions | User (editor+) |
| `POST` | `/workspaces/{wid}/datasets/{did}/revert/{version}` | Revert to a version | User (editor+) |

### 6.2 Create dataset (POST)

Request body: the `DatasetDefinition` from the dataset spec, minus `id`,
`createdAt`, `updatedAt`, `version` (server-generated).

Response: `201 Created` with the full `DatasetDefinition` including generated
fields.

### 6.3 Update dataset (PUT)

Request body: the full `DatasetDefinition` including `version` (for optimistic
concurrency).

- If `version` matches the current server version → save, increment version,
  return `200 OK` with the updated definition.
- If `version` is stale → `409 Conflict` with the current server version in
  the response body.

### 6.4 Validate (POST)

Runs the full validation rules (dataset spec §12) without saving:

```json
{
  "valid": false,
  "errors": [
    { "code": "CIRCULAR_MEASURE", "message": "Circular reference: [A] → [B] → [A]", "path": "tables[0].measures[2]" }
  ],
  "warnings": [
    { "code": "TABLE_NO_RELATIONSHIPS", "message": "Table 'Config' has no relationships.", "path": "tables[3]" }
  ]
}
```

---

## 7. Reports API

### 7.1 Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/workspaces/{wid}/reports` | List reports | User (viewer+) |
| `POST` | `/workspaces/{wid}/reports` | Create a report | User (editor+) |
| `GET` | `/workspaces/{wid}/reports/{rid}` | Get report definition | User (viewer+) |
| `PUT` | `/workspaces/{wid}/reports/{rid}` | Update report | User (editor+) |
| `DELETE` | `/workspaces/{wid}/reports/{rid}` | Delete report | User (admin) |
| `POST` | `/workspaces/{wid}/reports/{rid}/clone` | Clone a report | User (editor+) |
| `GET` | `/workspaces/{wid}/reports/{rid}/thumbnail` | Get report thumbnail | User (viewer+) |
| `POST` | `/workspaces/{wid}/reports/{rid}/export` | Export as PDF/PNG | User (viewer+) |

### 7.2 Report list (GET)

Returns summary objects (not the full definition):

```json
{
  "items": [
    {
      "id": "rpt-fleet-availability",
      "name": "Fleet Availability",
      "datasetId": "ds-transport",
      "datasetName": "Transport",
      "thumbnailUrl": "/api/v1/workspaces/ws-msd/reports/rpt-fleet-availability/thumbnail",
      "createdAt": "2026-10-15T10:00:00Z",
      "updatedAt": "2026-10-29T14:30:00Z",
      "createdBy": "user-42",
      "visualCount": 12
    }
  ],
  "total": 55,
  "offset": 0,
  "limit": 50
}
```

### 7.3 Export (POST)

Generates a PDF or PNG snapshot of the report with current data:

```json
{
  "format": "pdf",
  "filters": [
    { "table": "Date", "column": "Year", "op": "eq", "value": 2026 }
  ],
  "width": 1760,
  "height": 990,
  "rls": {
    "roles": ["DepartmentAccess"],
    "parameters": { "@userDepartments": ["dept-001"] }
  }
}
```

Response: `202 Accepted` with a job ID. Poll `GET /jobs/{jobId}` until
complete, then download the file.

---

## 8. Query API

### 8.1 Endpoint

```
POST /api/v1/query
```

This is the core endpoint: every visual, every preview, every export calls it.

### 8.2 Request

```json
{
  "datasetId": "ds-transport",
  "query": { /* SemanticQuery from the query engine spec §2 */ },
  "options": {
    "returnSql": false,
    "noCache": false,
    "timeout": 30
  }
}
```

### 8.3 Response

The DSR from the query engine spec §12:

```json
{
  "columns": [...],
  "data": { ... },
  "totals": { ... },
  "rowCount": 8,
  "truncated": false,
  "queryDurationMs": 12,
  "cacheHit": true
}
```

### 8.4 Authentication

Accepts both user tokens and embed tokens. When an embed token is used:
- The `datasetId` must match the token's `datasetId`.
- RLS predicates from the token are injected automatically.
- The `options.returnSql` flag is ignored (embed tokens cannot see SQL).

### 8.5 Batch query

For dashboards that load many visuals at once, a batch endpoint avoids
per-visual HTTP overhead:

```
POST /api/v1/query/batch
```

Request:

```json
{
  "datasetId": "ds-transport",
  "queries": [
    { "id": "viz-01", "query": { /* SemanticQuery */ } },
    { "id": "viz-02", "query": { /* SemanticQuery */ } },
    { "id": "viz-03", "query": { /* SemanticQuery */ } }
  ]
}
```

Response:

```json
{
  "results": [
    { "id": "viz-01", "result": { /* DSR */ } },
    { "id": "viz-02", "result": { /* DSR */ } },
    { "id": "viz-03", "result": { /* DSR */ } }
  ],
  "totalDurationMs": 45
}
```

The server executes queries concurrently (up to the per-dataset concurrency
limit). If any query fails, its result contains an `error` field; other
queries still succeed.

---

## 9. Embed API

### 9.1 Generate embed token

```
POST /api/v1/embed/token
Authorization: Bearer v2_svc_xxxxxxxxx  (service token)
```

Request:

```json
{
  "userId": "user-42",
  "userEmail": "david@magilatech.co.tz",
  "userName": "David",
  "reports": ["rpt-fleet-availability", "rpt-fuel-consumption"],
  "datasets": ["ds-transport"],
  "permissions": ["view"],
  "rls": {
    "roles": ["DepartmentAccess"],
    "parameters": {
      "@userDepartments": ["dept-001", "dept-002"]
    }
  },
  "ttl": 900
}
```

Response:

```json
{
  "token": "eyJhbGciOiJSUzI1NiIs...",
  "expiresAt": "2026-10-29T15:15:00Z",
  "reportUrls": {
    "rpt-fleet-availability": "/embed/rpt-fleet-availability",
    "rpt-fuel-consumption": "/embed/rpt-fuel-consumption"
  }
}
```

### 9.2 Embed protocol

The host application embeds a report in an iframe:

```html
<iframe
  src="https://bi.example.com/embed/rpt-fleet-availability"
  data-token="eyJhbGciOiJSUzI1NiIs..."
  style="width: 100%; height: 100%; border: none;"
></iframe>
```

The embedded viewer:
1. Reads the token from `data-token` or from a `postMessage` from the parent.
2. Validates the token (checks signature, expiry, report scope).
3. Loads the report definition from the API (using the embed token).
4. Renders all visuals, executing queries (with the embed token's RLS).

### 9.3 JavaScript SDK

For richer integration, the host app uses a JavaScript SDK instead of raw
iframe attributes:

```javascript
import { BiEmbed } from "@v2/embed-sdk";

const embed = new BiEmbed(document.getElementById("bi-container"), {
  embedUrl: "https://bi.example.com",
  token: embedToken,
  reportId: "rpt-fleet-availability",

  // Locked filters (user cannot change these)
  lockedFilters: [
    { table: "Date", column: "Year", op: "eq", value: 2026 }
  ],

  // Theme override
  theme: {
    background: "#F5F6FA",
    fontFamily: "Segoe UI"
  },

  // Event handlers
  onLoaded: () => console.log("Report loaded"),
  onError: (err) => console.error("Embed error", err),
  onFilterChanged: (filters) => console.log("Filters changed", filters),
  onVisualClicked: (visual, data) => console.log("Visual clicked", visual, data),

  // Token refresh callback
  tokenProvider: async () => {
    const response = await fetch("/api/bi/embed-token");
    const { token } = await response.json();
    return token;
  }
});

// Programmatic control
embed.setFilter("Date", "Year", "eq", 2026);
embed.getFilters();
embed.refresh();
embed.exportPdf();
embed.destroy();
```

### 9.4 Token refresh

Embed tokens expire after 15 minutes. The SDK calls `tokenProvider` 2 minutes
before expiry to get a fresh token. The host app's backend calls the embed
token API with the service token and returns the new embed token.

```
SDK → Host backend → v2 API (POST /embed/token) → new embed token → SDK
```

The user sees no interruption. If the refresh fails (host backend down, service
token revoked), the SDK shows an error overlay.

### 9.5 Security headers

The embed endpoint sets these HTTP headers:

```
Content-Security-Policy: frame-ancestors 'self' https://erp.msd.go.tz
X-Frame-Options: ALLOW-FROM https://erp.msd.go.tz
```

The allowed origins are configured per workspace. Only listed origins can
embed the report.

---

## 10. Refresh API

### 10.1 Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| `POST` | `/workspaces/{wid}/datasets/{did}/refresh` | Trigger a refresh now | User (editor+) or service token |
| `GET` | `/workspaces/{wid}/datasets/{did}/refresh/history` | List refresh history | User (editor+) |
| `GET` | `/workspaces/{wid}/datasets/{did}/refresh/{jobId}` | Get refresh job status | User (editor+) |
| `DELETE` | `/workspaces/{wid}/datasets/{did}/refresh/{jobId}` | Cancel a running refresh | User (editor+) |

### 10.2 Trigger refresh (POST)

```json
{
  "type": "full",
  "tables": null,
  "notifyOnComplete": true
}
```

Options:
- `type: "full"` — reimport all tables.
- `type: "incremental"` — import only the lookback window (phase 3).
- `type: "table"` + `tables: ["Trip"]` — reimport specific tables only.

Response: `202 Accepted` with job ID.

### 10.3 Refresh history (GET)

```json
{
  "items": [
    {
      "jobId": "job-2026-10-29-001",
      "type": "full",
      "status": "completed",
      "startedAt": "2026-10-29T06:00:00Z",
      "completedAt": "2026-10-29T06:02:15Z",
      "durationSeconds": 135,
      "rowsImported": 125000,
      "tablesRefreshed": 4,
      "triggeredBy": "schedule",
      "error": null
    },
    {
      "jobId": "job-2026-10-28-001",
      "type": "full",
      "status": "failed",
      "startedAt": "2026-10-28T06:00:00Z",
      "completedAt": "2026-10-28T06:00:45Z",
      "durationSeconds": 45,
      "error": "Connection refused: msd-db-01:1433"
    }
  ],
  "total": 30,
  "offset": 0,
  "limit": 50
}
```

---

## 11. Admin API

Platform-level administration (not workspace-scoped).

### 11.1 Endpoints

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/admin/users` | List all users | Platform admin |
| `POST` | `/admin/users` | Create a user | Platform admin |
| `PUT` | `/admin/users/{uid}` | Update user | Platform admin |
| `DELETE` | `/admin/users/{uid}` | Deactivate user | Platform admin |
| `GET` | `/admin/audit-log` | Query the audit log | Platform admin |
| `GET` | `/admin/metrics` | Platform metrics (active users, queries/sec, storage) | Platform admin |
| `GET` | `/admin/service-tokens` | List service tokens | Platform admin |
| `POST` | `/admin/service-tokens` | Create a service token | Platform admin |
| `DELETE` | `/admin/service-tokens/{id}` | Revoke a service token | Platform admin |

### 11.2 Audit log

Every mutation (create, update, delete, refresh, login, token generation) is
logged:

```json
{
  "id": "audit-001",
  "timestamp": "2026-10-29T14:32:01Z",
  "userId": "user-42",
  "action": "dataset.update",
  "resourceType": "dataset",
  "resourceId": "ds-transport",
  "workspaceId": "ws-msd",
  "details": {
    "changes": ["Added measure 'Trips LY'", "Modified relationship rel-trip-date"]
  },
  "ipAddress": "192.168.1.100",
  "userAgent": "Mozilla/5.0 ..."
}
```

### 11.3 Actions logged

| Action | Category |
|---|---|
| `auth.login`, `auth.logout`, `auth.token_refresh` | Authentication |
| `workspace.create`, `workspace.update`, `workspace.delete` | Workspace |
| `workspace.member.add`, `workspace.member.update`, `workspace.member.remove` | Membership |
| `dataset.create`, `dataset.update`, `dataset.delete` | Dataset |
| `dataset.refresh.start`, `dataset.refresh.complete`, `dataset.refresh.fail` | Refresh |
| `report.create`, `report.update`, `report.delete`, `report.export` | Report |
| `embed.token.generate` | Embedding |
| `admin.user.create`, `admin.user.deactivate` | Admin |
| `admin.service_token.create`, `admin.service_token.revoke` | Admin |

---

## 12. WebSocket events

The API server supports WebSocket connections for real-time updates:

```
ws://bi.example.com/api/v1/ws?token=eyJhbG...
```

### 12.1 Events

| Event | Payload | When |
|---|---|---|
| `dataset.refreshed` | `{ datasetId, version, duration }` | A dataset refresh completes |
| `dataset.refresh.failed` | `{ datasetId, error }` | A refresh fails |
| `dataset.updated` | `{ datasetId, version, updatedBy }` | The model is saved (by another user) |
| `report.updated` | `{ reportId, version, updatedBy }` | A report is saved (by another user) |
| `query.slow` | `{ queryId, duration, reportId }` | A query exceeds the slow threshold |

### 12.2 Use cases

- **Report designer:** When `dataset.refreshed` fires, the designer re-queries
  all visuals to show fresh data.
- **Report viewer:** When `dataset.refreshed` fires, the viewer shows a
  "Data refreshed — click to update" banner.
- **Collaborative editing (future):** When `report.updated` fires and the
  current user isn't the author, show "This report was modified by another
  user. Reload?"

### 12.3 Channel subscription

The client subscribes to events for specific resources:

```json
{ "type": "subscribe", "channels": ["dataset:ds-transport", "report:rpt-fleet-availability"] }
```

The server sends events only for subscribed channels. This prevents a user
from receiving events for workspaces they don't have access to (the server
validates the JWT's workspace memberships).

---

## 13. Error model

All errors follow a standard format:

```json
{
  "error": {
    "code": "DATASET_NOT_FOUND",
    "message": "Dataset 'ds-transport' not found in workspace 'ws-msd'.",
    "status": 404,
    "details": {},
    "requestId": "req-2026-10-29-abc123"
  }
}
```

### 13.1 Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid token |
| `FORBIDDEN` | 403 | Token valid but insufficient permissions |
| `NOT_FOUND` | 404 | Resource does not exist (or user lacks access) |
| `CONFLICT` | 409 | Optimistic concurrency conflict (stale version) |
| `VALIDATION_ERROR` | 422 | Request body fails validation |
| `RATE_LIMITED` | 429 | Too many requests |
| `QUERY_TIMEOUT` | 504 | Query exceeded timeout |
| `QUERY_ERROR` | 400 | Semantic query is invalid (bad column, no relationship path) |
| `REFRESH_FAILED` | 500 | Data refresh failed (connection error, schema drift) |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

### 13.2 Validation errors (422)

Validation errors include a `details` array with per-field errors:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request body has 2 validation errors.",
    "status": 422,
    "details": [
      { "field": "query.select[0].table", "message": "Table 'Tripp' not found." },
      { "field": "query.filters[1].op", "message": "Operator 'like' is not supported." }
    ]
  }
}
```

---

## 14. Rate limiting

### 14.1 Limits

| Scope | Limit | Window |
|---|---|---|
| Per user | 100 requests/minute | Sliding window |
| Per service token | 500 requests/minute | Sliding window |
| Per workspace (queries) | 200 queries/minute | Sliding window |
| Per IP (unauthenticated) | 20 requests/minute | Sliding window |

### 14.2 Headers

Rate limit state is communicated via response headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1730200060
Retry-After: 12          (only on 429 responses)
```

### 14.3 Implementation

Redis-backed sliding window counter using the `EVALSHA` pattern. Each request
increments the counter for its scope. Expired entries are cleaned up
automatically.

---

## 15. Deployment

### 15.1 Docker Compose (development / small deployment)

```yaml
version: "3.9"
services:
  api:
    build: ./v2/server
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://bi:bi@postgres:5432/bi
      REDIS_URL: redis://redis:6379
      DUCKDB_PATH: /data/datasets
      JWT_SECRET: ${JWT_SECRET}
      JWT_PUBLIC_KEY: ${JWT_PUBLIC_KEY}
    volumes:
      - datasets:/data/datasets
    depends_on: [postgres, redis]

  worker:
    build: ./v2/server
    command: ["arq", "v2.worker.WorkerSettings"]
    environment:
      DATABASE_URL: postgresql://bi:bi@postgres:5432/bi
      REDIS_URL: redis://redis:6379
      DUCKDB_PATH: /data/datasets
    volumes:
      - datasets:/data/datasets
    depends_on: [postgres, redis]

  web:
    build: ./v2/web
    ports: ["3000:3000"]
    environment:
      API_URL: http://api:8000

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: bi
      POSTGRES_PASSWORD: bi
      POSTGRES_DB: bi
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data

volumes:
  datasets:
  pgdata:
  redisdata:
```

### 15.2 Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `REDIS_URL` | Yes | — | Redis connection string |
| `DUCKDB_PATH` | Yes | — | Base path for DuckDB dataset files |
| `JWT_SECRET` | Yes (standalone) | — | HMAC secret for signing JWTs |
| `JWT_PUBLIC_KEY` | Yes (integrated) | — | RSA public key for verifying host-issued JWTs |
| `CORS_ORIGINS` | No | `*` | Allowed CORS origins |
| `EMBED_ALLOWED_ORIGINS` | No | `*` | Allowed iframe origins |
| `MAX_QUERY_TIMEOUT` | No | `30` | Max query timeout in seconds |
| `MAX_QUERY_MEMORY_MB` | No | `512` | DuckDB memory limit per query |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `SENTRY_DSN` | No | — | Error tracking |

### 15.3 Health checks

| Endpoint | Checks |
|---|---|
| `GET /health` | Server is running (always 200) |
| `GET /health/ready` | PostgreSQL connected, Redis connected, at least one DuckDB file accessible |
| `GET /health/live` | Server is running and accepting requests |

### 15.4 Production deployment

For production (multi-node):

1. **API nodes** behind a load balancer (nginx, Traefik, or cloud LB). At
   least 2 nodes for availability.
2. **PostgreSQL** with streaming replication (primary + standby). API reads go
   to the replica; writes go to the primary.
3. **Redis** in cluster mode (or Redis Sentinel for smaller setups).
4. **DuckDB files** on shared storage (NFS, AWS EFS, or S3 with s3fs-fuse).
   All API nodes must see the same files.
5. **Worker nodes** (1–4) for background refresh jobs.
6. **Object store** (S3 / MinIO) for exports, thumbnails, uploaded images.
7. **Monitoring:** Prometheus + Grafana for metrics, Loki for logs, Sentry for
   errors.

### 15.5 Scaling guidelines

| Load | API nodes | Workers | PostgreSQL | Redis |
|---|---|---|---|---|
| Small (1 workspace, <10 users) | 1 | 1 | Single | Single |
| Medium (5 workspaces, <100 users) | 2 | 2 | Primary + replica | Sentinel |
| Large (20+ workspaces, 500+ users) | 4+ | 4+ | Primary + 2 replicas | Cluster (3+ nodes) |

---

## Summary: what this spec pins down

| Question | Answer |
|---|---|
| How does auth work? | §3 — JWT (user tokens + embed tokens); two modes (standalone, integrated) |
| What API endpoints exist? | §4–11 — workspaces, datasets, reports, query, embed, refresh, admin |
| How does embedding work? | §9 — service token → embed token → iframe + JS SDK; locked filters, token refresh |
| How do queries work over HTTP? | §8 — POST /query with SemanticQuery, returns DSR; batch endpoint for dashboards |
| How are refreshes managed? | §10 — trigger, history, cancel; full/incremental/table-level |
| How are errors reported? | §13 — standard error object with code, message, status, details, requestId |
| How does it scale? | §15 — stateless API nodes, shared DuckDB files, Redis cache, PostgreSQL metadata |

This spec completes the server layer. Combined with the other six specs, the
entire v2 system is now specified from data source to embedded viewer.
