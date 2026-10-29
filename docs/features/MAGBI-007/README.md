# Feature: MAGBI-007 - Auth and embedding

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 7 (Week 10-11). FR: FR-070, FR-071, FR-090, FR-092, FR-093.
Deliverable: an ERP sends a service token, receives an embed token, and a query applies the roles carried in that token.

## 1. Analysis
**Current state (verified)**: `server/magbi/auth/` is four stubs (`tokens.py`, `roles.py`, `rls.py`, empty `__init__.py`). `api/embed.py` and `api/admin.py` are empty routers and are not mounted. Every `/api/v1` route depends on `admin_gate`, which allows the call when `environment` is `dev` or `MAGBI_INSECURE_ADMIN_API` is set. Tests run with `environment=test` and that flag, and they send no token. `users` and `workspace_members` already exist from migration `0001`, with `password_hash` and the role enum `admin`, `editor`, `viewer`, `embed_only`. There is no service-token table and no `is_platform_admin` column. `python-jose` and `cryptography` are already dependencies. Settings already have `jwt_secret`, `jwt_algorithm` (default `HS256`), and the two TTLs (60 minutes and 15 minutes). Workspace create, list, and get exist and do not check a member. The query route accepts `roles` on the body. RLS expressions still are not compiled at save time. The embed iframe and the JavaScript SDK are Sprint 10.

**Affected files**:
- `server/magbi/auth/tokens.py`, `roles.py`, `__init__.py`
- `server/magbi/api/embed.py`, `admin.py`, `deps.py`, `router.py`, `query.py`
- `server/magbi/metadata/models.py`, `server/migrations/versions/0004_auth.py`
- `server/tests/test_auth/`
- `docs/kb/09-api-auth-embed.md`, `docs/architecture/API-SERVICE-SPEC.md` (status note)

**Design decisions**:
1. **Three caller kinds.** A user token is a JWT. A service token is an opaque `v2_svc_` secret, stored only as a SHA-256 hash. An embed token is a short-lived JWT with `type: embed`. User tokens use audience `v2-bi-api`. Embed tokens use audience `v2-bi-embed`. One cannot be presented as the other.
2. **HS256 is the default. RS256 is used when a private key is configured.** Both are issued and checked with `python-jose`. HS256 signs with `MAGBI_JWT_SECRET`. RS256 signs with `MAGBI_JWT_PRIVATE_KEY_PEM` and checks with the matching public key. The algorithm on the token must match the configured one. A token that names the other algorithm is rejected.
3. **Passwords are hashed with PBKDF2-HMAC-SHA256.** No new package. `POST /api/v1/auth/login` takes email and password and returns a user token. There is no open registration and no SSO. A platform admin creates users. If the user table is empty, startup creates one admin from `MAGBI_BOOTSTRAP_ADMIN_EMAIL` and `MAGBI_BOOTSTRAP_ADMIN_PASSWORD` when both are set.
4. **Workspace roles keep the existing enum.** `admin` manages members and everything an editor can do. `editor` changes datasets, connections, and refreshes. `viewer` reads and queries. `embed_only` is not a membership that calls the management API. The order is admin, editor, viewer. A check names the minimum role.
5. **The current test suite keeps working.** When `environment` is `test`, or `MAGBI_INSECURE_ADMIN_API` is true, a request with no token is still the dev admin. A request that sends `Authorization` is checked even then. Outside those two cases a missing or bad token is 401. This replaces the blanket 503 from `admin_gate` once auth can succeed.
6. **Service tokens are workspace scoped.** Migration `0004` adds `service_tokens` (id, workspace, name, hash, created, revoked) and `users.is_platform_admin`. Create and revoke are platform-admin routes under `/api/v1/admin/service-tokens`. The plaintext secret is returned once. A revoked token fails the next call. JWTs are not blocklisted. Their TTL is the revocation window.
7. **Embed tokens come only from a service token.** `POST /api/v1/embed/token` takes the user email and name, report ids, dataset ids, and `rls.roles`. Every report and dataset must belong to the service token's workspace. TTL cannot exceed 15 minutes. The iframe page and the SDK are not built. The response still includes `token`, `expiresAt`, and `reportUrls`.
8. **A query trusts the embed token's roles and ignores `roles` on the body.** The dataset must be one of the token's datasets. A user token must be at least a viewer of that workspace, and body `roles` are accepted only for an admin or editor. A viewer or an embed token cannot widen RLS by naming another role. Management routes reject embed tokens.

