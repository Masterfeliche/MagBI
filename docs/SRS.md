# Software Requirements Specification — MagBI

**Version:** 1.0
**Date:** 29 October 2026
**Classification:** Internal / Confidential
**Author:** Magila Technology Co. Ltd
**Document Status:** Living document — updated as the product evolves

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Problem We Are Solving](#2-the-problem-we-are-solving)
3. [Vision and Scope](#3-vision-and-scope)
4. [Stakeholder Analysis](#4-stakeholder-analysis)
5. [User Personas and Workflows](#5-user-personas-and-workflows)
6. [Functional Requirements](#6-functional-requirements)
7. [Non-Functional Requirements](#7-non-functional-requirements)
8. [Data Requirements](#8-data-requirements)
9. [Integration Requirements](#9-integration-requirements)
10. [Security Requirements](#10-security-requirements)
11. [Deployment and Infrastructure](#11-deployment-and-infrastructure)
12. [Constraints and Assumptions](#12-constraints-and-assumptions)
13. [Risk Analysis](#13-risk-analysis)
14. [Acceptance Criteria](#14-acceptance-criteria)
15. [Phased Delivery Plan](#15-phased-delivery-plan)
16. [Glossary](#16-glossary)

---

## 1. Executive Summary

### 1.1 What this document is

This Software Requirements Specification defines what MagBI must do, why it
must do it, and how we will know it works. It is written for three audiences:
the engineering team building MagBI, the business stakeholders who will use it,
and the AI agents that will contribute to its development.

### 1.2 The one-sentence pitch

MagBI is a self-hosted business intelligence engine that turns operational data
in our ERP (and any SQL database) into interactive dashboards that anyone in the
organisation can use to make better decisions — without per-user licensing fees,
without fighting a third-party embed model, and without waiting for IT to write
a custom report.

### 1.3 Why now

We operate MSD ERP — a system with 8 operational modules (Finance, HR,
Procurement, Transport, Sales, CRM, WMS, PME), 55+ published dashboards, and
hundreds of SSRS reports. Today, these dashboards are built in Power BI Desktop,
published to Power BI Service, and embedded in the ERP via an iframe. This works
but it has three compounding problems:

1. **Cost at scale.** Every user who views an embedded dashboard requires
   Power BI capacity. As the number of ERP deployments and users grows, this
   becomes a major recurring cost that scales linearly with adoption — the
   exact opposite of what software economics should look like.

2. **Integration friction.** The ERP's user system, row-level security, theming,
   and navigation must be glued to Power BI's authentication, RLS, and embed API.
   Every change to either side risks breaking the integration. The ERP strips
   page backgrounds when embedding (`BackgroundType.Transparent`), the ERP's
   "Manage BI Dashboards" registry is a separate system from Power BI's
   workspace, and single sign-on between the ERP and Power BI is perpetual
   maintenance.

3. **Feature ceiling.** We hit the limits of what Power BI allows inside an
   embed: custom interactions, deep-linking into ERP pages from chart clicks,
   real-time data push from ERP events, and custom visuals that match our
   design language all require workarounds or are impossible.

MagBI eliminates all three by owning every layer — from the SQL query to the
pixel on screen.

### 1.4 Where this goes

MagBI starts as an internal tool for MSD ERP. But the architecture is
general-purpose: any organisation with a SQL database can connect, model, and
visualise their data. The second phase offers MagBI as a product — either
self-hosted by clients or offered as a service — for businesses that want
embedded analytics without the licensing cost of Power BI, Tableau, or Looker.

---

## 2. The Problem We Are Solving

This section names the actual pain points — not abstract "business needs" but
the specific, daily frustrations that real people experience. Every feature in
this SRS traces back to at least one of these problems.

### 2.1 The data is there but the insight is not

The ERP stores everything: every invoice, every purchase order, every employee
attendance record, every fleet movement, every warehouse transaction. But a
department head who wants to know "What is our procurement spend trend over the
last 6 months, and which vendors are growing fastest?" must either:

- Ask IT to write a SQL query and email the results (days of turnaround)
- Open an SSRS report that shows a flat table with no visual context
- Open a Power BI dashboard that may or may not have the right measure

The data exists. The tools to explore it do not exist in a form that a
non-technical manager can use independently, on demand, without waiting.

**Requirement this drives:** Self-service analytics — drag a field, see a chart,
filter by clicking. No SQL, no tickets, no waiting.

### 2.2 Reports are built by specialists and cannot be changed

Today, building a dashboard requires:
- A developer who knows Power BI Desktop, DAX, and the ERP data model
- A publishing process (Desktop → Service → embed registration → role grants)
- A review cycle (does this measure match finance's definition?)

When a stakeholder says "Can we add a column?" or "Can we see this by region
instead of by department?", the answer is "File a request." This creates a
bottleneck where 2-3 people build all the dashboards, and everyone else waits.

**Requirement this drives:** A report designer that trained analysts (not just
developers) can use. The designer must be web-based (no desktop app install),
must expose the data model visually, and must allow non-destructive
experimentation (undo/redo, draft reports, preview before publish).

### 2.3 Embedding is fragile and expensive

Power BI Embedded requires:
- An Azure AD app registration
- A Power BI Embedded capacity (A-SKU or EM-SKU)
- A service principal with workspace access
- A token exchange flow (service principal → embed token → iframe)
- RLS role mapping from ERP users to Power BI roles

Every component in this chain can break independently. The embed token expires;
the capacity runs out of render units; the RLS mapping drifts when someone adds
a new ERP role. Debugging requires knowledge of both systems.

**Requirement this drives:** Native embedding with zero external dependencies.
The ERP issues a JWT with the user's identity and permissions; MagBI trusts that
JWT and applies the right data filters. No Azure, no capacity SKUs, no token
exchange dance.

### 2.4 Dashboards look foreign inside the ERP

Power BI dashboards have their own look and feel — different fonts, different
button styles, different filter controls. Even with careful theming, they look
"embedded" rather than "native." Users notice. It erodes trust in the tool.

**Requirement this drives:** Full theme control. MagBI dashboards must inherit
the host application's design system — colours, typography, spacing, component
style. A dashboard inside the ERP should be indistinguishable from a native
ERP page.

### 2.5 Data freshness is a mystery

When a user looks at a dashboard, they do not know when the data was last
refreshed. Was this number calculated 5 minutes ago or 5 hours ago? The refresh
status is buried in Power BI Service's admin UI, which end users never see.

**Requirement this drives:** Visible refresh status on every dashboard — "Last
refreshed: 14 minutes ago" — plus the ability to trigger a manual refresh from
the dashboard itself (for users with the right role).

### 2.6 Row-level security is bolted on, not built in

In Power BI, RLS is defined in the data model (DAX filters on roles) and then
mapped to Azure AD groups or user emails. The ERP has its own permission system
— which departments a user can access, which cost centres, which branches. These
two systems must be synchronised.

Today: when the ERP adds a new branch, someone must update the Power BI RLS
role. If they forget, users at that branch see no data — or worse, see data
from another branch.

**Requirement this drives:** RLS that reads directly from the ERP's permission
system. When MagBI receives a query for a user, it calls the ERP's API (or
reads a shared table) to get the user's data permissions, and injects those as
filters. No separate role mapping, no synchronisation, no drift.

### 2.7 Small and medium businesses cannot afford BI

Beyond our own ERP, every business we talk to has the same story: they have
data in a database, they want dashboards, and they cannot justify the per-user
cost of Power BI or Tableau for 50+ users. They end up with Excel reports
emailed weekly — which are always stale, often wrong, and never interactive.

**Requirement this drives:** MagBI must be deployable at a cost that makes BI
accessible to a 50-person company. Self-hosted (their server, their data, no
recurring per-user fee) or offered as a managed service at a flat rate.

### 2.8 Institutional knowledge lives in people's heads

When the one person who built the Finance dashboards leaves, no one knows what
`[Total Revenue LY MTD Adjusted]` actually calculates, or why the Procurement
dashboard filters out `Status = 'Draft'`. The measures, business rules, and
domain context are locked in DAX formulas and report configurations that
non-specialists cannot read.

**Requirement this drives:** A semantic model that serves as documentation.
Every measure has a description field. Every relationship has a purpose.
The model editor shows the data model visually — not as code but as a diagram
that a business analyst can read and understand. The knowledge base chapters
(docs/kb/) complement this as living documentation.

---

## 3. Vision and Scope

### 3.1 Product vision

> Make it possible for any person in any organisation to answer their own
> data questions, interactively, without writing code, without per-user fees,
> and without leaving the application where they work.

### 3.2 Scope boundaries

**In scope:**
- Connect to SQL databases and files (CSV, Excel)
- Shape and transform data visually
- Build a semantic model (tables, relationships, measures)
- Design interactive reports on a drag-and-drop canvas
- Publish reports to a web-based viewer
- Embed reports inside other applications (iframe + JS SDK)
- Row-level security tied to the host application's user system
- Scheduled and manual data refresh
- Self-hosted deployment (Docker)

**Out of scope (v1):**
- Real-time streaming data (we refresh periodically, not continuously)
- Notebook/code interface (no Python/R cells)
- Data warehouse management (we read from existing databases)
- Predictive analytics / ML models
- Natural language query ("show me revenue by month" typed in English)
- Mobile-native apps (responsive web is the mobile story for v1)
- Multi-tenant SaaS hosting (v1 is single-tenant / self-hosted)

**Future scope (v2+):**
- Natural language query powered by LLM
- Alerting (notify me when KPI crosses threshold)
- Collaborative annotations (comment on a data point)
- REST API connectors (pull from any HTTP API)
- Multi-tenant SaaS with tenant isolation

### 3.3 Success metrics

| Metric | Target | How measured |
|--------|--------|-------------|
| Dashboard load time | < 3 seconds for 90th percentile | Query engine response time + render time |
| Time to first chart (new user) | < 15 minutes from "Get Data" to published chart | User testing sessions |
| Data refresh reliability | 99% of scheduled refreshes succeed | Refresh history log |
| ERP integration time | < 1 day to embed MagBI in a new ERP instance | Integration engineering log |
| User adoption | 80% of ERP dashboard users switch from Power BI within 3 months | Login analytics |
| Cost per user | $0 marginal cost per additional viewer | Infrastructure cost / active users |

---

## 4. Stakeholder Analysis

### 4.1 Internal stakeholders

| Stakeholder | Role | Interest | Influence |
|-------------|------|----------|-----------|
| **Department heads** (Finance, HR, Procurement, etc.) | Consumers of dashboards | Want accurate, timely, interactive data for decision-making | High — they determine adoption |
| **Data analysts** | Build and maintain dashboards | Want a productive tool that saves time vs. Power BI Desktop | High — they build the content |
| **ERP development team** | Integrate MagBI into the ERP | Want clean APIs, simple embedding, minimal maintenance | High — they own the integration |
| **IT / infrastructure** | Deploy and operate MagBI | Want simple deployment, monitoring, backup, security | Medium — they operate the system |
| **Executive leadership** | Sponsor the project | Want cost reduction, competitive advantage, IP ownership | High — they fund the project |

### 4.2 External stakeholders (future)

| Stakeholder | Role | Interest |
|-------------|------|----------|
| **Client organisations** (using MSD ERP) | Deploy MagBI alongside their ERP instance | Want BI without additional licensing |
| **Independent businesses** | Deploy MagBI standalone | Want affordable, self-hosted BI |
| **Third-party developers** | Build custom visuals or connectors | Want documented APIs and extension points |

---

## 5. User Personas and Workflows

### 5.1 Persona: Department Head (Consumer)

**Name:** Amina, Director of Finance
**Technical skill:** Uses Excel daily, comfortable with pivot tables, does not write SQL
**Goal:** See the financial position of the organisation at any time, without asking anyone

**Typical workflow:**
1. Opens the ERP, navigates to Finance → Analytics
2. Sees a dashboard with revenue, expenses, and cash position
3. Clicks on "Q3" in the revenue chart to filter everything to Q3
4. Notices procurement expenses are higher than expected
5. Clicks "Drill down" on the procurement card to see by vendor
6. Exports the vendor breakdown to Excel for a meeting
7. Closes the dashboard — total time: 3 minutes

**What MagBI must do for Amina:**
- Load the dashboard in < 3 seconds
- Cross-filter works with a single click
- Drill-down is available where the data model supports it
- Export to Excel/CSV is one click
- The dashboard uses the same visual language as the rest of the ERP
- She never sees a login screen (SSO from the ERP)
- She only sees data for her cost centres (RLS)

### 5.2 Persona: Data Analyst (Builder)

**Name:** Joseph, Senior Data Analyst
**Technical skill:** Knows SQL, knows Power BI DAX, understands star schemas
**Goal:** Build and maintain dashboards for all departments

**Typical workflow:**
1. Receives a request: "HR needs an attendance dashboard"
2. Opens MagBI's designer, creates a new report
3. Connects to the ERP database, selects the attendance tables
4. Builds a semantic model: adds relationships, creates measures
   (`Attendance Rate = DIVIDE(COUNTROWS(FILTER(...)), ...)`)
5. Drags fields onto visuals: a bar chart for attendance by department,
   a KPI card for overall rate, a table for detail
6. Adds filters: date range, department, employee category
7. Tests with different RLS roles ("View as HR Manager")
8. Publishes the dashboard
9. Registers it in the ERP's BI Dashboard menu
10. Total time: 2-4 hours (vs. 1-2 days in Power BI Desktop + publish cycle)

**What MagBI must do for Joseph:**
- Web-based designer (no desktop app to install and update)
- Familiar DAX syntax for measures
- Visual model editor (diagram view, not code)
- Live preview as he builds
- Undo/redo (he experiments a lot)
- RLS testing without publishing
- One-click publish from designer to live

### 5.3 Persona: ERP Developer (Integrator)

**Name:** Sarah, Full-Stack Developer
**Technical skill:** Writes C#/.NET, JavaScript, SQL; maintains the ERP codebase
**Goal:** Embed MagBI dashboards into the ERP with minimal ongoing maintenance

**Typical workflow:**
1. Adds MagBI's JS SDK to the ERP's frontend bundle
2. When a user navigates to a BI page, the ERP backend generates a JWT
   containing the user's ID, roles, and data permissions
3. The frontend passes the JWT to MagBI's embed endpoint
4. MagBI returns an embed token scoped to the specific report + user's RLS
5. The frontend renders the dashboard in an iframe
6. The SDK handles token refresh, theme synchronisation, and event callbacks

**What MagBI must do for Sarah:**
- A documented REST API with OpenAPI spec
- A JS SDK with TypeScript types
- JWT-based auth that trusts the ERP's token (no separate login)
- Theme injection (pass the ERP's CSS variables, MagBI applies them)
- Event callbacks (dashboard loaded, visual clicked, filter changed)
- Programmatic filter control (set filters from the ERP's sidebar)

### 5.4 Persona: IT Administrator (Operator)

**Name:** Frank, Systems Administrator
**Technical skill:** Linux, Docker, networking, database administration
**Goal:** Deploy MagBI, keep it running, and ensure data security

**Typical workflow:**
1. Runs `docker compose up` to start MagBI
2. Configures environment variables (database URLs, secrets)
3. Sets up a reverse proxy with TLS
4. Configures scheduled data refreshes (every 30 minutes for Finance,
   daily for HR)
5. Monitors the health dashboard for failed refreshes or slow queries
6. Backs up PostgreSQL (metadata) and DuckDB files (analytical data) nightly

**What MagBI must do for Frank:**
- Single-command deployment (Docker Compose)
- Health check endpoints (`/health`, `/ready`)
- Prometheus metrics for monitoring
- Structured logs (JSON) for centralised logging
- Configurable refresh schedules
- Backup-friendly storage (files + PostgreSQL dump)
- No phone-home, no telemetry to external servers

---

## 6. Functional Requirements

Requirements are numbered FR-XXX and prioritised:
- **P1** = Must have for launch (blocks ERP integration)
- **P2** = Must have for internal adoption (blocks department usage)
- **P3** = Important for product viability (blocks external use)
- **P4** = Nice to have (improves experience)

### 6.1 Data Connection

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-001 | Connect to SQL Server databases | P1 | Given valid credentials, the system lists all tables and views in the database |
| FR-002 | Connect to PostgreSQL databases | P2 | Same as FR-001 for PostgreSQL |
| FR-003 | Connect to MySQL databases | P3 | Same as FR-001 for MySQL |
| FR-004 | Import CSV and Excel files | P2 | User uploads a file; system infers schema and imports data |
| FR-005 | Test connection before saving | P1 | System validates credentials and network connectivity; shows success or error |
| FR-006 | Store connection credentials securely | P1 | Credentials encrypted at rest (AES-256-GCM); never logged or exposed in API responses |
| FR-007 | Browse tables and preview data | P1 | User sees table list, column names/types, and first 200 rows before importing |

### 6.2 Data Transformation

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-010 | Visual step-based transform editor | P2 | User adds, reorders, and deletes transform steps via UI; preview updates after each step |
| FR-011 | Filter rows by condition | P1 | Given a column and condition, only matching rows remain in preview |
| FR-012 | Remove / rename / reorder columns | P1 | User can select columns to keep, rename columns, or change column order |
| FR-013 | Change column data types | P1 | User can cast a column (e.g., string → date, string → integer) |
| FR-014 | Add calculated columns | P2 | User defines an expression; new column appears in preview |
| FR-015 | Query folding for transforms | P2 | Foldable steps compile to SQL and execute on the source database; fold boundary visible in UI |
| FR-016 | Group by and aggregate | P2 | User selects grouping columns and aggregation functions; result shows grouped data |
| FR-017 | Pivot and unpivot | P3 | User can reshape data between wide and long formats |

### 6.3 Semantic Model

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-020 | Define tables, columns, and data types | P1 | Model stores table and column metadata; data types map correctly from source |
| FR-021 | Define relationships between tables | P1 | User creates many-to-one relationships; the query engine uses them to generate joins |
| FR-022 | Auto-detect relationships | P3 | System suggests relationships based on column name and type matching |
| FR-023 | Define measures (DAX-lite formulas) | P1 | User writes a formula; system validates syntax and compiles to SQL |
| FR-024 | Visual model editor (diagram view) | P2 | User sees tables as boxes and relationships as lines; can drag to create relationships |
| FR-025 | Measure editor with syntax highlighting | P2 | Monaco-based editor with DAX-lite tokenisation, autocomplete for table/column names |
| FR-026 | Date table auto-generation | P2 | Given a date column, system generates a full date dimension table (year, quarter, month, week, day, fiscal year) |
| FR-027 | Mark a table as date table | P2 | Marking enables time intelligence functions (SAMEPERIODLASTYEAR, etc.) |
| FR-028 | Calculated columns | P3 | User defines a DAX expression; column value computed at refresh time |
| FR-029 | Model validation | P2 | System reports errors (ambiguous paths, circular references) and warnings (unused tables) |

### 6.4 Row-Level Security

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-030 | Define RLS roles with filter expressions | P1 | Admin defines a role with DAX filter (e.g., `[Department] = @UserDepartment`) |
| FR-031 | Dynamic RLS parameters from JWT | P1 | Embed token carries user attributes; RLS filter substitutes `@UserDepartment` with the user's actual department |
| FR-032 | RLS filters are non-removable | P1 | No DAX function (ALL, REMOVEFILTERS) can bypass an RLS filter |
| FR-033 | "View as role" testing in designer | P2 | Analyst can preview a dashboard as if they were a user in a specific RLS role |
| FR-034 | Multiple RLS roles per user | P2 | A user in multiple roles sees the union of data permitted by each role |

### 6.5 Report Designer

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-040 | Web-based drag-and-drop report designer | P1 | User creates a report by dragging visuals onto a canvas in the browser |
| FR-041 | Free-form canvas (1760 × 990 pixels) | P1 | Visuals are positioned absolutely; snap-to-grid and smart guides aid alignment |
| FR-042 | Add visuals from a type palette | P1 | User picks from bar, line, pie, card, table, matrix, slicer, scatter, treemap, funnel, gauge, waterfall, map |
| FR-043 | Configure visuals via field wells | P1 | User drags fields from the data pane into wells (Axis, Values, Legend, etc.); chart updates live |
| FR-044 | Auto-aggregation in wells | P1 | When a numeric column is dropped in Values, it defaults to SUM; user can change to COUNT, AVG, MIN, MAX |
| FR-045 | Visual property pane | P2 | User configures colours, labels, data labels, titles, borders, and conditional formatting |
| FR-046 | Cross-filtering between visuals | P1 | Clicking a data point in one visual filters all others on the page |
| FR-047 | Filter pane (report / page / visual level) | P1 | User adds filters at three levels; filters combine with AND logic |
| FR-048 | Undo / redo | P2 | Ctrl+Z / Ctrl+Y undoes and redoes any design action |
| FR-049 | Copy / paste visuals | P2 | User can duplicate visuals within a page or across pages |
| FR-050 | Report themes | P2 | User can apply a theme (colours, fonts); theme can be inherited from the host application |
| FR-051 | One-click publish | P1 | User clicks "Publish"; the report becomes available in the viewer immediately |
| FR-052 | Draft / published states | P2 | Changes in the designer do not affect the live version until explicitly published |

### 6.6 Report Viewing

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-060 | Interactive report viewer | P1 | Users view published reports with full cross-filtering, drill-down, and tooltips |
| FR-061 | Export to Excel / CSV | P2 | User exports the data behind any visual as an Excel or CSV file |
| FR-062 | Export to PDF | P3 | User exports the entire report page as a PDF |
| FR-063 | Full-screen mode | P2 | User can view a dashboard in full-screen (presentation mode) |
| FR-064 | Visible refresh timestamp | P1 | Every dashboard shows "Last refreshed: X minutes ago" |
| FR-065 | Manual refresh trigger | P2 | Users with Editor role can trigger an on-demand data refresh from the viewer |
| FR-066 | Bookmark / saved views | P3 | User can save a set of filters as a named bookmark |

### 6.7 Embedding

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-070 | Embed via iframe + JS SDK | P1 | Host application loads MagBI in an iframe; SDK provides typed API |
| FR-071 | Embed token with resolved RLS | P1 | Service token → POST /embed/token → embed token with user's data permissions baked in |
| FR-072 | Theme injection from host | P1 | Host passes CSS variables or a theme object; MagBI applies it to the dashboard |
| FR-073 | Programmatic filter control | P1 | Host application can set/get/clear filters via the SDK |
| FR-074 | Event callbacks | P2 | SDK emits events: loaded, error, filterChanged, visualClicked |
| FR-075 | Token auto-refresh | P1 | SDK automatically requests a new embed token before the current one expires |
| FR-076 | Locked filters | P2 | Host can specify filters that the viewer cannot remove (e.g., always filter to their branch) |

### 6.8 Data Refresh

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-080 | Scheduled automatic refresh | P1 | Admin configures a cron schedule; data refreshes automatically |
| FR-081 | Manual refresh via API | P1 | POST to /api/refresh/{datasetId} triggers an immediate refresh |
| FR-082 | Zero-downtime refresh | P1 | Users continue querying old data while new data imports; swap is atomic |
| FR-083 | Refresh history and status | P1 | API returns last N refreshes with status, duration, and error details |
| FR-084 | Refresh failure notification | P2 | On failure, system logs the error and optionally sends a webhook notification |
| FR-085 | Incremental refresh | P3 | For date-partitioned tables, only reimport data newer than a cutoff date |
| FR-086 | Concurrent refresh limits | P1 | At most 1 refresh per dataset, 3 per workspace, 10 platform-wide |

### 6.9 Administration

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| FR-090 | Workspace management | P1 | Admin creates workspaces; assigns users with roles (admin/editor/viewer) |
| FR-091 | Audit log | P2 | System records who did what and when (login, publish, refresh, settings change) |
| FR-092 | User management | P1 | Admin adds/removes users; assigns workspace roles |
| FR-093 | Service token management | P1 | Admin creates service tokens for server-to-server authentication |
| FR-094 | Usage metrics | P3 | Admin sees dashboard view counts, query performance percentiles, top users |

---

## 7. Non-Functional Requirements

### 7.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-001 | Dashboard load time (first contentful paint) | < 2 seconds (cold cache), < 500ms (warm cache) |
| NFR-002 | Query response time (simple aggregation, < 1M rows) | < 500ms at p90 |
| NFR-003 | Query response time (complex multi-measure, < 10M rows) | < 3 seconds at p90 |
| NFR-004 | Report designer interaction response | < 200ms for drag/drop, resize, property change |
| NFR-005 | Data refresh throughput | Import 1M rows / minute / table (limited by source) |
| NFR-006 | Concurrent viewers | Support 100 simultaneous viewers without degradation |

### 7.2 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-010 | API uptime | 99.5% (excluding planned maintenance) |
| NFR-011 | Data refresh success rate | > 99% (failures due to source unavailability do not count) |
| NFR-012 | Zero data loss on refresh failure | If a refresh fails mid-import, the previous data remains intact and queryable |
| NFR-013 | Graceful degradation | If Redis is down, queries still work (no caching); if a visual errors, other visuals still render |

### 7.3 Scalability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-020 | Dataset size | Support datasets up to 10GB in DuckDB (100M+ rows across tables) |
| NFR-021 | Reports per workspace | No hard limit; UI should handle 500+ reports without lag |
| NFR-022 | Visuals per report page | Support 30+ visuals on a single page without noticeable render delay |
| NFR-023 | Horizontal scaling | API servers can be added behind a load balancer for more capacity |

### 7.4 Usability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-030 | Time to first chart (new user) | < 15 minutes from connection to published chart |
| NFR-031 | Learning curve | An analyst who knows Power BI should be productive in MagBI within 1 day |
| NFR-032 | Keyboard accessibility | All designer actions reachable via keyboard; tab order is logical |
| NFR-033 | Error messages | Every error shows what went wrong AND what the user can do about it |

### 7.5 Maintainability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-040 | Code test coverage | > 80% for server-side code (unit + integration) |
| NFR-041 | API documentation | OpenAPI spec auto-generated from FastAPI; always current |
| NFR-042 | Knowledge base | docs/kb/ chapters updated with every major feature change |
| NFR-043 | Deployment reproducibility | `docker compose up` produces the same system on any Docker-capable machine |

---

## 8. Data Requirements

### 8.1 Source data

MagBI reads from external databases — it does not own the source data. The ERP
database (MSD_ERP) is the primary source for the initial deployment.

**Supported sources (v1):** SQL Server, PostgreSQL, MySQL, CSV, Excel, DuckDB

**Data volumes (MSD ERP baseline):**
| Module | Estimated rows (largest table) | Growth rate |
|--------|-------------------------------|-------------|
| Finance | 2M transactions | 50K/month |
| HR | 500K attendance records | 20K/month |
| Procurement | 1M purchase orders | 30K/month |
| Transport | 3M fleet movements | 100K/month |
| Sales | 1.5M invoices | 40K/month |
| WMS | 2M warehouse transactions | 60K/month |

### 8.2 Analytical storage

Imported data is stored in DuckDB files — one file per dataset version. The
file is the unit of:
- **Query:** the query engine opens the file, runs SQL, returns results
- **Refresh:** the import pipeline creates a new file, then atomically swaps it
- **Backup:** copy the file to backup storage
- **Deletion:** delete the file

### 8.3 Metadata storage

Metadata (workspaces, datasets, reports, users, audit log) is stored in
PostgreSQL. This is transactional data with referential integrity requirements
that a relational database handles well.

### 8.4 Data retention

- **Analytical data:** Current version + 5 archived versions per dataset
  (configurable). Older archives are automatically deleted.
- **Metadata:** Retained indefinitely. Audit log entries older than 2 years
  may be archived.
- **Query cache:** Evicted on LRU basis or on dataset refresh.

---

## 9. Integration Requirements

### 9.1 MSD ERP Integration

This is the primary integration and the acceptance test for MagBI.

| ID | Requirement | Detail |
|----|-------------|--------|
| IR-001 | SSO from ERP | ERP issues a JWT; MagBI validates it. User never sees a MagBI login screen. |
| IR-002 | RLS from ERP permissions | JWT carries the user's department, branch, and role; MagBI uses these as RLS filter parameters. |
| IR-003 | Theme from ERP | ERP passes its CSS variables (MSD navy, blue, orange palette); MagBI applies them. |
| IR-004 | Dashboard registry | ERP's "Manage BI Dashboards" (vecfg.BiDashboard) links to MagBI reports instead of Power BI. URL format: `/bi-analytics/<slug>`. |
| IR-005 | Navigation integration | Clicking a data point in MagBI can navigate to an ERP page (e.g., click an invoice number → open the invoice in the ERP). |
| IR-006 | Security Object grants | ERP's role-based access uses Security Objects (e.g., "Finance Pages") to control who sees which dashboard menu items. |

### 9.2 Generic Integration (for other host applications)

| ID | Requirement | Detail |
|----|-------------|--------|
| IR-010 | Standalone mode | MagBI runs independently with its own login UI for organisations that do not embed it. |
| IR-011 | OIDC / OAuth2 | MagBI can delegate authentication to an external identity provider. |
| IR-012 | Webhook notifications | MagBI sends webhooks on key events (refresh completed, refresh failed) to any URL. |
| IR-013 | REST API for automation | All operations available via REST API for scripting and CI/CD integration. |

---

## 10. Security Requirements

| ID | Requirement | Detail |
|----|-------------|--------|
| SR-001 | Authentication | JWT-based. Tokens signed with HS256 (symmetric) or RS256 (asymmetric, for external IdPs). |
| SR-002 | Authorisation | Workspace roles: admin (full control), editor (build reports), viewer (view only), embed-only (iframe access). |
| SR-003 | Row-level security | Filter expressions evaluate per query; injected into every SQL statement; non-removable by user-facing functions. |
| SR-004 | Credential encryption | Database connection credentials encrypted with AES-256-GCM at rest. Encryption key from server config (not stored in the database). |
| SR-005 | TLS | All HTTP traffic over TLS in production. Internal service communication may use plain HTTP within a private network. |
| SR-006 | SQL injection prevention | All user-supplied values parameterised via sqlglot (never interpolated into SQL strings). |
| SR-007 | CORS | Configurable allowed origins; default: same-origin only. |
| SR-008 | Rate limiting | API rate-limited per user (default: 100 requests/minute) and per IP (default: 500 requests/minute). |
| SR-009 | Audit logging | All authentication events, data access, and administrative actions logged with timestamp, user, and action. |
| SR-010 | No external telemetry | MagBI sends no data to external servers. All data stays on the deployment. |
| SR-011 | Embed token scoping | Embed tokens are scoped to one report; cannot be used to access other reports or the admin API. |
| SR-012 | Input validation | All API inputs validated via Pydantic models; malformed requests rejected with 422. |

---

## 11. Deployment and Infrastructure

### 11.1 Minimum deployment

| Component | Resource | Notes |
|-----------|----------|-------|
| API server | 2 CPU, 4GB RAM | Handles HTTP + query engine |
| Worker | 2 CPU, 4GB RAM | Handles background data refresh |
| PostgreSQL | 1 CPU, 2GB RAM | Metadata store |
| Redis | 1 CPU, 1GB RAM | Cache + queue |
| Storage | 50GB SSD | DuckDB files + PostgreSQL data |

**Total: ~8 CPU, 11GB RAM, 50GB storage** — runs on a single mid-range server
or a small cloud VM.

### 11.2 Production deployment

- Multiple API servers behind a load balancer (nginx or cloud LB)
- Multiple Celery workers (one per CPU core for refresh parallelism)
- PostgreSQL with streaming replication (primary + read replica)
- Redis Sentinel or Redis Cluster for HA
- DuckDB files on shared storage (NFS, EFS, or cloud block storage)

### 11.3 Deployment method

Docker Compose for development and small deployments. Docker images published
to a private registry for production. Kubernetes manifests as a future
deliverable.

---

## 12. Constraints and Assumptions

### 12.1 Constraints

| Constraint | Impact |
|------------|--------|
| Python's GIL | CPU-bound Python code (DAX compilation, transforms) cannot use multiple cores in a single process. Mitigated by DuckDB (C++ engine), async I/O (no blocking), and Celery workers (separate processes). |
| DuckDB single writer | Only one process can write to a DuckDB file at a time. Mitigated by the atomic swap pattern (write to a new file, rename when done). |
| Browser rendering limits | A single canvas with 50+ ECharts instances may lag on low-end devices. Mitigated by virtualisation (only render visuals in the viewport) and canvas (not SVG) rendering for complex charts. |
| Network between MagBI and source DB | Import speed is limited by the network between MagBI and the source database. For on-premises deployments, MagBI should be on the same network as the database. |

### 12.2 Assumptions

| Assumption | Risk if wrong |
|------------|---------------|
| Users have a modern browser (Chrome, Edge, Firefox, Safari — last 2 versions) | Old browsers may not support ES2022 features or Canvas API |
| Source databases are available during scheduled refresh windows | Refreshes will fail; need retry logic |
| MSD ERP can issue JWTs with user attributes | If not, we need a different auth integration pattern |
| The team has Python and TypeScript skills | If not, onboarding cost increases |
| Docker is available in deployment environments | If not, we need bare-metal installation docs |

---

## 13. Risk Analysis

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | DAX-lite does not cover a critical Power BI formula in existing dashboards | Medium | High — blocks migration | Audit all 55 existing dashboards for DAX functions used; ensure coverage before migration. Provide a compatibility matrix. |
| R2 | DuckDB query performance is insufficient for the largest datasets | Low | High — users see slow dashboards | Profile with realistic data volumes early. DuckDB handles 100M+ rows well in benchmarks; our datasets are smaller. Add query caching as a fallback. |
| R3 | Report designer UX is too complex for non-technical users | Medium | Medium — limits adoption | Test with real analysts early and often. Provide templates for common dashboard patterns. Build a "Quick Chart" wizard for the simplest case. |
| R4 | Embedding integration with ERP takes longer than expected | Medium | High — delays deployment | Build the embed SDK and integration contract first (before the full designer). Test with a minimal ERP page early. |
| R5 | Scope creep delays delivery | High | High — never ships | Enforce the phased delivery plan. Phase 1 has a hard feature freeze. Every feature request goes to Phase 2 or later. |
| R6 | Security vulnerability in the query engine | Low | Critical — data exposure | All values parameterised (never interpolated). RLS filters are non-removable. Security review before Phase 1 launch. |
| R7 | Single developer (bus factor = 1) | High | High — project stalls | Knowledge base and SRS exist to reduce bus factor. AI agents can continue development from documentation. |

---

## 14. Acceptance Criteria

### 14.1 Phase 1 acceptance (internal launch)

MagBI is accepted for internal use when:

- [ ] All P1 functional requirements pass their acceptance criteria
- [ ] The 8 existing ERP modules' dashboards render correctly in MagBI
- [ ] SSO from the ERP works without a separate login
- [ ] RLS correctly restricts data based on ERP user permissions
- [ ] Dashboard load time is < 3 seconds (p90) on the production server
- [ ] Data refresh runs reliably on a 30-minute schedule for 7 consecutive days
- [ ] Three department heads (Finance, HR, Procurement) confirm the dashboards
  match or exceed the Power BI versions in usability
- [ ] Zero critical or high-severity security findings in a review

### 14.2 Phase 2 acceptance (product readiness)

MagBI is accepted as a product when:

- [ ] All P2 functional requirements pass
- [ ] A non-ERP organisation can deploy MagBI in < 1 day
- [ ] Documentation covers installation, configuration, and first dashboard
- [ ] The designer is usable by an analyst with no prior MagBI training
  (validated by a usability test with 3 external participants)

---

## 15. Phased Delivery Plan

### Phase 1: Core Engine (Internal Launch)

**Goal:** Replace Power BI for 8 ERP modules
**Duration:** 12-16 weeks
**Scope:** FR-001, FR-005-007, FR-011-013, FR-020-021, FR-023, FR-030-032,
FR-040-044, FR-046-047, FR-051, FR-060, FR-064, FR-070-073, FR-075,
FR-080-083, FR-086, FR-090, FR-092-093

**Milestone 1 (Week 4): Query engine works**
- Connect to SQL Server
- Import tables into DuckDB
- Define relationships and measures
- Execute a semantic query and return results
- *Validation:* run the 55 existing dashboards' queries against MagBI's engine

**Milestone 2 (Week 8): Designer produces reports**
- Canvas with drag-and-drop visuals
- Field wells and auto-aggregation
- Cross-filtering
- Filter pane
- *Validation:* rebuild 3 dashboards (Finance, HR, Transport) in MagBI

**Milestone 3 (Week 12): Embedded in ERP**
- JWT auth from ERP
- RLS from ERP permissions
- Theme injection
- Dashboard registry integration
- *Validation:* department heads use MagBI dashboards in the ERP for 1 week

**Milestone 4 (Week 16): Migration complete**
- All 55 dashboards migrated
- Power BI capacity decommissioned
- *Validation:* Phase 1 acceptance criteria met

### Phase 2: Product Polish (External Readiness)

**Goal:** MagBI is usable by organisations outside MSD
**Duration:** 8-12 weeks after Phase 1
**Scope:** All P2 requirements + documentation + standalone deployment

### Phase 3: Scale and Extend

**Goal:** Advanced features for large deployments
**Duration:** Ongoing
**Scope:** P3 and P4 requirements, natural language query, alerting,
REST API connectors, multi-tenant SaaS

---

## 16. Glossary

| Term | Definition |
|------|-----------|
| **BI** | Business Intelligence — the practice of using data to make better decisions |
| **Canvas** | The design surface where report visuals are placed (1760 × 990 pixels) |
| **Cross-filtering** | Clicking a data point in one visual filters all other visuals on the page |
| **DAX** | Data Analysis Expressions — Microsoft's formula language for Power BI |
| **DAX-lite** | MagBI's formula language, using DAX syntax but compiling to SQL |
| **Dataset** | A semantic model: tables, relationships, measures, and RLS definitions |
| **DuckDB** | An in-process columnar database used for analytical data storage |
| **Embed token** | A short-lived JWT scoped to one report + one user's RLS permissions |
| **ERP** | Enterprise Resource Planning — the MSD ERP system that is MagBI's first host |
| **JWT** | JSON Web Token — a signed token that carries user identity and claims |
| **Measure** | A DAX-lite formula that computes an aggregate value (e.g., `SUM(Sales[Amount])`) |
| **Query folding** | Compiling transform steps into SQL that runs on the source database |
| **RLS** | Row-Level Security — filters that restrict which rows a user can see |
| **Semantic model** | An abstraction layer that defines what the data means and how it relates |
| **Semantic query** | A JSON object describing what data to fetch (tables, columns, measures, filters) |
| **Service token** | A long-lived API token for server-to-server authentication |
| **sqlglot** | A Python library for parsing, building, and transpiling SQL across dialects |
| **Well** | A typed field bucket in the designer (e.g., Axis, Values, Legend) |
| **Workspace** | A container for datasets and reports, with role-based access control |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-10-29 | Magila Technology | Initial SRS |
