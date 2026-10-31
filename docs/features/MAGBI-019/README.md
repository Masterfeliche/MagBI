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
| SUB-3.1 | Iterators: SUMX, AVERAGEX, MINX, MAXX, COUNTX over a table with a row expression | Same figures as a hand-written SQL check on the E2E and Warehouse data | 3d | [x] |
| SUB-3.2 | RELATED (row context across a many-to-one relationship) | `SUMX(Sales, Sales[Qty] * RELATED(Product[Price]))` matches SQL | 1.5d | [x] |
| SUB-3.3 | SWITCH, IFERROR, COALESCE, SELECTEDVALUE, HASONEVALUE, ISFILTERED, VALUES (in iterators) | Unit tests per function; error messages for wrong argument counts | 2d | [x] |
| SUB-3.4 | Text, maths and date functions (FORMAT, CONCATENATE, LEFT, RIGHT, MID, UPPER, LOWER, LEN, ROUND, ABS, INT, MOD, POWER, YEAR, MONTH, DAY, TODAY, DATE, DATEDIFF, EOMONTH, WEEKDAY) | Each maps to DuckDB SQL; tests | 2d | [x] |
| SUB-3.5 | TOTALQTD, TOTALMTD, DATESYTD, PREVIOUSMONTH, PREVIOUSYEAR, PARALLELPERIOD | Same results as the equivalent CALCULATE + date filters | 1.5d | [x] |
| SUB-3.6 | RANKX and TOPN over the visual's rows (window step after grouping) | Rank by region in a table matches a manual ordering, ties ranked the Power BI way (skip) | 2d | [x] |
| SUB-3.7 | Measure editor lists the supported functions with signatures | Autocomplete shows every supported function | 1d | [x] |
| SUB-4.1 | Matrix visual: rows, columns, values, row and column subtotals, expand and collapse | Region × Product matrix totals equal the table visual | 3d | [x] |
| SUB-4.2 | Combo (columns and a line on one value axis), area, stacked and 100 % stacked column and bar | Each draws from the E2E dataset and cross-filters | 2d | [x] |
| SUB-4.3 | Filled map from bundled Tanzania regions GeoJSON; point map from latitude and longitude | Warehouses plotted by region; no map tile service needed | 2d | [x] |
| SUB-4.4 | Remove "draws nothing" types from the gallery until they draw | Every gallery visual draws something with data | 0.5d | [x] |
| SUB-5.1 | Share a report with people (viewer access to that report only) and revoke | Shared user sees only that report; audit log rows | 2d | [x] |
| SUB-5.2 | Apps: publish a named set of reports to an audience with its own navigation | An app user sees the app, not the workspace | 3d | [x] |
| SUB-5.3 | Export a page to PDF on the server (headless Chrome, the QA gate's renderer) | PDF of each Warehouse dashboard matches its screenshot; filters applied | 2d | [x] |
| SUB-5.4 | Email subscriptions (PDF of a page on a schedule), off until SMTP is configured | With a test SMTP server, a daily subscription arrives with the PDF | 2d | [x] |
| SUB-5.5 | Alerts on a card or KPI value crossing a threshold, checked after each refresh | An alert fires once per crossing; in-app notice, email when SMTP is set | 2d | [x] |
| SUB-6.1 | PostgreSQL connector on the `Connector` base, read-only guard included | Same connector test suite as SQL Server passes | 2d | [x] |
| SUB-6.2 | MySQL connector | Same suite | 1.5d | [x] |
| SUB-6.3 | OData / REST JSON connector (paged GET, flattening) | Imports a public OData feed into a table | 3d | [x] |
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
- [x] Phases 3, 4 and 5 done 31 Oct 2026.
- [x] Phase 6 done 31 Oct 2026; phase 8 (phone) running alongside in its own session and branch.

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

### Phase 3 result (31 Oct 2026)

64 DAX functions are now supported, up from 24, and each is in the measure editor with its signature.

| Group | Functions | How |
|-------|-----------|-----|
| Iterators | SUMX, AVERAGEX, MINX, MAXX, COUNTX over a table or FILTER(table, condition) | The row expression is aggregated over the home table's rows. Columns of other tables need RELATED, as in Power BI. Measures inside a row expression (context transition) are refused with a clear message, for now |
| RELATED | RELATED(Table[Column]) in a row expression | The table is joined along the relationship |
| Logic | SWITCH (value form and SWITCH(TRUE(), …)), IFERROR, COALESCE | CASE, TRY and COALESCE |
| Context | SELECTEDVALUE, HASONEVALUE, ISFILTERED | Counted over the rows in the current filter context; ISFILTERED looks at filters and slicers |
| Text | CONCATENATE, LEFT, RIGHT, MID, UPPER, LOWER, LEN, FORMAT | FORMAT covers "0", "0.0", "#,0", "#,0.00", "0%", "0.0%" and date patterns such as "dd mmm yyyy" and "mmm yy" |
| Maths | ROUND, ABS, INT, MOD (sign of the divisor), POWER | |
| Dates | YEAR, MONTH, DAY, TODAY, DATE, DATEDIFF, EOMONTH, WEEKDAY (types 1–3) | |
| Time intelligence | TOTALQTD, TOTALMTD, DATESYTD, PREVIOUSMONTH, PREVIOUSYEAR, PARALLELPERIOD | Like TOTALYTD and DATEADD, they read the date filter on the marked date table |
| Ranking | RANKX(ALL(…), expression, , ASC/DESC, SKIP/DENSE) | A window over the visual's rows. Empty arguments now parse as blank, as in Power BI |

Still refused, each with a message saying what to do instead: TOPN (use the visual's Top N filter), VALUES, SUMMARIZE and other table expressions, EARLIER, USERELATIONSHIP, KEEPFILTERS, ALLEXCEPT, MEDIAN, PERCENTILEX and CONCATENATEX.

**Found and fixed**: TOTALYTD never worked inside a visual. To find a measure's home table, the engine compiled it once with no filters, and time intelligence fails without a date filter. `home_table()` now finds it without compiling.

**Differences from Power BI to know**
- IFERROR over an aggregate replaces a blank result too. Division by zero is already blank in MagBI, and DuckDB's TRY cannot wrap an aggregate.
- RANKX ranks the rows the visual shows; its third argument (a value to rank) isn't supported.
- SELECTEDVALUE and HASONEVALUE look at the fact rows in context, so a dimension member with no facts doesn't count.

**Checks**
- Backend: 554 passed. Frontend: 80 passed. ruff, mypy, ESLint and the type build are clean.
- New engine tests compute each function on DuckDB against figures worked out by hand (`tests/test_dax/test_parity_functions.py`).
- All 39 Warehouse measures give identical figures before and after, totals and per warehouse.
- QA gate: the 3 Warehouse dashboards pass. End to end: **47 of 47 steps pass**, including RANKX ranking regions.
- Measure editor, checked in headless Chrome: 64 functions listed, searching "row by row" finds AVERAGEX and SUMX, and a click inserts the function.

**New finding for a later phase**: the code editor in the measure dialog (Monaco) is downloaded from a public CDN (cdn.jsdelivr.net) when the dialog opens. On a network without internet access, the DAX box stays on "Loading…" and measures can't be typed. Bundling Monaco with the app fixes this; it adds a few MB to the build.

### Phase 4 result (31 Oct 2026)

| Visual | What it does | Where |
|--------|--------------|-------|
| Matrix | Up to 3 row fields and 1 column field, several values, a Total column and row, and a subtotal on every row level, with each row's arrow plus Expand all and Collapse all. Every subtotal and total is its own query at that level, so averages, ratios and distinct counts are right (North's average order subtotal is 162.4, not the sum of its products) | `designer/matrix.ts`, `visuals/MatrixVisual.tsx` |
| Stacked column, stacked bar | Series stacked per category, with a thin white edge between segments | `catalog.ts`, `visuals/registry.tsx` |
| 100% stacked column and bar | Each category as shares of 100; the tooltip shows the value and its share | `render.ts` (`percentOfCategory`) |
| Area, stacked area | A line with the area under it filled | |
| Line and column | Column values and line values on one value axis | New `line` well |
| Point map | Points from latitude and longitude (plain columns, never summed), sized by an optional measure; drawn over the region boundaries when installed, otherwise on plain longitude and latitude axes | `visuals/MapVisuals.tsx`, `maps.ts` |
| Filled map | Regions shaded light to dark by value; names matched ignoring case, spaces, hyphens and "Region"; names without a boundary are listed on the map | |

Every visual in the gallery now draws something, and a test keeps it that way.

**Fixed along the way**: on every chart, a top legend sat on top of the title. It now has its own line under the title, and the plot makes room. A chart with one series shows no legend, because the title names it.

**Differences from Power BI to know**
- Line and column uses one value axis, not two. A line on a much smaller scale (for example Orders around 20 against Total sales in thousands) lies flat along the bottom, so it belongs in its own chart. This keeps the reader from comparing two scales as if they were one.
- The matrix takes one column field; Power BI allows several.
- **Region boundaries** (installed 31 Oct 2026 with the owner's approval): `web/public/maps/tanzania-regions.json` holds Tanzania's 31 regions as of 2018, Songwe included. The source is Tanzania's National Bureau of Statistics, published by UN OCHA on the Humanitarian Data Exchange and packaged by geoBoundaries (gbHumanitarian). It's licensed CC BY 3.0 IGO, so every map credits it ("Boundaries: NBS Tanzania / UN OCHA, CC BY 3.0 IGO"). Coordinates are rounded to about 110 m (1.2 MB down to 580 KB). Source, licence and changes are in `web/public/maps/README.md`. The 30-region OpenStreetMap file (2015, ODbL) was rejected because it lacks Songwe.
- Region names are the official ones (Kaskazini Unguja, Mjini Magharibi…). Data that uses English names such as "Zanzibar North" doesn't match, and the map lists those names.

**Checks**
- Frontend: 90 passed (new: chart models, matrix builder, map matching, legend placement, every gallery visual draws). Lint, types and the production build are clean.
- In headless Chrome on the E2E data, 15 of 15 checks pass: each new chart draws; the matrix has Region rows × Product columns plus Total; the grand total equals the engine's (26,244); Expand all opens 12 Product rows; a row's arrow collapses it; North's subtotal is the engine's average; the point map places 4 sites over the region boundaries; the filled map shades real regions (Dodoma, Mwanza, Dar es Salaam Region, Songwe, Kaskazini Unguja), lists only "Zanzibar North" as unmatched, and both maps show the credit.
- End to end: 47 of 47. QA gate: the 3 Warehouse dashboards pass.

### Phase 5 result (31 Oct 2026)

Reports now reach people who don't build them: by a share, an app, a PDF, an email or an alert.

| Part | What it does | Where |
|------|--------------|-------|
| Share a report | An editor shares one report by email and can stop sharing it. The person sees that report and nothing else in the workspace: not its other reports, its model or the edit actions. Row-level security still applies to them. Each share and unshare is in the audit log | `api/sharing.py`, `sharing/__init__.py`, `api/deps.py` (`_granted_read`), `viewer/ShareDialog.tsx` |
| Apps | An editor picks a set of the workspace's reports and an audience, then publishes. The audience opens the app at `/apps/<id>` with its reports as tabs, and sees the reports but not who else is in the audience. Unpublishing it, or taking someone out of the audience, ends their access at once | `api/sharing.py`, `workspace/AppsPanel.tsx`, `viewer/AppView.tsx` |
| Shared with me | The workspace list shows Apps and Shared with me. Someone who only has shares no longer sees "No workspaces yet" | `workspace/SharedWithMe.tsx` |
| Export PDF | The viewer's Export PDF button returns every page of the published report, one page per sheet at the report's own size, as the person sees it, row-level security included. The server prints the viewer's new `?export=1` mode in headless Chrome or Edge. It signs in with a 10-minute token held in the page's session storage, never in the URL. Text in the PDF is real text, so it can be searched | `notify/pdf.py`, `api/notify.py`, `viewer/ReportViewer.tsx` |
| Subscriptions | A person subscribes to a report on a schedule (every day, weekdays, Mondays or the first of the month, at 07:00 server time) and gets it as a PDF by email; Send now checks how it looks. Subscriptions are off until mail is set up (`MAGBI_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_FROM`, `_STARTTLS`), and the dialog says so | `notify/subscriptions.py`, `notify/mail.py`, `viewer/NotifyDialogs.tsx` |
| Data alerts | A person sets an alert on a card, KPI card or gauge: above, at or above, below, at or below, equal to or not equal to a threshold. It is checked after each successful refresh, as that person sees the value, with the visual's own filters. It fires once when the condition becomes true, not again while it stays true. The person gets an in-app notification, plus an email when mail is set up. An alert stops if the person loses access to the report | `notify/alerts.py`, `notify/visuals.py` |
| Notifications | A bell in the top bar shows the unread count. A notification opens its report, and all can be marked read | `workspace/NotificationBell.tsx` |
| Scheduler | Runs in the API server every `MAGBI_SCHEDULER_INTERVAL_SECONDS` (60; 0 turns it off). Each pass queues and runs due scheduled refreshes, checks the alerts after each, then sends due subscriptions | `notify/subscriptions.py` (`run_scheduler`), `main.py` |

New tables (migration 0008): `report_shares`, `apps`, `app_reports`, `app_audience`, `subscriptions`, `alerts`, `notifications`. New settings: `MAGBI_WEB_BASE_URL` (where the web app is served, for export and email links) and `MAGBI_CHROME_PATH` (found automatically when empty).

**Found and fixed**
- **Scheduled refreshes never ran.** Datasets could be given a refresh schedule, but nothing ever called the code that queues them. The new scheduler runs them.
- **Fit to page didn't fit.** The viewer measured its stage before the report had loaded, so on screens narrower than the page (1760 px) the page opened unscaled and ran off the right edge. It now measures again once the report is loaded. The QA gate uses a 1920 px window, which is why this went unnoticed.

**Differences from Power BI to know**
- The PDF shows the report as published, with its saved filters. Slicer choices made on screen aren't carried into it yet.
- Subscriptions send the whole report, not one page, and the schedules are the four offered.
- Alerts fire when the condition becomes true after a refresh, at most once per crossing. Power BI also offers "at most once an hour or a day".
- Sharing is by email address of an existing MagBI user. An admin adds new people first, because there's no invitation email yet.

**Checks**
- Backend: 566 passed, 17 skipped (new: 5 sharing and 7 notify tests: share and revoke, row-level security for a shared person, apps and their audience, alerts firing once per crossing with the visual's filters, losing access, subscriptions needing mail and sending on schedule, PDF export access, the scheduler pass). Frontend: 93 passed. ruff, mypy and the type build are clean.
- In headless Chrome, 14 of 14 checks pass. As an editor: Share, Export PDF, Subscribe and Alerts in the viewer; sharing with a person, and an unknown email refused with a message; adding an alert that shows the card's value now (26,244); the mail notice; Export PDF finishing without an error; the bell's unread count; a notification opening its report; publishing an app from the Apps tab. As an outsider with no workspace: Apps and Shared with me listed, the app opening its report, the dataset's row-level security applied to them, and no Share button. Fit to page fits a 1600 px window.
- PDF export: the 3 Warehouse dashboards export in about 7 s each as one page that matches the dashboard on screen.
- Email: a PDF sent through `SmtpMailer` to a local SMTP server arrives with the subject and the PDF, byte for byte.
- End to end: 47 of 47. QA gate (`--themes all --quick`): 30 of 30 pass, the 3 Warehouse dashboards in every theme.

### Phase 6 result (31 Oct 2026)

MagBI now imports from four kinds of source, up from one.

| Kind | What it reads | How it stays safe | Where |
|------|---------------|-------------------|-------|
| PostgreSQL | Tables, views, materialised and partitioned tables in every schema the login can use; primary keys; row estimates; SQL queries | Settings go to the driver one by one, never pasted into a string. The session is read-only at the server (`default_transaction_read_only`) with a time limit per statement. Every query passes the read-only guard. Rows stream through a server-side cursor | `connectors/postgresql.py` |
| MySQL and MariaDB | Every database the login can read (a MySQL schema is a database), tables and views, primary keys, row estimates, SQL queries | A read-only session set at the server, a time limit (MySQL's and MariaDB's own settings), the session time zone set to UTC, the read-only guard, and an unbuffered cursor | `connectors/mysql.py` |
| OData (v4 and v2 JSON) | Each entity set is a table, with columns, types and keys from `$metadata`; complex types flattened into columns (`ShipTo_City`); pages followed by their next links; the count from `$count` | Only GETs, and only to the configured host: a next link to another host is refused and redirects aren't followed. The password or token travels only in the Authorization header. No SQL ever reaches the service | `connectors/odata.py` |
| REST JSON | One endpoint returning a list of records, or an object holding one (records path), with the next page's URL in the response (next page path). Columns and types are read from the first page | As for OData | `connectors/odata.py` (`format: "json"`) |

Types are planned per source (`plan_columns(columns, dialect)` in `connectors/types.py`). For example: PostgreSQL `timestamptz` is converted to UTC in the query, and arrays, enums and JSON come in as text. MySQL `bigint unsigned` becomes DECIMAL(20,0), and MySQL's zero dates come in blank. OData dates, decimals and times arrive as text in the JSON and are converted on arrival. The host allow-list (`MAGBI_CONNECTOR_ALLOWED_HOSTS`) now also covers web sources, by the host of their URL.

The New Connection form asks for each kind's own settings: SSL mode for PostgreSQL, an optional database for MySQL, and URL, authentication (none, user name and password, or bearer token) and paging for web sources.

**Found and fixed**
- **Datasets made from a connection had no columns.** The dataset wizard creates each table with no columns, and nothing filled them in. The first refresh imported the data, but the model still listed no columns, so no visual or query could use it. SQL Server was affected too; the MSD dashboards weren't, because their models were built by scripts. Now a refresh gives each table with no columns the columns it imported, typed, and with sums as the default for numbers.
- **The connection form never showed a test result.** The server answers `success`, but the form read `ok`, so every Test Connection showed "Connection failed: null", even for SQL Server.

**Checks**
- Backend: 620 passed, 17 skipped (new: 19 PostgreSQL, 17 MySQL and 15 OData/REST tests on fake drivers and a mock web service, as the SQL Server suite does; type planning and conversion; the column fill; secrets and the host allow-list for the new kinds). Frontend: 95 passed. ruff, mypy and the type build are clean.
- A real public OData service (the Northwind demo at services.odata.org): 26 entity sets listed. Orders (830 rows, over several pages, matching the service's own count) and Customers (91) imported with typed columns in 7 s.
- In the app, 15 of 15 checks pass: the four kinds offered, Test Connection on the public service, a missing PostgreSQL server failing with a clear message, saving the connection, browsing 26 tables with types, a 5-row preview, creating a dataset from Orders and Customers, a refresh that succeeds, and a query giving 830 orders in 21 countries. The form shows each kind's own fields, and Test Connection in the form reports "Connected successfully — OData 4.0 at services.odata.org".
- End to end: **49 of 49**, including a real refresh from MSD_ERP (SQL Server, read-only) through the changed importer. QA gate: the 3 Warehouse dashboards pass.

**Not yet checked against a real server**: PostgreSQL and MySQL ran against fake drivers only. No server is installed here and Docker isn't running. A check against real servers needs the official `postgres` and `mysql` Docker images downloaded (about 150 MB each).

---

## 4. Definition of Done (DoD)
- [ ] Code is written and passes all local tests and lints
- [ ] The QA gate (`--themes all --quick`) and the E2E suite pass
- [ ] Single-sentence commit rule followed for all commits
- [ ] SSOT README is fully updated
- [ ] PR description generated from this checklist