**Risks**:
- **A test that started sending `Authorization` by accident would start failing closed.** Mitigation: only the new auth tests send a token. The gate treats a missing header as today when the environment is `test`.
- **HS256 and RS256 acceptance at the same time lets a forged header pick the weaker key.** Mitigation: the server has one active algorithm. A token signed with the other is rejected.
- **The embed token's role names are not checked against the dataset until the query runs.** Mitigation: the query path already rejects an unknown role. The embed route checks that the datasets exist in the workspace.

**Assumptions**:
- SSO, WebSocket events, rate limits, and the embed SDK wait.
- Report viewing beyond the token's dataset list waits for the report API. Report ids are stored on the token and checked for workspace membership, not rendered.
- RLS filter expressions stay a comparison, `IN`, or `AND` of those, as in Sprint 5.
- Password reset is not this sprint.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Tokens and passwords |
| TASK-2 | Roles, login, and membership |
| TASK-3 | Service tokens and embed tokens |
| TASK-4 | Gate, query RLS, docs, and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | User tokens | A password hash verifies, an HS256 user token round-trips, and a wrong password, a wrong audience, and an expired token fail | 3h | [x] |
| SUB-1.2 | RS256 | When a PEM key is configured, tokens are signed and checked with RS256, and an HS256 token is rejected in that mode | 2h | [x] |
| SUB-2.1 | Role checks | Admin, editor, and viewer match the permission order; a viewer is refused an editor action; an embed token is refused a management action | 3h | [x] |
| SUB-2.2 | Login and members | Login returns a token; a platform admin creates a user; a workspace admin adds and removes a member; a duplicate email is 409 | 4h | [x] |
| SUB-3.1 | Service tokens | Migration `0004` stores a hash; create returns the secret once; a later call accepts it; revoke makes the next call fail | 3h | [ ] |
| SUB-3.2 | Embed tokens | A service token mints an embed token scoped to its workspace; a user token cannot mint one; a dataset outside the workspace is rejected | 3h | [ ] |
| SUB-4.1 | Gate and query | Outside test mode a missing token is 401; an embed token's roles are applied to the query and body roles are ignored; a viewer cannot set roles | 4h | [ ] |
| SUB-4.2 | Docs | KB 09 and the API spec status note the three token kinds, the test-mode bypass, and what stays later | 1.5h | [ ] |
| SUB-4.3 | Finalization | ruff, mypy strict, coverage over 80% for `auth` and the new routes; full regression; PR description | 1.5h | [ ] |

Order: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.3. Each subtask is code, tests, and one single-sentence commit. About 25 hours.

---

## 3. Execution Log
- [x] SUB-1.1: see git log. Passwords use PBKDF2. An HS256 user token round-trips. A wrong audience and an expired token fail.
- [x] SUB-1.2: see git log. RS256 signs with a PEM private key. An HS256 token is rejected while that algorithm is active.
- [x] SUB-2.1: see git log. Admin outranks editor, which outranks viewer. An embed or service caller cannot take a management action. A platform admin can.
- [x] SUB-2.2: see git log. Login returns a user token. A platform admin creates a user. A workspace admin adds and removes a member. A duplicate email is 409. A viewer cannot add a member.
- [ ] SUB-3.1: (Commit hash)
- [ ] SUB-3.2: (Commit hash)
- [ ] SUB-4.1: (Commit hash)
- [ ] SUB-4.2: (Commit hash)
- [ ] SUB-4.3: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] `ruff check` and `mypy --strict` pass
- [ ] Coverage over 80% for `auth` and the new routes
- [ ] A service token mints an embed token and a query applies that token's roles
- [ ] A missing token is rejected outside test mode
- [ ] KB 09 updated to match the implementation
