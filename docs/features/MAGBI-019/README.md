# Feature: MAGBI-019 - Close the gaps the end-to-end review found

Source: the MagBI Test Review of 31 Oct 2026 (https://claude.ai/artifact/A8F9YtQghQsZD1Z3spPjTZ). It ran MagBI end to end and compared it with Power BI area by area: 4 match, 1 is ahead (themes), 5 are partly there, 5 are gaps. This plan covers its open findings and the gaps, in the order that protects live dashboards first and then moves MagBI closest to Power BI for the effort.

## 1. Analysis

### 1.1 Open findings from the review

| # | Finding | Evidence | Cause in the code | Size |
|---|---------|----------|-------------------|------|
| F1 | A viewer can open the designer; their edits quietly fail to save | QA viewer saw "Unsaved changes" after an edit; the server refused the save (403) | The `/designer` route only needs a session; the client doesn't know the caller's workspace role (`WorkspaceOut` has no role) | S |
| F2 | The designer autosaves the dataset's published report | Opening `/datasets/<id>/designer` loaded Stock & Expiry and saved every change after 2 s | `DesignerPage` PUTs the whole definition on every change when a report id is known; `Report` has one definition, no draft | M |
| F3 | A relationship needs its key column marked by hand | `KEY_REQUIRED: relationship target Region.Region must be a primary key` | `validation.py` requires `is_primary_key`; nothing checks the imported data for uniqueness | S |
| F4 | RLS rules need the table name on each column | `[Region] = "North"` on the Region table fails with "measure 'Region' does not exist" | `rls.role_filters` binds the expression without the role's table as context, so `[Region]` reads as a measure | S |
| F5 | RLS is static only | No `USERPRINCIPALNAME()`; the embed token's user email isn't usable in a rule | Binder has no identity functions; `role_filters` gets roles, not the user | M |
| F6 | About 30 DAX functions | RANKX refused; SUMX, RELATED, SWITCH, SELECTEDVALUE and others listed as unsupported | `dax/functions.py` `UNSUPPORTED`; the compiler builds one SQL aggregate per fact and has no row-context iterators or window step | L |
| F7 | Presentation cuts one subtitle short | `% of deliveries · target 95%` ends in "…" at 120 % type | Panel subtitles are single-line, ellipsis | XS |
| F8 | No phone layout | Mobile is larger text only; the 1760 × 990 page shrinks to the screen | Pages have one set of visual positions | L |

### 1.2 Gaps against Power BI

| Area | Power BI | MagBI today | What closes most of the gap |
|------|----------|-------------|-----------------------------|
| Visuals | About 30 built in, plus custom | 12 drawing classic visuals and 12 standard-kit visuals; **map shows in the gallery but never draws** ("needs latitude and longitude"); no matrix, combo, area or stacked charts | Matrix (rows × columns with subtotals), combo, area and stacked column/bar, filled map of Tanzania regions from a bundled GeoJSON, point map from latitude/longitude |
| DAX | About 250 functions | About 30 | See F6: iterators, RELATED, SWITCH, SELECTEDVALUE, HASONEVALUE, ISFILTERED, IFERROR, COALESCE, text and date functions, quarter and month time intelligence, RANKX and TOPN |
| Data sources | 100+ connectors | SQL Server (tables or a read-only query) and CSV/Excel upload; `postgresql.py` and `mysql.py` are empty files | PostgreSQL and MySQL on the existing `Connector` base; then an OData/REST JSON connector |
| Sharing | Apps, links, comments, subscriptions, alerts | Workspaces and members only | Share a report with people or a link, apps (a published set of reports for an audience), email subscriptions, alerts on a card value |
| Export | PDF, PowerPoint, Excel, paginated | Visual data to CSV/Excel; charts as images | Server-side PDF of a page (the headless Chrome renderer the QA gate already drives), then PowerPoint |
| Identity | Entra ID, MFA, lockout, reset | Email and password, audit log | Lockout after repeated failures, password reset, change password, OpenID Connect single sign-on |
| AI | Q&A, smart narratives, Copilot | None | Out of scope here; revisit after the gaps above |

### 1.3 Order and reasoning

1. **Safety first (F1, F2).** These two can change a live MSD dashboard by accident today. They are small and touch only the designer and report API.
2. **Model and security correctness (F3, F4, F5).** Small changes that remove the most common modelling friction and add dynamic RLS, which ERP embedding needs (one dashboard per user's warehouse or department).
3. **DAX core (F6).** The single biggest blocker for authors coming from Power BI. Most measures in the Power BI dashboards being migrated use SUMX, RELATED, SWITCH, SELECTEDVALUE or DIVIDE with time intelligence.
4. **Visuals.** The matrix is the most used Power BI visual after cards and bar charts. The map currently looks broken because it sits in the gallery but never draws.
5. **Sharing and export.** How reports reach people who don't author them.
6. **Data sources and identity.** Needed for customers other than MSD.
7. **Phone layout (F8).** Large and independent; it can run in parallel with 5 and 6.

**Affected areas**: `web/src/designer` (designer, store, catalog, registry, render), `web/src/viewer`, `server/magbi/api` (reports, workspaces, identity, datasets), `server/magbi/dax`, `server/magbi/engine`, `server/magbi/model`, `server/magbi/connectors`, new `server/magbi/sharing` and `server/magbi/export`.

**Risks**:
- DAX iterators and RANKX change how measures compile. Every existing Warehouse measure must give the same figures before and after; the QA gate's figure checks against MSD_ERP cover this.
- Drafts change the report contract. Existing reports become "published, no draft" in a migration; embed and viewer read the published definition only.
- Email subscriptions need an SMTP server; none is configured. They ship behind a setting and stay off until one is.
- The filled map needs region boundaries. A bundled Tanzania regions GeoJSON (public domain) keeps it offline; other countries come later.

**Assumptions**:
- MSD stays the first customer: the order favours what MSD dashboards and the ERP embed need.
- AI features are out of scope for this ticket.
- Power BI parity means "an author can rebuild a typical Power BI report", not every function and visual.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Designer safety: roles and drafts |
| TASK-2 | Model and security correctness |
| TASK-3 | DAX core functions |
| TASK-4 | Core visuals: matrix, combo, area, stacked, maps |
| TASK-5 | Sharing and export |
| TASK-6 | More data sources |
| TASK-7 | Identity: lockout, reset, single sign-on |
| TASK-8 | Phone layout |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Return the caller's role on `GET /workspaces/{wid}` (`myRole`) | Viewer, editor, admin and platform admin each see their own role; tests | 0.5d | [x] |
| SUB-1.2 | Viewers get no Edit: the designer route opens read-only or sends them to the viewer | A viewer opening `/designer` lands on the report view; no "Unsaved changes" | 0.5d | [x] |
| SUB-1.3 | Report drafts: `draft_definition` column, autosave writes the draft only, **Publish** copies draft to published | Editing a published report never changes what viewers and embeds see until Publish; migration keeps every existing report published | 2d | [x] |
| SUB-1.4 | Designer shows "Draft — not published" and offers Discard draft | Discard restores the published definition | 0.5d | [x] |
| SUB-2.1 | Detect a unique key when a relationship is added | Sales → Region works without marking Region[Region]; a non-unique target still gets a clear error naming the duplicate count | 1d | [x] |
| SUB-2.2 | RLS rules read `[Column]` as the role's own table | `[Region] = "North"` on the Region table works; E2E step passes | 0.5d | [x] |
| SUB-2.3 | Dynamic RLS: `USERPRINCIPALNAME()` and `USERNAME()` from the signed-in user or the embed token's user | A rule `Users[Email] = USERPRINCIPALNAME()` shows each user only their rows, in the app and embedded | 2d | [x] |
| SUB-3.1 | Iterators: SUMX, AVERAGEX, MINX, MAXX, COUNTX over a table with a row expression | Same figures as a hand-written SQL check on the E2E and Warehouse data | 3d | [ ] |
| SUB-3.2 | RELATED (row context across a many-to-one relationship) | `SUMX(Sales, Sales[Qty] * RELATED(Product[Price]))` matches SQL | 1.5d | [ ] |
| SUB-3.3 | SWITCH, IFERROR, COALESCE, SELECTEDVALUE, HASONEVALUE, ISFILTERED, VALUES (in iterators) | Unit tests per function; error messages for wrong argument counts | 2d | [ ] |
| SUB-3.4 | Text, maths and date functions (FORMAT, CONCATENATE, LEFT, RIGHT, MID, UPPER, LOWER, LEN, ROUND, ABS, INT, MOD, POWER, YEAR, MONTH, DAY, TODAY, DATE, DATEDIFF, EOMONTH, WEEKDAY) | Each maps to DuckDB SQL; tests | 2d | [ ] |
| SUB-3.5 | TOTALQTD, TOTALMTD, DATESYTD, PREVIOUSMONTH, PREVIOUSYEAR, PARALLELPERIOD | Same results as the equivalent CALCULATE + date filters | 1.5d | [ ] |
| SUB-3.6 | RANKX and TOPN over the visual's rows (window step after grouping) | Rank by region in a table matches a manual ordering, ties ranked the Power BI way (skip) | 2d | [ ] |
| SUB-3.7 | Measure editor lists the supported functions with signatures | Autocomplete shows every supported function | 1d | [ ] |
| SUB-4.1 | Matrix visual: rows, columns, values, row and column subtotals, expand and collapse | Region × Product matrix totals equal the table visual | 3d | [ ] |
| SUB-4.2 | Combo (columns and a line on one value axis), area, stacked and 100 % stacked column and bar | Each draws from the E2E dataset and cross-filters | 2d | [ ] |
| SUB-4.3 | Filled map from bundled Tanzania regions GeoJSON; point map from latitude and longitude | Warehouses plotted by region; no map tile service needed | 2d | [ ] |
| SUB-4.4 | Remove "draws nothing" types from the gallery until they draw | Every gallery visual draws something with data | 0.5d | [ ] |
| SUB-5.1 | Share a report with people (viewer access to that report only) and revoke | Shared user sees only that report; audit log rows | 2d | [ ] |
| SUB-5.2 | Apps: publish a named set of reports to an audience with its own navigation | An app user sees the app, not the workspace | 3d | [ ] |
| SUB-5.3 | Export a page to PDF on the server (headless Chrome, the QA gate's renderer) | PDF of each Warehouse dashboard matches its screenshot; filters applied | 2d | [ ] |
| SUB-5.4 | Email subscriptions (PDF of a page on a schedule), off until SMTP is configured | With a test SMTP server, a daily subscription arrives with the PDF | 2d | [ ] |
| SUB-5.5 | Alerts on a card or KPI value crossing a threshold, checked after each refresh | An alert fires once per crossing; in-app notice, email when SMTP is set | 2d | [ ] |
| SUB-6.1 | PostgreSQL connector on the `Connector` base, read-only guard included | Same connector test suite as SQL Server passes | 2d | [ ] |
| SUB-6.2 | MySQL connector | Same suite | 1.5d | [ ] |
| SUB-6.3 | OData / REST JSON connector (paged GET, flattening) | Imports a public OData feed into a table | 3d | [ ] |
| SUB-7.1 | Lockout after 5 failed sign-ins in 15 minutes, with audit | Sixth attempt refused for 15 minutes; admin can unlock | 1d | [ ] |
| SUB-7.2 | Change password and admin-issued reset link | Old password stops working; link expires after 1 hour | 1.5d | [ ] |
| SUB-7.3 | OpenID Connect sign-in (Entra ID, Google, Keycloak) | A test identity provider signs a user in; first sign-in creates the user | 3d | [ ] |
| SUB-8.1 | Phone layout per page: separate visual positions on a 360 px-wide canvas, edited in the designer | Designer has Desktop / Phone tabs; unplaced visuals listed | 3d | [ ] |
| SUB-8.2 | Viewer uses the phone layout under 768 px, with 44 px tap targets | The 3 Warehouse dashboards readable on a 390 px phone; gate render check at 390 × 844 | 2d | [ ] |
| SUB-9.1 | E2E suite in the repo (`server/scripts/e2e.py`) and run in CI against a seeded dev server | All review steps pass, including the 3 former gaps | 1.5d | [ ] |

**Phases and effort** (one engineer; days of work, not calendar):

| Phase | Tasks | Effort | Done when |
|-------|-------|--------|-----------|
| 1. Safety | TASK-1 | 3.5d | No one can change a live dashboard by accident |
| 2. Correctness | TASK-2 | 3.5d | The 3 E2E gaps (keys, RLS short form) pass; dynamic RLS works embedded |
| 3. DAX core | TASK-3 | 13d | Typical Power BI measures compile; Warehouse figures unchanged |
| 4. Visuals | TASK-4 | 7.5d | Matrix, combo, area, stacked and maps draw and cross-filter |
| 5. Sharing and export | TASK-5 | 11d | Reports reach non-authors by share, app, PDF, email and alert |
| 6. Data sources | TASK-6 | 6.5d | PostgreSQL, MySQL and OData import and refresh |
| 7. Identity | TASK-7 | 5.5d | Lockout, reset and SSO |
| 8. Phone | TASK-8 | 5d | Dashboards readable on a phone |
| Always | SUB-9.1 | 1.5d | The review re-runs in CI |

About 57 days in total. Phases 1–2 (7 days) are the recommended next step; phase 8 can run in parallel with 5–7.

---

## 3. Execution Log
- [x] Analysis and Plan approved 31 Oct 2026; phases 1 and 2 started.
- [x] Phases 1 and 2 done 31 Oct 2026 (commits listed by `git log --grep magbi-019` and the feat/fix commits before it).

### Phases 1–2 result (31 Oct 2026)

| Part | Where |
|------|-------|
| `my_role` on every workspace (viewer, editor, admin; the dev actor and platform admins are admin) | `api/workspaces.py`, `auth/roles.py` (`role_of`) |
| Viewers see no New dataset, New connection, Embed, Refresh or Open in designer; a viewer who opens the designer is sent to the report view before anything can save | `workspace/*.tsx`, `designer/DesignerPage.tsx` |
| Drafts: `reports.draft_definition` (migration 0007). Autosave sends `draft`, which leaves the published definition and its updated time alone; Publish sends `definition`, which replaces it and clears the draft; `discard_draft` restores the published version. Only editors and admins are sent the draft | `api/reports.py`, `designer/DesignerPage.tsx`, `StatusBar.tsx` |
| The dev server adds new nullable columns to its SQLite database (production runs the migrations) | `server/dev_server.py` |
| A relationship's one side is marked as the key when its data is unique; a repeating column is refused with the count | `api/datasets.py` (`_with_detected_key`) |
| RLS rules read `[Column]` as the role's own table; `USERPRINCIPALNAME()` and `USERNAME()` are the signed-in user's email or the embed token's user (only in rules; a measure gets a clear message) | `engine/rls.py`, `dax/binder.py`, `dax/functions.py` |
| Role members: viewers get the roles they belong to; a viewer in none of a dataset's roles is refused (`RLS_NO_ROLE`); editors and admins see every row; the query cache keys on the user | `model/schema.py`, `api/query.py`, `engine/cache.py`, `model-editor/RlsRolesDialog.tsx` |

**Found while building phase 2**: until now, signed-in viewers got no row-level security at all. Roles applied only to embed tokens and an editor's "view as". Role members close that, and match Power BI's Manage security. Today only the scratch "E2E check" datasets define roles, so no MSD dashboard changes.

**Checks**
- Backend: 541 passed, 17 skipped. Frontend: 78 passed. ruff, mypy, ESLint and the type build are clean.
- End to end: 45 of 46 steps pass. The one failure is RANKX (phase 3). New steps cover a viewer with no edit actions, the designer redirect, draft then Publish, key detection, a refused repeating key, the short RLS form, and a viewer in a role seeing only North.
- QA gate: the 3 Warehouse dashboards pass.

**Note**: string comparison in rules is case-sensitive (DuckDB), unlike DAX. MagBI stores emails in lower case, so a rule like `[Email] = USERPRINCIPALNAME()` needs lower-case emails in the data.

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] The QA gate (`--themes all --quick`) and the E2E suite pass
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
