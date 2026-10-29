# Dataset and model specification

The JSON schema for datasets — the semantic layer between raw database tables
and the visuals that consume them. A dataset defines what tables exist, what
their columns look like, how tables relate to each other, what measures and
calculated columns the user has written, and who can see which rows. Every
other component (the query engine, the report designer, the formula editor,
the model editor UI) reads or writes this schema.

| | |
|---|---|
| Written | 29 October 2026 |
| Status | Draft — not implemented |
| Depends on | [POWERBI-V2-ARCHITECTURE.md](POWERBI-V2-ARCHITECTURE.md) §8, [DAX-LITE-SPEC.md](DAX-LITE-SPEC.md), [QUERY-ENGINE-SPEC.md](QUERY-ENGINE-SPEC.md) §4–7 |
| Analogues | Power BI Model.bim / TMDL, Cube.js cube definitions, dbt semantic layer |

---

## Contents

1. [Design principles](#1-design-principles)
2. [Dataset definition (top level)](#2-dataset-definition-top-level)
3. [Tables](#3-tables)
4. [Columns](#4-columns)
5. [Measures](#5-measures)
6. [Calculated columns](#6-calculated-columns)
7. [Relationships](#7-relationships)
8. [Hierarchies](#8-hierarchies)
9. [Date tables](#9-date-tables)
10. [Row-level security (RLS)](#10-row-level-security-rls)
11. [Storage and refresh](#11-storage-and-refresh)
12. [Model validation rules](#12-model-validation-rules)
13. [The model editor UI](#13-the-model-editor-ui)
14. [Versioning and migration](#14-versioning-and-migration)
15. [Worked example: Transport module](#15-worked-example-transport-module)

---

## 1. Design principles

1. **One JSON file = one dataset.** The entire model is a single JSON document.
   Unlike Power BI's TMDL (which splits into one file per table), we keep one
   file because: (a) the models are small (tens of tables, not thousands),
   (b) a single file is atomic to read and write, (c) the API returns the
   whole model in one GET and accepts the whole model in one PUT.

2. **The schema IS the documentation.** Every table, column and measure has a
   `description` field. The model editor shows these as tooltips. The data pane
   in the report designer shows them on hover. They are the data dictionary.

3. **Derived state is never stored.** The dataset definition stores metadata
   only — table schemas, measures, relationships. It does not store data, query
   results or compiled SQL. The data lives in the DuckDB file; the compiled SQL
   is regenerated on every query.

4. **Forward-compatible.** Unknown properties are preserved (round-tripped)
   when the model is read and written. This lets newer versions of the schema
   add fields without breaking older readers.

---

## 2. Dataset definition (top level)

```typescript
interface DatasetDefinition {
  // Identity
  id: string;                       // UUID
  name: string;                     // "Transport"
  description?: string;             // "Fleet management and trip data"
  workspaceId: string;              // the workspace this dataset belongs to

  // Schema version (for forward compatibility)
  schemaVersion: "1.0";

  // Connection (where the source data comes from)
  connection: ConnectionConfig;

  // The model
  tables: TableDefinition[];
  relationships: RelationshipDefinition[];
  roles: RlsRoleDefinition[];

  // Refresh configuration
  refresh: RefreshConfig;

  // Metadata
  createdAt: string;                // ISO 8601
  updatedAt: string;
  createdBy: string;                // user ID
  version: number;                  // optimistic concurrency counter
}
```

---

## 3. Tables

```typescript
interface TableDefinition {
  name: string;                     // "Trip" — unique within the dataset
  description?: string;             // "Vehicle trips and journeys"
  schema?: string;                  // source schema (e.g., "dbo", "vetsp")

  // Source mapping
  source: TableSource;

  // Columns, measures, calculated columns
  columns: ColumnDefinition[];
  measures: MeasureDefinition[];
  calculatedColumns: CalculatedColumnDefinition[];

  // Hierarchies
  hierarchies: HierarchyDefinition[];

  // Date table marker
  isDateTable?: boolean;
  dateColumn?: string;              // the column name if isDateTable is true

  // Display
  displayFolder?: string;           // groups tables in the data pane ("Dimensions", "Facts")
  isHidden?: boolean;               // hidden from the data pane (but still queryable)
}
```

### 3.1 Table source

The source tells the import pipeline where to get the data:

```typescript
type TableSource =
  | SqlTableSource
  | SqlQuerySource
  | CsvSource;

interface SqlTableSource {
  type: "table";
  database?: string;                // "MSD_ERP" (defaults to connection default)
  schema: string;                   // "vetsp"
  table: string;                    // "Trip"
}

interface SqlQuerySource {
  type: "query";
  sql: string;                      // "SELECT * FROM vetsp.Trip WHERE IsDeleted = 0"
  description?: string;             // explains what the query does
}

interface CsvSource {
  type: "csv";
  filePath: string;                 // relative to the dataset's storage
  delimiter?: string;               // default ","
  hasHeader?: boolean;              // default true
}
```

### 3.2 Table categories

Tables are implicitly categorised by their role in the model:

| Category | How identified | Examples |
|---|---|---|
| **Fact table** | Has relationships where it is the "many" side | Trip, ServiceRequest, Order |
| **Dimension table** | Has relationships where it is the "one" side | Directorate, Vehicle, Date |
| **Bridge table** | Is on the "many" side of two relationships | TripDriver (many trips, many drivers) |
| **Standalone** | No relationships | Config, LookupValues |

The model editor uses these categories for layout (facts in the centre,
dimensions around them) and validation (warns if a fact table has no
relationships).

---

## 4. Columns

```typescript
interface ColumnDefinition {
  name: string;                     // "DistanceKm" — unique within the table
  description?: string;             // "Distance in kilometres"
  dataType: DataType;               // the column's data type
  sourceColumn?: string;            // source DB column name (if different from name)

  // Constraints
  isNullable: boolean;              // default true
  isPrimaryKey?: boolean;           // one per table
  isForeignKey?: boolean;           // inferred from relationships, but can be explicit

  // Display
  displayName?: string;             // "Distance (km)" — shown in data pane
  format?: string;                  // "#,##0", "0.0%", "yyyy-MM-dd"
  isHidden?: boolean;               // hidden from data pane
  sortByColumn?: string;            // sort this column by another column's values

  // Summarisation default
  defaultAggregation?: AggregationType;  // what happens when dropped into a measure well
}

type DataType =
  | "string"
  | "integer"
  | "decimal"
  | "boolean"
  | "date"
  | "datetime"
  | "time"
  | "binary";     // for future use (images, etc.)

type AggregationType =
  | "sum"
  | "average"
  | "count"
  | "distinctCount"
  | "min"
  | "max"
  | "none";       // don't aggregate (for text/date columns)
```

### 4.1 Type mapping from source databases

| SQL Server | PostgreSQL | MySQL | DuckDB | v2 DataType |
|---|---|---|---|---|
| `int`, `bigint`, `smallint`, `tinyint` | `integer`, `bigint`, `smallint` | `INT`, `BIGINT` | `INTEGER`, `BIGINT` | `integer` |
| `decimal`, `numeric`, `float`, `real`, `money` | `numeric`, `real`, `double precision` | `DECIMAL`, `FLOAT`, `DOUBLE` | `DOUBLE`, `DECIMAL` | `decimal` |
| `varchar`, `nvarchar`, `char`, `text` | `varchar`, `text`, `char` | `VARCHAR`, `TEXT` | `VARCHAR` | `string` |
| `bit` | `boolean` | `TINYINT(1)`, `BOOLEAN` | `BOOLEAN` | `boolean` |
| `date` | `date` | `DATE` | `DATE` | `date` |
| `datetime`, `datetime2`, `smalldatetime` | `timestamp` | `DATETIME`, `TIMESTAMP` | `TIMESTAMP` | `datetime` |
| `time` | `time` | `TIME` | `TIME` | `time` |
| `uniqueidentifier` | `uuid` | — | `UUID` (stored as `VARCHAR`) | `string` |

### 4.2 Sort-by-column

The `sortByColumn` property tells visuals to sort this column's values by
another column's values. The classic example: sort `MonthName` ("January",
"February", …) by `MonthNumber` (1, 2, …):

```json
{
  "name": "MonthName",
  "dataType": "string",
  "sortByColumn": "MonthNumber"
}
```

The query engine adds `ORDER BY MonthNumber` whenever `MonthName` appears in
a groupBy.

---

## 5. Measures

Measures are named DAX-lite expressions defined on a table:

```typescript
interface MeasureDefinition {
  name: string;                     // "Trips" — unique across all tables
  description?: string;             // "Count of all trip records"
  expression: string;               // "COUNTROWS(Trip)"
  table: string;                    // the home table (where this measure "lives")

  // Display
  displayName?: string;             // "Total Trips"
  displayFolder?: string;           // "Performance" — groups measures in the data pane
  format?: string;                  // "#,##0"
  isHidden?: boolean;

  // Metadata
  returnType?: DataType;            // inferred from expression if not set
}
```

### 5.1 Measure naming rules

- Names must be unique across **all tables** in the dataset. This matches DAX
  behaviour: `[Trips]` is unambiguous because no two measures share a name.
- Names can contain spaces and special characters (except `[` and `]`).
- Names are case-insensitive for lookup but case-preserving for display.

### 5.2 Home table

A measure's `table` property determines:
- Where it appears in the data pane (under that table's node).
- Its **home table** for the query engine (§query-engine-spec §6): the fact
  table whose rows the measure aggregates.
- For simple measures like `COUNTROWS(Trip)` or `SUM(Trip[DistanceKm])`, the
  home table is obvious. For complex measures that reference multiple tables,
  the home table is the table listed in the outermost aggregation function.

### 5.3 Implicit measures

When a user drags a numeric column into a measure well without an existing
measure, the designer creates an **implicit measure**:

```json
{
  "name": "Sum of DistanceKm",
  "expression": "SUM(Trip[DistanceKm])",
  "table": "Trip",
  "format": "#,##0",
  "_implicit": true
}
```

Implicit measures have `_implicit: true`. They are visible in the report
designer but not in the model editor's measure list. The user can "promote"
an implicit measure to an explicit one (which removes the `_implicit` flag and
makes it editable).

---

## 6. Calculated columns

Calculated columns are row-level expressions evaluated once at refresh time
and stored in the DuckDB file:

```typescript
interface CalculatedColumnDefinition {
  name: string;                     // "FullName"
  description?: string;
  expression: string;               // "Employee[FirstName] & \" \" & Employee[LastName]"
  dataType: DataType;               // inferred or explicit

  // Display (same options as regular columns)
  displayName?: string;
  format?: string;
  isHidden?: boolean;
  sortByColumn?: string;
  defaultAggregation?: AggregationType;
}
```

### 6.1 When calculated columns are computed

Calculated columns are computed during the **import/refresh** step, not at
query time. The pipeline:

1. Import all physical columns from the source.
2. For each calculated column, evaluate its expression row by row.
3. Store the result as a regular column in the DuckDB file.

This means calculated columns can use `RELATED()` to look up values from
dimension tables (the joins are resolved during import), but they cannot use
aggregation functions (`SUM`, `COUNT`, etc.) — those belong in measures.

### 6.2 Dependency order

Calculated columns can reference other calculated columns. The import pipeline
resolves them in dependency order (topological sort). Circular references are
caught at model save time.

---

## 7. Relationships

```typescript
interface RelationshipDefinition {
  id: string;                       // UUID
  name?: string;                    // optional display name

  // From side (the "many" side / FK side)
  from: {
    table: string;                  // "Trip"
    column: string;                 // "DepartmentGuid"
  };

  // To side (the "one" side / PK side)
  to: {
    table: string;                  // "Directorate"
    column: string;                 // "DepartmentGuid"
  };

  // Cardinality
  cardinality: "many-to-one" | "one-to-one" | "many-to-many";

  // Cross-filter direction
  crossFilterDirection: "single" | "both";

  // Active/inactive
  isActive: boolean;                // only one active relationship per (from.table → to.table) pair

  // Join type
  joinType: "inner" | "left";      // left = include fact rows with NULL FK
}
```

### 7.1 Cardinality rules

| Cardinality | From side | To side | Example |
|---|---|---|---|
| **Many-to-one** | Many rows in the fact table | One row in the dimension | Trip.DeptGuid → Directorate.DeptGuid |
| **One-to-one** | One row | One row | Employee.EmployeeId → EmployeeDetail.EmployeeId |
| **Many-to-many** | Many rows | Many rows | Trip ↔ Driver (via TripDriver bridge) |

**Many-to-many** is deferred to phase 3. In the MVP, many-to-many
relationships are modelled with an explicit bridge table and two many-to-one
relationships.

### 7.2 Cross-filter direction

| Direction | Behaviour | Use case |
|---|---|---|
| **Single** (default) | Filters flow from the "one" side to the "many" side only | Standard dimension → fact filtering |
| **Both** | Filters flow in both directions | Bridge tables, bidirectional slicers |

**Both** is deferred to phase 3 (same as many-to-many). In the MVP, all
relationships use single-direction cross-filtering.

### 7.3 Active vs inactive

Only **one active relationship** is allowed per pair of tables. If a fact table
has two foreign keys to the same dimension (e.g., `Trip.StartDate` and
`Trip.EndDate` both pointing to `Date`), one is active and the other inactive.

The active relationship is used by default. The inactive one can be activated
in a specific measure using `USERELATIONSHIP` (phase 3). Until then, the user
must choose which date relationship is active and accept that the other date
column won't automatically filter through the Date table.

### 7.4 Relationship detection

When a user adds tables to the model, the engine can **auto-detect**
relationships by matching column names and types:

1. For each pair of tables, find columns with matching names.
2. If one table's matching column is a primary key and the other's is not,
   propose a many-to-one relationship.
3. If both are primary keys, propose one-to-one.
4. Present the proposals to the user for confirmation.

This is a convenience — all relationships can also be created manually in the
model editor.

---

## 8. Hierarchies

Hierarchies define drill-down paths for visuals:

```typescript
interface HierarchyDefinition {
  name: string;                     // "DateHierarchy"
  description?: string;
  levels: HierarchyLevel[];
}

interface HierarchyLevel {
  name: string;                     // "Year", "Quarter", "Month", "Day"
  column: string;                   // the column name in the same table
  sortByColumn?: string;            // optional sort column for this level
}
```

### 8.1 Example: Date hierarchy

```json
{
  "name": "DateHierarchy",
  "levels": [
    { "name": "Year", "column": "Year" },
    { "name": "Quarter", "column": "Quarter" },
    { "name": "Month", "column": "MonthName", "sortByColumn": "MonthNumber" },
    { "name": "Day", "column": "Day" }
  ]
}
```

### 8.2 Using hierarchies in visuals

When a user drags a hierarchy into a well, all levels are added. The visual
shows the top level by default, with drill-down buttons (+/−) to expand to
lower levels. Each drill-down level adds the next column to the groupBy.

---

## 9. Date tables

A date table is a dimension table with one row per calendar day, no gaps. It
is required for time intelligence functions (DAX-lite spec §8).

### 9.1 Marking a date table

Set `isDateTable: true` and `dateColumn: "Date"` on the table definition. The
model editor validates:

1. The table has a column of type `date` or `datetime`.
2. Every day in the range `[min(date), max(date)]` is present (no gaps).
3. Each date value is unique (no duplicates).
4. The table is related to at least one fact table.

### 9.2 Auto-generated date table

When the user enables "Auto date table" on a dataset, the engine generates a
date table covering the range of all date columns in all fact tables, plus one
year of padding on each side. The generated table includes:

| Column | Type | Example |
|---|---|---|
| Date | date | 2026-01-15 |
| Year | integer | 2026 |
| Quarter | string | Q1 |
| QuarterNumber | integer | 1 |
| Month | string | January |
| MonthNumber | integer | 1 |
| MonthShort | string | Jan |
| YearMonth | string | 2026-01 |
| Day | integer | 15 |
| DayOfWeek | string | Wednesday |
| DayOfWeekNumber | integer | 3 (Monday = 0) |
| WeekNumber | integer | 3 |
| IsWeekend | boolean | false |
| FiscalYear | integer | 2026 (configurable start month) |
| FiscalQuarter | string | FQ3 |

The auto-generated date table has a standard hierarchy: Year > Quarter > Month > Day.

### 9.3 Fiscal year configuration

```typescript
interface DateTableConfig {
  autoGenerate: boolean;
  fiscalYearStartMonth?: number;    // 1–12 (default 1 = January = calendar year)
  firstDayOfWeek?: number;          // 0 = Monday, 6 = Sunday (default 0)
}
```

---

## 10. Row-level security (RLS)

RLS restricts which rows a user can see based on their identity.

### 10.1 Role definition

```typescript
interface RlsRoleDefinition {
  name: string;                     // "DepartmentAccess"
  description?: string;             // "Users see only their department's data"
  tableFilters: RlsTableFilter[];
}

interface RlsTableFilter {
  table: string;                    // "Directorate"
  expression: string;               // DAX-lite boolean: Directorate[DepartmentGuid] IN @userDepartments
}
```

### 10.2 Dynamic predicates

RLS expressions can reference **dynamic parameters** prefixed with `@`:

| Parameter | Resolved to | Example |
|---|---|---|
| `@userId` | The current user's ID | `Employee[UserId] = @userId` |
| `@userEmail` | The current user's email | `Employee[Email] = @userEmail` |
| `@userDepartments` | List of department IDs the user belongs to | `Directorate[DeptGuid] IN @userDepartments` |
| `@userRoles` | List of role names the user has | `IF("Admin" IN @userRoles, TRUE(), ...)` |

These parameters are resolved at query time by the server, which reads them
from the user's identity claims. The query engine receives the resolved values
(never the raw parameter names).

### 10.3 Role assignment

Roles are assigned to users in the workspace settings:

```typescript
interface RlsRoleAssignment {
  roleId: string;                   // references RlsRoleDefinition.name
  userId: string;                   // the user assigned to this role
}
```

A user with **no role assignments** sees all data (no RLS applied). A user
assigned to one or more roles sees the union of what each role allows.

### 10.4 Testing RLS

The model editor includes a "View as role" mode: the user selects a role and
optionally a test user, and the data pane and preview queries apply that role's
RLS filters. This matches Power BI's "View as" feature.

---

## 11. Storage and refresh

### 11.1 Import mode (default)

Data is extracted from the source database and stored in a DuckDB file:

```
datasets/
  {dataset-id}/
    live.duckdb          ← the live file (read-only for queries)
    staging.duckdb       ← being built during refresh (write)
    model.json              ← the DatasetDefinition
    history/
      v3_2026-10-29T10.duckdb  ← previous version (kept for rollback)
```

### 11.2 Refresh pipeline

```
1. Read model.json → list of tables and their sources
2. For each table (in dependency order):
   a. Connect to the source database
   b. Execute the source query (or SELECT * FROM source table)
   c. Write rows into staging.duckdb
   d. Compute calculated columns (topological order)
3. Build indexes (if configured)
4. Validate: row counts, null checks, referential integrity spot-checks
5. Atomic swap: rename live.duckdb → history/vN.duckdb,
                rename staging.duckdb → live.duckdb
6. Increment dataset version → invalidates query cache
7. Notify connected clients (WebSocket) to re-query
```

### 11.3 Incremental refresh (phase 3)

For large tables, the refresh pipeline supports incremental refresh:

```typescript
interface IncrementalRefreshConfig {
  table: string;
  dateColumn: string;               // the column that determines "newness"
  lookbackPeriod: string;           // "30 days", "7 days" — re-import this window
  archivePeriod: string;            // "2 years" — keep this much history
}
```

The pipeline:
1. DELETE rows from the DuckDB table where `dateColumn > (now - lookbackPeriod)`.
2. INSERT new rows from the source for the same date range.
3. DELETE rows older than `archivePeriod`.

This avoids re-importing the entire table on each refresh.

### 11.4 Refresh scheduling

```typescript
interface RefreshConfig {
  mode: "import" | "directQuery";
  schedule?: {
    frequency: "hourly" | "daily" | "weekly" | "monthly" | "manual";
    time?: string;                  // "06:00" (UTC)
    dayOfWeek?: number;             // 0–6 for weekly
    dayOfMonth?: number;            // 1–28 for monthly
    timezone?: string;              // "Africa/Dar_es_Salaam"
  };
  timeout?: number;                 // max refresh duration in seconds (default 3600)
  retryCount?: number;              // retries on failure (default 1)
  notifyOnFailure?: string[];       // email addresses to notify
}
```

### 11.5 DirectQuery mode

In DirectQuery mode, there is no DuckDB file. The query engine generates SQL
in the source database's dialect and executes it directly (see query engine
spec §15). The `RefreshConfig` is:

```json
{
  "mode": "directQuery"
}
```

No scheduling, no DuckDB file, no import pipeline.

---

## 12. Model validation rules

The model editor and the API validate the dataset definition before saving.
Every rule produces either an **error** (blocks save) or a **warning** (allows
save but flags the issue).

### 12.1 Errors (block save)

| Rule | Message |
|---|---|
| Duplicate table name | `Table 'Trip' is defined twice.` |
| Duplicate column name in table | `Column 'Status' is defined twice in table 'Trip'.` |
| Duplicate measure name (cross-table) | `Measure 'Trips' is defined in both 'Trip' and 'Vehicle'.` |
| Measure expression parse error | `Measure 'Trips': Expected ')' at line 1, column 15.` |
| Measure expression type error | `Measure 'Share': SUM requires a numeric column.` |
| Circular measure reference | `Circular reference: [A] → [B] → [A].` |
| Circular calculated column reference | `Circular reference: Trip[Full] → Trip[Half] → Trip[Full].` |
| Aggregation in calculated column | `Calculated column 'Total' cannot use SUM. Use a measure.` |
| Missing aggregation in measure | `Measure 'Bad': expression must contain an aggregation.` |
| Relationship references missing table | `Relationship references table 'Tripp', which does not exist.` |
| Relationship references missing column | `Relationship references column 'Trip.DeptId', which does not exist.` |
| Multiple active relationships between same tables | `Trip and Date have 2 active relationships. Deactivate one.` |
| Date table has gaps | `Date table 'Date' has 3 missing dates between 2025-01-01 and 2026-12-31.` |
| Date table has duplicates | `Date table 'Date' has duplicate dates.` |
| RLS expression parse error | `RLS role 'DeptAccess': parse error in filter for table 'Directorate'.` |
| RLS expression references unknown table | `RLS role 'DeptAccess' filters table 'Dept', which does not exist.` |

### 12.2 Warnings (allow save)

| Rule | Message |
|---|---|
| Table with no relationships | `Table 'Config' has no relationships. It won't be filterable by other tables.` |
| Fact table with no measures | `Table 'Trip' has no measures. Consider adding at least one.` |
| Column with high cardinality as category | `Column 'Trip.TripId' has very high cardinality (>10,000 distinct values). Using it as an axis may be slow.` |
| Hidden table with visible measures | `Table 'Trip' is hidden but has visible measures. Users can still see the measures.` |
| Unused relationship | `Relationship 'Trip.OldDeptId → Dept.DeptId' is inactive and not used by any USERELATIONSHIP call.` |
| Nullable FK in an inner join | `Trip.DepartmentGuid is nullable, but the relationship uses INNER join. Rows with NULL will be excluded.` |

### 12.3 Validation timing

- **On every keystroke** in the measure editor: parse and type-check the
  expression, show errors inline (red squiggles).
- **On save**: full validation of the entire model. Errors block the save;
  warnings are shown in a panel.
- **On refresh**: the import pipeline checks that source tables and columns
  still exist (schema drift detection).

---

## 13. The model editor UI

The model editor is a browser-based tool for building and editing dataset
models. It has two views: the **diagram view** and the **table list view**.

### 13.1 Diagram view (relationship diagram)

A visual representation of the model, similar to Power BI's model view:

```
┌──────────────┐          ┌──────────────┐
│  Directorate │          │    Date      │
│──────────────│          │──────────────│
│ DeptGuid (PK)│◄────────┐│ Date (PK)   │
│ Name         │         ││ Year        │
│ Region       │         ││ Quarter     │
│ Country      │         ││ Month       │
└──────────────┘         │└──────────────┘
       ▲                 │       ▲
       │ many-to-one     │       │ many-to-one
       │                 │       │
┌──────────────┐         │┌──────────────┐
│    Trip      │─────────┘│   Vehicle    │
│──────────────│          │──────────────│
│ TripId (PK)  │          │ VehicleGuid  │
│ DeptGuid (FK)│          │ Type         │
│ StartDate(FK)│          │ Make         │
│ VehicleGuid  │─────────►│ Model        │
│ DistanceKm   │          │ Weight       │
│ Status       │          └──────────────┘
│──────────────│
│ Σ Trips      │
│ Σ Completion%│
│ Σ Trips LY   │
└──────────────┘
```

**Implementation:**

- **Layout engine:** Force-directed graph layout (using d3-force or a similar
  algorithm) with manual override. The user can drag tables to any position,
  and the positions are saved in the dataset metadata. On first open, the auto
  layout places fact tables in the centre and dimensions around them.

- **Relationship lines:** SVG lines drawn between the FK and PK columns.
  The line has a "1" label on the PK end and a "*" on the FK end. Clicking a
  line opens the relationship editor.

- **Table cards:** Each table is a card showing the table name, its columns
  (with type icons), and its measures (with Σ icons). Cards are collapsible.
  Double-clicking a table opens the table detail view.

### 13.2 Table list view

A flat list of all tables with expand/collapse for columns, measures and
calculated columns. Better for detailed editing (renaming, hiding, setting
formats) than the diagram.

### 13.3 Creating a relationship (in the diagram)

1. The user drags from a column in one table card to a column in another.
2. The model editor proposes the cardinality (many-to-one if one column is a
   PK) and cross-filter direction (single).
3. A dialog confirms the settings. The user can change the join type, make it
   inactive, etc.
4. On confirm, the relationship is added and the diagram re-renders with a
   new line.

### 13.4 Measure editor

Clicking "New measure" or double-clicking an existing measure opens the
**formula bar** — a Monaco editor instance with the DAX-lite language mode:

```
┌─────────────────────────────────────────────────────────┐
│ Trips LY =                                              │
│ CALCULATE(                                              │
│     [Trips],                                            │
│     SAMEPERIODLASTYEAR('Date'[Date])                    │
│ )                                                       │
│                                               ✓ Save  ✕ │
├─────────────────────────────────────────────────────────┤
│ Compiles to:                                            │
│ SELECT COUNT(*) FROM Trip t JOIN Date dt ...              │
│ WHERE dt.Year = $1 - 1                                   │
└─────────────────────────────────────────────────────────┘
```

Features:
- **Autocomplete:** Table names, column names (with `Table[Column]` syntax),
  measure names, function names.
- **Signature help:** Parameter names and types for each function.
- **Error squiggles:** Real-time parse and type errors.
- **"Compiles to" panel:** Shows the generated SQL for the current measure.
- **Inline documentation:** Hover over a function name to see its description
  and syntax.

### 13.5 Calculated column editor

Same as the measure editor, but with different validation:
- Must not contain aggregation functions.
- Must return a scalar value (not a table).
- Can use `RELATED()` for lookups.

### 13.6 Table properties panel

Selecting a table shows a properties panel:

| Property | Control |
|---|---|
| Name | Text input |
| Description | Text area |
| Is date table | Toggle + date column dropdown |
| Display folder | Text input |
| Is hidden | Toggle |

### 13.7 Column properties panel

Selecting a column shows:

| Property | Control |
|---|---|
| Name | Text input |
| Display name | Text input |
| Description | Text area |
| Data type | Dropdown (read-only for physical columns) |
| Format | Format string input with preview |
| Default aggregation | Dropdown |
| Sort by column | Dropdown (columns from the same table) |
| Is hidden | Toggle |

### 13.8 Schema drift detection

When the refresh pipeline runs, it compares the source database schema against
the model's expected schema. Detected changes:

| Change | Action |
|---|---|
| New column in source table | Warning: "Column 'NewCol' found in source 'Trip'. Add it to the model?" |
| Column removed from source | Error: "Column 'OldCol' no longer exists in source 'Trip'." |
| Column type changed | Warning: "Column 'Trip.Amount' changed from INT to DECIMAL in source." |
| Table removed from source | Error: "Source table 'vetsp.Trip' no longer exists." |
| New table in source schema | Info (only if user is browsing the source explorer) |

The model editor shows these as a notification badge. The user reviews and
either updates the model or ignores the change.

---

## 14. Versioning and migration

### 14.1 Schema version

The `schemaVersion` field tracks the format of the DatasetDefinition JSON.
The current version is `"1.0"`. When we add new fields or change semantics,
we increment the version.

### 14.2 Migration rules

| From | To | Migration |
|---|---|---|
| (any) | (same) | No migration needed — unknown fields are round-tripped |
| 1.0 | 1.1 (example) | Add default values for new fields; no destructive changes |

The API always serves the latest schema version. Older clients that don't
understand new fields ignore them (they are preserved in the JSON, not
stripped).

### 14.3 Model change history

Every save creates a new version of `model.json`. The history is stored:

```
datasets/{dataset-id}/model-history/
  v1.json
  v2.json
  v3.json  ← current
```

The API supports:
- `GET /datasets/{id}/model` → current version
- `GET /datasets/{id}/model/history` → list of versions with timestamps
- `GET /datasets/{id}/model/history/{version}` → a specific version
- `POST /datasets/{id}/model/revert/{version}` → revert to a previous version

---

## 15. Worked example: Transport module

The MSD ERP Transport module's dataset definition (simplified):

```json
{
  "id": "ds-transport",
  "name": "Transport",
  "description": "Fleet management, trips, fuel consumption, and vehicle tracking",
  "workspaceId": "ws-msd",
  "schemaVersion": "1.0",

  "connection": {
    "type": "sqlServer",
    "host": "msd-db-01",
    "database": "MSD_ERP",
    "authentication": "serviceAccount"
  },

  "tables": [
    {
      "name": "Trip",
      "description": "Vehicle trips and journeys",
      "source": { "type": "table", "schema": "vetsp", "table": "Trip" },
      "columns": [
        { "name": "TripId", "dataType": "string", "isPrimaryKey": true, "isHidden": true },
        { "name": "TripNumber", "dataType": "string", "displayName": "Trip #" },
        { "name": "StartDate", "dataType": "date", "format": "yyyy-MM-dd" },
        { "name": "EndDate", "dataType": "date", "format": "yyyy-MM-dd" },
        { "name": "DepartmentGuid", "dataType": "string", "isHidden": true, "isForeignKey": true },
        { "name": "VehicleGuid", "dataType": "string", "isHidden": true, "isForeignKey": true },
        { "name": "DistanceKm", "dataType": "decimal", "format": "#,##0.0", "defaultAggregation": "sum" },
        { "name": "FuelLitres", "dataType": "decimal", "format": "#,##0.0", "defaultAggregation": "sum" },
        { "name": "Status", "dataType": "string" },
        { "name": "TripType", "dataType": "string" }
      ],
      "measures": [
        {
          "name": "Trips",
          "expression": "COUNTROWS(Trip)",
          "table": "Trip",
          "format": "#,##0",
          "description": "Total number of trips"
        },
        {
          "name": "Completion %",
          "expression": "DIVIDE(CALCULATE(COUNTROWS(Trip), Trip[Status] = \"Completed\"), COUNTROWS(Trip))",
          "table": "Trip",
          "format": "0.0%",
          "description": "Percentage of trips with Completed status"
        },
        {
          "name": "Trips LY",
          "expression": "CALCULATE([Trips], SAMEPERIODLASTYEAR('Date'[Date]))",
          "table": "Trip",
          "format": "#,##0",
          "description": "Trips in the same period last year"
        },
        {
          "name": "Km per Litre",
          "expression": "DIVIDE(SUM(Trip[DistanceKm]), SUM(Trip[FuelLitres]))",
          "table": "Trip",
          "format": "#,##0.0",
          "description": "Fuel efficiency"
        },
        {
          "name": "Total Distance",
          "expression": "SUM(Trip[DistanceKm])",
          "table": "Trip",
          "format": "#,##0",
          "description": "Total distance in kilometres"
        }
      ],
      "calculatedColumns": [],
      "hierarchies": []
    },
    {
      "name": "Directorate",
      "description": "Organisational directorates (departments)",
      "source": { "type": "table", "schema": "vehr", "table": "Department" },
      "columns": [
        { "name": "DepartmentGuid", "dataType": "string", "isPrimaryKey": true, "isHidden": true },
        { "name": "Name", "dataType": "string", "displayName": "Directorate" },
        { "name": "Region", "dataType": "string" },
        { "name": "Country", "dataType": "string" }
      ],
      "measures": [],
      "calculatedColumns": [],
      "hierarchies": [
        {
          "name": "OrgHierarchy",
          "levels": [
            { "name": "Country", "column": "Country" },
            { "name": "Region", "column": "Region" },
            { "name": "Directorate", "column": "Name" }
          ]
        }
      ]
    },
    {
      "name": "Vehicle",
      "description": "Fleet vehicles",
      "source": { "type": "table", "schema": "vetsp", "table": "Vehicle" },
      "columns": [
        { "name": "VehicleGuid", "dataType": "string", "isPrimaryKey": true, "isHidden": true },
        { "name": "PlateNumber", "dataType": "string", "displayName": "Plate #" },
        { "name": "Type", "dataType": "string", "displayName": "Vehicle Type" },
        { "name": "Make", "dataType": "string" },
        { "name": "Model", "dataType": "string" },
        { "name": "Year", "dataType": "integer", "displayName": "Model Year" },
        { "name": "Weight", "dataType": "decimal", "format": "#,##0", "isHidden": true }
      ],
      "measures": [],
      "calculatedColumns": [],
      "hierarchies": []
    },
    {
      "name": "Date",
      "description": "Calendar date dimension (auto-generated)",
      "isDateTable": true,
      "dateColumn": "Date",
      "source": { "type": "query", "sql": "SELECT * FROM bi.DateDimension" },
      "columns": [
        { "name": "Date", "dataType": "date", "isPrimaryKey": true },
        { "name": "Year", "dataType": "integer" },
        { "name": "Quarter", "dataType": "string" },
        { "name": "QuarterNumber", "dataType": "integer", "isHidden": true },
        { "name": "Month", "dataType": "string", "sortByColumn": "MonthNumber" },
        { "name": "MonthNumber", "dataType": "integer", "isHidden": true },
        { "name": "MonthShort", "dataType": "string", "sortByColumn": "MonthNumber" },
        { "name": "YearMonth", "dataType": "string" },
        { "name": "Day", "dataType": "integer" },
        { "name": "DayOfWeek", "dataType": "string", "sortByColumn": "DayOfWeekNumber" },
        { "name": "DayOfWeekNumber", "dataType": "integer", "isHidden": true },
        { "name": "IsWeekend", "dataType": "boolean" }
      ],
      "measures": [],
      "calculatedColumns": [],
      "hierarchies": [
        {
          "name": "DateHierarchy",
          "levels": [
            { "name": "Year", "column": "Year" },
            { "name": "Quarter", "column": "Quarter", "sortByColumn": "QuarterNumber" },
            { "name": "Month", "column": "Month", "sortByColumn": "MonthNumber" },
            { "name": "Day", "column": "Day" }
          ]
        }
      ]
    }
  ],

  "relationships": [
    {
      "id": "rel-trip-dept",
      "from": { "table": "Trip", "column": "DepartmentGuid" },
      "to": { "table": "Directorate", "column": "DepartmentGuid" },
      "cardinality": "many-to-one",
      "crossFilterDirection": "single",
      "isActive": true,
      "joinType": "inner"
    },
    {
      "id": "rel-trip-vehicle",
      "from": { "table": "Trip", "column": "VehicleGuid" },
      "to": { "table": "Vehicle", "column": "VehicleGuid" },
      "cardinality": "many-to-one",
      "crossFilterDirection": "single",
      "isActive": true,
      "joinType": "left"
    },
    {
      "id": "rel-trip-date",
      "from": { "table": "Trip", "column": "StartDate" },
      "to": { "table": "Date", "column": "Date" },
      "cardinality": "many-to-one",
      "crossFilterDirection": "single",
      "isActive": true,
      "joinType": "inner"
    }
  ],

  "roles": [
    {
      "name": "DepartmentAccess",
      "description": "Users see only their department's data",
      "tableFilters": [
        {
          "table": "Directorate",
          "expression": "Directorate[DepartmentGuid] IN @userDepartments"
        }
      ]
    }
  ],

  "refresh": {
    "mode": "import",
    "schedule": {
      "frequency": "daily",
      "time": "06:00",
      "timezone": "Africa/Dar_es_Salaam"
    },
    "timeout": 1800,
    "retryCount": 2,
    "notifyOnFailure": ["admin@msd.go.tz"]
  },

  "createdAt": "2026-10-01T10:00:00Z",
  "updatedAt": "2026-10-29T14:00:00Z",
  "createdBy": "user-42",
  "version": 15
}
```

This Transport dataset defines 4 tables (1 fact, 3 dimensions), 3
relationships, 5 measures, 1 RLS role, and a daily 6:00 AM refresh. The query
engine, report designer and model editor all consume this JSON.

---

## Summary: what this spec pins down

| Question | Answer |
|---|---|
| What does a dataset look like? | §2 — a single JSON file with tables, columns, measures, relationships, RLS |
| How are columns typed? | §4 — 8 data types with mapping from every major database |
| How are measures defined? | §5 — DAX-lite expressions with a home table, format, display name |
| How do relationships work? | §7 — many-to-one (MVP), active/inactive, inner/left join |
| What about date tables? | §9 — marked with `isDateTable`, auto-generated if needed, fiscal year support |
| How does RLS work? | §10 — roles with table filter expressions using dynamic `@` parameters |
| How is data refreshed? | §11 — import pipeline with atomic swap, scheduling, incremental (phase 3) |
| What validation runs? | §12 — 16 errors that block save, 6 warnings |
| What does the model editor look like? | §13 — diagram view, table list, measure editor (Monaco), schema drift detection |
| How is the schema versioned? | §14 — `schemaVersion` field, unknown properties round-tripped, model history |

This spec completes the data layer. The query engine consumes this schema to
resolve names and relationships; the report designer reads it to populate the
data pane; the model editor writes it.
