# Feature: MAGBI-014 - Lock down embed tokens and workspace roles

Source: MagBI Implementation Plan, Phase 5, Tasks 36 and 37 (audit of MAGBI-013, 30 Oct 2026).

## 1. Analysis

**Problem**:

- `_embed_path_allowed` in `server/magbi/api/deps.py` lets an embed token call any method on any path containing `/reports/`. `update_report` in `server/magbi/api/reports.py` has no actor check, so an embed token held in an ERP user's browser can rewrite or unpublish any report.
- `reports.py`, `datasets.py`, `refresh.py`, `connections.py` and `transforms.py` never call `permits`. Any signed-in user can read and change any workspace's reports, datasets, measures, relationships, uploads, refreshes and connections.

**Affected files**:

- `server/magbi/api/deps.py` (embed guard, new role dependency)
- `server/magbi/api/reports.py`, `datasets.py`, `refresh.py`, `connections.py`, `transforms.py`, `workspaces.py`
- New tests: `server/tests/test_api/test_embed_guard.py`, `server/tests/test_api/test_permissions.py`

**Role rules** (`permits` already ranks viewer < editor < admin; platform admins and the dev actor pass):

| Action | Minimum role |
|--------|--------------|
| Read workspace, datasets, definitions, reports, refresh history | viewer |
| Create or change datasets, definitions, measures, relationships, uploads, refreshes, schedules, reports, transform previews | editor |
| Browse a connection's schemas, tables and previews | editor |
| Create, change or test connections | admin |
| Create a workspace | platform admin |
| List workspaces | members see only their own |

Embed tokens may only `GET /workspaces/{wid}/reports/{rid}` for a report in the token and `POST /workspaces/{wid}/datasets/{did}/query` for a dataset in the token, both in the token's workspace, plus `GET /auth/whoami`.

**Risks**:

- Creating a workspace becomes platform-admin only. Before this, a creator who was not a platform admin was locked out of the new workspace anyway, because nobody was made its member.
- User tokens carry memberships captured at login. A role change takes effect at the next login. Unchanged by this ticket.
- Test and insecure dev mode still treat a request with no token as the dev admin, so existing tests and the local designer keep working.

**Jira Tasks**:

| Key | Summary |
|-----|---------|
| TASK-36 | Method- and scope-aware embed guard |
| TASK-37 | Workspace role checks on every workspace route |

---

## 2. Implementation Plan

| Subtask Key | Summary | Acceptance Criteria | Status |
|-------------|---------|---------------------|--------|
| SUB-36.1 | Embed guard | Embed token: PUT, DELETE, POST on a report → 403; GET of a report not in the token → 403; GET in another workspace → 403; query on a dataset not in the token → 403; GET of its own published report → 200 | [x] |
| SUB-37.1 | Role dependency on all workspace routes | Table-driven test over every workspace route × viewer, editor, admin, non-member gives the expected allow or 403; workspace list is filtered; workspace create needs platform admin | [x] |
| SUB-37.2 | Regression | Full pytest and Vitest pass; live curl with an embed token cannot PUT a report | [x] |

---

## 3. Execution Log

- [x] SUB-36.1: see git log `fix(api): limit embed tokens to reading their own reports`
- [x] SUB-37.1: see git log `fix(api): require workspace roles on every workspace route`
- [x] SUB-37.2: 30 Oct 2026, full pytest and Vitest green

---

## 4. Definition of Done (DoD)

- [x] Code is written and passes all local tests
- [x] Single-sentence commit rule followed for all commits
- [x] SSOT README is fully updated
