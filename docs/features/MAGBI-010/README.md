# Feature: MAGBI-010 - Report viewer and embed SDK

Source: `docs/IMPLEMENTATION-PLAN.md` Sprint 10 (Week 14-15). Milestone 3, with auth from Sprint 7. FR: FR-060, FR-061, FR-064, FR-072, FR-073, FR-074, FR-075. The embed token itself is already FR-070 from Sprint 7.
Deliverable: open a published report, see the same charts as the designer, click a category to cross-filter, export a visual, and load that report in an iframe from the SDK.

## 1. Analysis

The designer (MAGBI-009) stores a report definition and draws column, bar, line, pie, card, and table from `POST .../datasets/{id}/query`. A saved Sales report already exists in the local demo. The viewer reuses that drawing path and does not add a page editor.

`POST /api/v1/embed/token` already returns a token, `expiresAt`, and `reportUrls` of the form `/embed/{reportId}`. An embed token is allowed only for the datasets and reports named on it, and a query uses the token's RLS roles. There is no report read for the viewer yet. `web/src/embed/sdk.ts` and `buildEChartsTheme` are stubs.

**Affected files**:
- `server/magbi/api/reports.py` — `GET` one report. An embed token may read only a published report listed on the token. The body includes `last_refreshed_at` from the latest succeeded refresh of the report's dataset.
- `web/src/viewer/` — read-only page at `/workspaces/:workspaceId/reports/:reportId` and `/embed/:reportId`. Same visuals and cross-filter as the designer. No move, wells, undo, or publish.
- `web/src/viewer/export.ts` — CSV and xlsx from the visual's last query result. No new query and no new dependency.
- `web/src/embed/sdk.ts` — iframe, `postMessage` for token, filters, and theme, plus `loaded`, `error`, `filterChanged`, `visualClicked`, and `tokenExpiring`.
- `web/src/shared/theme.ts` — host colors become the chart palette.
- `docs/kb/09-api-auth-embed.md` — the SDK and viewer that actually ship.

**Risks**:
- The service token that mints an embed token must stay on the host server. The browser SDK cannot call `POST /embed/token` itself.
- Each visual is still its own query. This sprint does not add a batch endpoint.
- Docker already listens on `localhost:8000`. The demo API is on `127.0.0.1:8000`. That is a local proxy detail, not part of the viewer.

**Assumptions**:
- Drill-down is named on FR-060 and is not this sprint. Tooltips stay the ones ECharts already shows. Cross-filter is the interactivity.
- A missing refresh history says "Not refreshed yet". The demo Sales file was written directly, so it has no refresh row.
- Theme is a color list and the CSS variables `--magbi-color-1` onward. Conditional formatting stays out.
- Token refresh is a host callback. The SDK emits `tokenExpiring` and accepts `setToken`. It does not store a service token.
- Unpublished reports are hidden from an embed token. A dev or editor can still open one in the workspace viewer.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Read a published report and show it |
| TASK-2 | Embed SDK |
| TASK-3 | Docs and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Report read | `GET /api/v1/workspaces/{wid}/reports/{rid}` returns the definition and `last_refreshed_at`. An embed token for another report, or an unpublished report, is rejected | 3h | [ ] |
| SUB-1.2 | Viewer | `/workspaces/:workspaceId/reports/:reportId` and `/embed/:reportId` draw the saved visuals from live queries. A category click filters the other visuals and a second click clears it. The page cannot move or edit visuals | 5h | [ ] |
| SUB-1.3 | Refresh badge and export | The badge says "Last refreshed: X minutes ago", or "Not refreshed yet". Export downloads that visual's rows as CSV and as xlsx | 3h | [ ] |
| SUB-2.1 | SDK frame | `embed(container, config)` creates an iframe, sends the token, and applies `setFilters` and `setTheme` inside the viewer | 4h | [ ] |
| SUB-2.2 | SDK events | The iframe emits `loaded`, `error`, `filterChanged`, and `visualClicked`. Near expiry the SDK emits `tokenExpiring`, and `setToken` replaces the bearer token | 3h | [ ] |
| SUB-3.1 | Docs | KB 09 names the viewer routes, the postMessage events, and that the host mints the next embed token | 1.5h | [ ] |
| SUB-3.2 | Finalization | ESLint, `tsc`, Vitest, the report-read tests, and a browser pass of the Sales viewer; PR description | 1.5h | [ ] |

Order: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2. Each subtask is code, tests, and one single-sentence commit. About 21 hours.

---

## 3. Execution Log
- [ ] SUB-1.1: (Commit hash)
- [ ] SUB-1.2: (Commit hash)
- [ ] SUB-1.3: (Commit hash)
- [ ] SUB-2.1: (Commit hash)
- [ ] SUB-2.2: (Commit hash)
- [ ] SUB-3.1: (Commit hash)
- [ ] SUB-3.2: (Commit hash)

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes local tests and lints
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
- [ ] ESLint and `tsc` pass
- [ ] Vitest covers the refresh label, CSV rows, theme colors, and SDK messages
- [ ] The Sales report opens in the viewer and a category click filters another visual
- [ ] An embed token cannot read a report that is not on the token
- [ ] KB 09 matches the SDK that shipped
