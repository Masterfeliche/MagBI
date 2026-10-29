# Report designer specification

The browser-based drag-and-drop report authoring experience. This is the
surface users spend the most time on: they pick visuals, drop fields into
wells, set colours and labels, position things on a canvas, wire up
interactions, and preview the result — all without writing code or SQL.

| | |
|---|---|
| Written | 29 October 2026 |
| Status | Draft — not implemented |
| Depends on | [POWERBI-V2-ARCHITECTURE.md](POWERBI-V2-ARCHITECTURE.md) §11–12, [VISUALS-LIBRARY-ANALYSIS.md](VISUALS-LIBRARY-ANALYSIS.md), [QUERY-ENGINE-SPEC.md](QUERY-ENGINE-SPEC.md) §2 |
| Stack | React 18+, TypeScript, dnd-kit (drag-and-drop), ECharts (visuals), Monaco (formula editor) |

---

## Contents

1. [Design goals](#1-design-goals)
2. [The three panes](#2-the-three-panes)
3. [The canvas](#3-the-canvas)
4. [Visual lifecycle](#4-visual-lifecycle)
5. [Wells (field buckets)](#5-wells-field-buckets)
6. [The property pane](#6-the-property-pane)
7. [The data pane](#7-the-data-pane)
8. [Interactions and cross-filtering](#8-interactions-and-cross-filtering)
9. [Filters: report, page and visual level](#9-filters-report-page-and-visual-level)
10. [Undo / redo](#10-undo--redo)
11. [Report definition JSON schema](#11-report-definition-json-schema)
12. [Theming](#12-theming)
13. [Keyboard and accessibility](#13-keyboard-and-accessibility)
14. [Responsive layout (future)](#14-responsive-layout-future)
15. [State management](#15-state-management)
16. [File structure](#16-file-structure)

---

## 1. Design goals

1. **Familiar.** Anyone who has used Power BI Desktop should feel at home in
   five minutes. The designer borrows Power BI's layout: a canvas on the left,
   a visualisation picker and field wells on the right, a data pane below the
   wells.

2. **One page = one dashboard.** Following the MSD standard: no multi-page
   reports. Each report is one page, one canvas. If a dashboard needs tabs,
   the user creates separate reports that share the same model and the UI
   presents them as tabs.

3. **Everything is saved as JSON.** The report definition is a single JSON
   file. No binary blobs, no opaque state. The JSON is versioned, diffable
   and API-accessible.

4. **Live preview.** Every change — dragging a field into a well, changing a
   colour, resizing a visual — immediately re-queries and re-renders. There is
   no separate "preview mode" during authoring.

5. **No code required.** The designer never asks the user to write SQL, HTML,
   CSS or JavaScript. Measures are the only user-written text, and those use
   DAX-lite syntax in a guided editor.

---

## 2. The three panes

The designer window has three areas:

```
┌────────────────────────────────┬──────────────────┐
│                                │  Visual picker    │
│                                │  ──────────────   │
│                                │  Wells            │
│          Canvas                │  (field buckets)  │
│          (report page)         │  ──────────────   │
│                                │  Property pane    │
│                                │  (format options)  │
│                                │  ──────────────   │
│                                │  Data pane        │
│                                │  (tables/columns)  │
├────────────────────────────────┴──────────────────┤
│  Filter pane (report / page / visual filters)      │
└───────────────────────────────────────────────────┘
```

### 2.1 Resizing

The right panel is a fixed 320px wide (collapsible). The filter pane is a
bottom drawer (collapsible). The canvas takes the remaining space. When the
canvas is smaller than the report page, it scrolls and zooms.

---

## 3. The canvas

### 3.1 Page size

Default: **1760 × 990px** (the MSD standard — renders 1:1 in ERP at Full HD).
Configurable per report: the user picks from presets (16:9, 4:3, Letter, A4,
Custom) or enters exact pixel dimensions.

The canvas is a `<div>` with `position: relative`, sized to the page
dimensions. Zoom is applied via CSS `transform: scale(n)` on the canvas
container, so visuals are always positioned in page-pixel coordinates
regardless of zoom level.

### 3.2 Visual positioning

Every visual is absolutely positioned on the canvas:

```css
.visual-container {
  position: absolute;
  left: ${visual.x}px;
  top: ${visual.y}px;
  width: ${visual.width}px;
  height: ${visual.height}px;
}
```

This is **free-form layout**, not a grid. The user can place visuals at any
position and any size, exactly like Power BI Desktop. The canvas is the
coordinate system; the visuals are the items.

### 3.3 Snap-to-grid

A snap grid helps alignment:
- Default grid: 8px
- When dragging or resizing, the position snaps to the nearest grid point.
- **Smart guides** appear when edges or centres align with other visuals
  (horizontal and vertical guide lines, like Figma / PowerPoint).
- Hold **Alt** to disable snapping temporarily.

### 3.4 Drag and drop (dnd-kit)

We use [dnd-kit](https://dndkit.com/) for all drag-and-drop interactions:

| Interaction | dnd-kit feature | Notes |
|---|---|---|
| Move a visual on canvas | `useDraggable` on the visual, custom `DragOverlay` | Free transform (x, y), not grid swap |
| Resize a visual | `useDraggable` on 8 resize handles (corners + edges) | Compute new width/height from delta |
| Drop a field into a well | `useDraggable` on data pane items, `useDroppable` on wells | Type checking on drop: does this well accept this column type? |
| Drop a visual from picker to canvas | `useDraggable` on visual-type icons, `useDroppable` on canvas | Creates a new visual at the drop position |
| Reorder fields within a well | `useSortable` within well items | |

### 3.5 Selection

- **Click** a visual to select it (shows resize handles, activates wells and
  property pane for that visual).
- **Ctrl+Click** to add to selection (multi-select).
- **Drag on empty canvas** to rubber-band select.
- **Escape** to deselect.
- Selected visuals show a blue border and 8 resize handles.

### 3.6 Z-order

Visuals have a `z` property (integer). Higher z = on top. The context menu
and keyboard shortcuts adjust z-order:
- **Bring to front** (Ctrl+Shift+])
- **Send to back** (Ctrl+Shift+[)
- **Bring forward** (Ctrl+])
- **Send backward** (Ctrl+[)

### 3.7 Canvas zoom

| Action | Effect |
|---|---|
| Ctrl + scroll wheel | Zoom in/out (25% steps: 25%, 50%, 75%, 100%, 150%, 200%) |
| Ctrl + 0 | Fit to window |
| Ctrl + 1 | 100% |
| Zoom slider in toolbar | Continuous zoom |

The zoom only affects the canvas display, not the report definition. All
positions and sizes are stored in page pixels.

---

## 4. Visual lifecycle

### 4.1 Adding a visual

Two ways:
1. **From the visual picker:** Click a visual type icon (bar, line, card, etc.)
   → a new empty visual appears at the centre of the visible canvas area with
   default dimensions.
2. **Drag from picker to canvas:** Drop at a specific position.

A new visual starts **empty** (no data). It shows a placeholder:
*"Drag fields from the Data pane into the wells on the right."*

### 4.2 Configuring a visual

The user drags fields (columns or measures) from the Data pane into the
visual's wells. Each drop triggers:
1. Wells validation (does this well accept this type?).
2. Semantic query generation (the visual wrapper's `toQuery` function).
3. Query execution via the engine.
4. Visual re-render with the returned data.

### 4.3 Changing visual type

The user can change a visual's type (e.g., bar chart → line chart) without
losing the field configuration. The designer:
1. Maps the old wells to the new wells by role (Axis → Axis, Values → Values).
2. Drops fields that don't fit the new type (e.g., a stacked bar's Legend well
   has no equivalent in a card visual).
3. Re-queries and re-renders.

### 4.4 Deleting a visual

Select → Delete key (or context menu → Delete). Undo-able.

### 4.5 Copy / paste

- **Ctrl+C / Ctrl+V:** Copies the visual with its well configuration, format
  settings, and filters. Paste offsets the position by 20px down and right.
- **Cross-page:** Not applicable (one-page reports), but the clipboard format
  is JSON, so it works across reports if the dataset model matches.

---

## 5. Wells (field buckets)

### 5.1 What a well is

A well is a named slot that accepts one or more fields. Each visual type
defines its wells in its `VisualDefinition`:

```typescript
interface WellDefinition {
  id: string;            // "category", "values", "legend", "tooltips"
  label: string;         // "Axis", "Values", "Legend", "Tooltips"
  accepts: FieldType[];  // ["string", "date"] or ["measure"] or ["any"]
  min: number;           // 0 = optional, 1 = required
  max: number;           // 1 = single field, 5 = up to 5 measures
  description?: string;  // tooltip: "The column that splits bars into groups"
}

type FieldType = "string" | "integer" | "decimal" | "date" | "boolean" | "measure" | "any";
```

### 5.2 Standard wells by visual type

| Visual | Well 1 | Well 2 | Well 3 | Well 4 |
|---|---|---|---|---|
| **Bar / Column** | Axis (string/date, max 1) | Values (measure, max 5) | Legend (string, max 1) | Tooltips (measure, max 3) |
| **Line / Area** | X-axis (date/string, max 1) | Values (measure, max 5) | Legend (string, max 1) | Tooltips (measure, max 3) |
| **Pie / Donut** | Category (string, max 1) | Values (measure, max 1) | — | Tooltips (measure, max 3) |
| **Card** | Value (measure, max 1) | — | — | — |
| **KPI** | Value (measure, max 1) | Trend axis (date, max 1) | Target (measure, max 1) | — |
| **Table** | Columns (any, max 20) | — | — | — |
| **Matrix** | Rows (string, max 4) | Columns (string, max 2) | Values (measure, max 10) | — |
| **Scatter** | X (measure, max 1) | Y (measure, max 1) | Size (measure, max 1) | Details (string, max 1) |
| **Map** | Location (string, max 1) | Size (measure, max 1) | Colour (measure, max 1) | Tooltips (measure, max 3) |
| **Gauge** | Value (measure, max 1) | Target (measure, max 1) | Min (measure, max 1) | Max (measure, max 1) |
| **Waterfall** | Category (string, max 1) | Values (measure, max 1) | Breakdown (string, max 1) | — |
| **Treemap** | Category (string, max 1) | Size (measure, max 1) | Colour (measure, max 1) | — |
| **Slicer** | Field (string/date, max 1) | — | — | — |
| **Text box** | — (static content) | — | — | — |
| **Image** | — (URL or uploaded) | — | — | — |
| **Button** | — (action configuration) | — | — | — |
| **Shape** | — (rectangle, line, etc.) | — | — | — |

### 5.3 Drag-into-well behaviour

When a field is dropped into a well:

1. **Type check:** If the field's type is not in the well's `accepts` list,
   reject the drop (the well highlights red briefly).
2. **Max check:** If the well is full (`max` reached), either:
   - Replace the last field (for max-1 wells like Axis).
   - Reject the drop (for multi-field wells at capacity).
3. **Auto-aggregate:** If a numeric column is dropped into a measure well, the
   designer automatically wraps it in `SUM()` and creates an implicit measure.
   The user can change the aggregation (Average, Count, Min, Max) via a
   dropdown on the well chip.
4. **Re-query:** The visual wrapper's `toQuery` generates a new SemanticQuery,
   the engine executes it, and the visual re-renders.

### 5.4 Well chips

Each field in a well is rendered as a **chip** (pill-shaped tag):

```
┌──────────────────────────────────────┐
│  ▼ Values                            │
│  ┌─────────────┐ ┌─────────────────┐ │
│  │ Σ Trips   ✕ │ │ Σ Completion  ✕ │ │
│  └─────────────┘ └─────────────────┘ │
└──────────────────────────────────────┘
```

- **Σ icon** = measure (aggregated). **A** icon = text column. **#** = number.
  **📅** = date.
- **Click the chip** → dropdown: rename the display name, change aggregation,
  remove.
- **✕ button** → remove the field from the well.
- **Drag chips** within a well to reorder (affects the series order in charts).

---

## 6. The property pane

The property pane appears when a visual is selected. It has two tabs:

### 6.1 Build tab

Shows the wells for the selected visual. This is where the user drags fields.
(Described in §5.)

### 6.2 Format tab

Organises formatting options into collapsible sections. The sections are
driven by the visual's `formatSchema` — a JSON Schema that defines every
configurable property:

```typescript
interface FormatSchema {
  sections: FormatSection[];
}

interface FormatSection {
  id: string;           // "title", "legend", "dataLabels", "colors", etc.
  label: string;        // "Title", "Legend", "Data labels", "Colors"
  properties: FormatProperty[];
}

interface FormatProperty {
  id: string;           // "titleText", "titleFontSize", "titleColor"
  label: string;        // "Text", "Font size", "Color"
  type: "text" | "number" | "color" | "boolean" | "select" | "slider" | "font";
  default: any;
  options?: { label: string; value: any }[];  // for "select" type
  min?: number;         // for "number" / "slider"
  max?: number;
  step?: number;
}
```

### 6.3 Standard format sections

Every visual has these sections (some may be hidden if not applicable):

| Section | Properties | Notes |
|---|---|---|
| **General** | Width, Height, X, Y, Background colour, Border, Border radius, Padding, Shadow | Precise positioning controls |
| **Title** | Text, Font family, Font size, Font colour, Alignment, Background | The visual's heading |
| **Legend** | Show, Position (top/bottom/left/right), Font size, Colour | For multi-series visuals |
| **X-axis** / **Y-axis** | Show, Label, Font, Range (auto/custom), Gridlines | For Cartesian charts |
| **Data labels** | Show, Font, Colour, Position (inside/outside/auto), Format string | Values rendered on marks |
| **Data colours** | Per-series colour pickers | Manual overrides of theme colours |
| **Conditional formatting** | Rules: if value > X → colour, icon, data bar | Per-column rules for table/matrix |
| **Tooltips** | Show, Custom tooltip page (future), Fields | |
| **Interactions** | Cross-filter, Cross-highlight, None | Per-visual interaction mode |

### 6.4 Format controls (React components)

Each property type maps to a React component:

| Type | Component | Notes |
|---|---|---|
| `text` | `<TextInput>` | |
| `number` | `<NumberInput>` with stepper | Min/max/step enforced |
| `color` | `<ColorPicker>` | Shows theme palette + custom hex |
| `boolean` | `<Toggle>` | On/off switch |
| `select` | `<Dropdown>` | |
| `slider` | `<Slider>` | Range with number input |
| `font` | `<FontPicker>` | Dropdown of available fonts |

Changes are applied **immediately** (live preview) and added to the undo stack.

---

## 7. The data pane

The data pane shows the dataset model as a tree:

```
▼ Trip
    TripId
    StartDate
    EndDate
    DistanceKm
    Status
    Σ [Trips]
    Σ [Completion %]
    Σ [Trips LY]
▼ Directorate
    DepartmentGuid
    Name
    Region
▼ Vehicle
    VehicleGuid
    Type
    Make
    Model
    Weight
▼ Date
    Date
    Year
    Quarter
    Month
    MonthName
    Day
    DayOfWeek
```

### 7.1 Icons

| Icon | Meaning |
|---|---|
| **Σ** | Measure (defined in the model) |
| **#** | Numeric column |
| **A** | Text column |
| **📅** | Date column |
| **🔑** | Key column (primary key or foreign key) |
| **fx** | Calculated column |
| **👁** (dimmed) | Hidden column (not shown by default; toggle to show) |

### 7.2 Search

A search box at the top filters the tree: type "trip" and only tables/columns
containing "trip" appear.

### 7.3 Drag from data pane

Fields are dragged from the data pane to:
- A **specific well** → placed in that well.
- The **canvas** (not onto a visual) → creates a new visual using a heuristic:
  - Measure → Card visual
  - Text column → Table visual with that column
  - Date column → Line chart with a default measure (if one exists)

### 7.4 Right-click context menu

- **Add to current visual** → adds to the first compatible well.
- **New measure** → opens the formula editor.
- **New calculated column** → opens the formula editor in column mode.
- **Hide / unhide** → toggles the column's visibility.

---

## 8. Interactions and cross-filtering

### 8.1 How it works at runtime

When the user clicks a data point in one visual (e.g., a bar for "Operations"),
the report runtime:

1. Extracts the clicked dimension values: `{ "Directorate[Name]": "Operations" }`.
2. For every **other** visual on the page, checks its interaction mode:
   - **Cross-filter** (default): add the clicked values as filters to the
     other visual's semantic query, re-query, re-render.
   - **Cross-highlight** (for bar/column charts): keep all data but dim the
     non-matching marks (reduce opacity).
   - **None**: the visual is unaffected.
3. The clicked visual shows a "selected" state (highlighted bar, outlined
   point, etc.).

### 8.2 How the designer configures it

The designer has an **Edit interactions** mode (toggled from the toolbar).
When active:

- Selecting a visual shows icons on every other visual:
  - **Filter icon** (funnel) → cross-filter
  - **Highlight icon** (light) → cross-highlight
  - **None icon** (⊘) → no interaction
- Click an icon to cycle through the modes.
- The interaction mode is stored per source→target visual pair.

### 8.3 Interaction state

```typescript
interface InteractionConfig {
  source: string;        // visual ID that emits the click
  target: string;        // visual ID that receives the filter
  mode: "filter" | "highlight" | "none";
}
```

Default: every visual cross-filters every other visual. The user only needs
to configure exceptions.

### 8.4 Implementation

The report runtime manages a `CrossFilterState`:

```typescript
interface CrossFilterState {
  sourceVisualId: string | null;
  selectedValues: Record<string, any>;  // column → value
}
```

When a visual's `onCrossFilter` callback fires:
1. Update `CrossFilterState`.
2. For each other visual, check `InteractionConfig`:
   - **filter**: rebuild its SemanticQuery with the selected values as
     additional filters, re-query.
   - **highlight**: pass the selected values as a `highlightFilter` to the
     visual's render function (the visual dims non-matching marks).
   - **none**: skip.
3. Clicking the same data point again (or clicking empty space) clears the
   cross-filter state.

---

## 9. Filters: report, page and visual level

### 9.1 Filter hierarchy

```
Report-level filters                         (apply to every visual)
  └── Page-level filters                     (apply to every visual on this page)
        └── Visual-level filters             (apply to one visual only)
              └── Cross-filter selections    (runtime, not saved)
                    └── RLS predicates       (injected by the server, invisible to the user)
```

All filters are additive (AND). A visual-level filter further restricts the
page-level filter, which further restricts the report-level filter.

### 9.2 The filter pane

The filter pane (bottom drawer) has three tabs:

| Tab | Filters for | Editable when |
|---|---|---|
| **This visual** | The selected visual | A visual is selected |
| **This page** | The current page | Always |
| **All pages** | The entire report | Always |

Each tab shows a list of filter cards. Each card:

```
┌───────────────────────────────┐
│ Date[Year]              ✕ ▾  │
│ ┌───────────────────────────┐ │
│ │ ☑ 2024                    │ │
│ │ ☑ 2025                    │ │
│ │ ☐ 2026                    │ │
│ └───────────────────────────┘ │
│ Filter type: Basic  ▾        │
└───────────────────────────────┘
```

### 9.3 Filter types

| Type | UI | Generates |
|---|---|---|
| **Basic** | Checkboxes for each distinct value | `op: "in", values: [...]` |
| **Advanced** | Two condition rows with AND/OR | `op: "and"`, two sub-predicates |
| **Top N** | Top/Bottom N by a measure | Post-query filter (applied after aggregation) |
| **Relative date** | "Last 3 months", "This year", etc. | Dynamic date range predicate |

### 9.4 Adding a filter

Drag a field from the data pane to the filter pane (or right-click → "Add as
filter"). This opens a new filter card. The distinct values are loaded by
querying `SELECT DISTINCT col FROM table ORDER BY col`.

### 9.5 Locked filters (report embedding)

When a report is embedded, the host application can pass **locked filters**
that the viewer cannot change. These are visually present but greyed out,
and the API marks them as `"locked": true`.

---

## 10. Undo / redo

### 10.1 The undo stack

Every user action pushes an entry onto the undo stack:

```typescript
interface UndoEntry {
  description: string;     // "Moved visual 'bar-01' to (120, 340)"
  timestamp: number;
  patch: JsonPatch;        // RFC 6902 JSON Patch (forward)
  inversePatch: JsonPatch; // RFC 6902 JSON Patch (backward)
}
```

Using JSON Patch (RFC 6902) means undo/redo is a matter of applying the
inverse patch or the forward patch to the report definition JSON. The entire
report state is derivable from the definition, so patching the definition
and re-rendering is sufficient.

### 10.2 Granularity

| Action | One undo entry |
|---|---|
| Move a visual (drag) | Final position (not every intermediate pixel) |
| Resize a visual | Final size |
| Drop a field into a well | The well change |
| Change a format property | The property change |
| Delete a visual | The removal (undo restores it) |
| Paste a visual | The addition |
| Reorder well fields | The new order |

### 10.3 Limits

- Max undo depth: 100 entries.
- Undo is per-session (not persisted across saves). Saving clears the undo
  stack (the saved version becomes the new baseline).

### 10.4 Shortcuts

- **Ctrl+Z**: Undo
- **Ctrl+Y** / **Ctrl+Shift+Z**: Redo

---

## 11. Report definition JSON schema

The report definition is the single source of truth for a report's layout and
configuration. It is saved as JSON and served via the API.

```typescript
interface ReportDefinition {
  // Identity
  id: string;                      // UUID
  name: string;                    // "Fleet Availability"
  datasetId: string;               // the semantic model this report is built on
  version: number;                 // incremented on each save

  // Page (single page per report)
  page: PageDefinition;

  // Report-level settings
  theme?: ThemeOverrides;          // overrides the workspace default theme
  reportFilters: FilterDefinition[];

  // Interaction defaults
  defaultInteractionMode: "filter" | "highlight";

  // Metadata
  createdAt: string;               // ISO 8601
  updatedAt: string;
  createdBy: string;               // user ID
}

interface PageDefinition {
  width: number;                   // 1760
  height: number;                  // 990
  background?: {
    color?: string;                // hex
    image?: string;                // URL
    transparency?: number;         // 0–100
  };
  visuals: VisualDefinition[];
  pageFilters: FilterDefinition[];
}

interface VisualDefinition {
  id: string;                      // UUID, stable across edits
  type: string;                    // "barChart", "lineChart", "card", "table", etc.

  // Position and size (page pixels)
  x: number;
  y: number;
  width: number;
  height: number;
  z: number;                       // z-order (higher = on top)

  // Data binding
  wells: WellBinding[];

  // Formatting (all optional — defaults come from the visual type + theme)
  format: Record<string, any>;     // keyed by FormatProperty.id

  // Visual-level filters
  filters: FilterDefinition[];

  // Interaction overrides (defaults to report-level defaultInteractionMode)
  interactions?: InteractionConfig[];

  // Visibility
  visible: boolean;                // false = hidden in the viewer (conditional visibility)
  visibilityRule?: string;         // DAX-lite boolean expression (future)
}

interface WellBinding {
  wellId: string;                  // matches WellDefinition.id ("category", "values", etc.)
  fields: FieldBinding[];
}

interface FieldBinding {
  type: "column" | "measure";

  // For columns
  table?: string;
  column?: string;
  aggregation?: "sum" | "average" | "count" | "min" | "max" | "distinctCount" | "none";

  // For measures
  measure?: string;

  // Display
  alias?: string;                  // user-facing label override
  format?: string;                 // format string override
  sortOrder?: "asc" | "desc" | null;
}

interface FilterDefinition {
  table: string;
  column: string;
  type: "basic" | "advanced" | "topN" | "relativeDate";
  config: BasicFilterConfig | AdvancedFilterConfig | TopNConfig | RelativeDateConfig;
  locked?: boolean;                // for embedded reports
}

interface BasicFilterConfig {
  operator: "in" | "notIn" | "all";
  values: any[];
  requireSingleSelection?: boolean; // slicer behaviour
}

interface AdvancedFilterConfig {
  logicalOperator: "and" | "or";
  conditions: {
    operator: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "contains" | "startsWith" | "isBlank" | "isNotBlank";
    value: any;
  }[];
}

interface TopNConfig {
  direction: "top" | "bottom";
  count: number;
  orderByMeasure: string;
}

interface RelativeDateConfig {
  anchor: "today" | "endOfLastMonth" | "endOfLastQuarter" | "endOfLastYear";
  unit: "days" | "weeks" | "months" | "quarters" | "years";
  count: number;
  includeToday?: boolean;
}

interface InteractionConfig {
  targetVisualId: string;
  mode: "filter" | "highlight" | "none";
}

interface ThemeOverrides {
  palette?: string[];              // categorical colour palette
  font?: string;                   // default font family
  fontSize?: number;               // base font size
  background?: string;             // page background
  foreground?: string;             // default text colour
  cardBackground?: string;
  cardBorderRadius?: number;
}
```

### 11.1 Example: a simple bar chart report

```json
{
  "id": "rpt-fleet-availability",
  "name": "Fleet Availability",
  "datasetId": "ds-transport",
  "version": 3,
  "page": {
    "width": 1760,
    "height": 990,
    "background": { "color": "#F5F6FA" },
    "visuals": [
      {
        "id": "viz-title",
        "type": "textBox",
        "x": 24, "y": 16, "width": 400, "height": 48, "z": 1,
        "wells": [],
        "format": {
          "text": "Fleet Availability",
          "fontSize": 24,
          "fontWeight": "bold",
          "fontColor": "#1B2A4A"
        },
        "filters": [],
        "visible": true
      },
      {
        "id": "viz-card-trips",
        "type": "card",
        "x": 24, "y": 80, "width": 200, "height": 120, "z": 1,
        "wells": [
          {
            "wellId": "value",
            "fields": [{ "type": "measure", "measure": "Trips" }]
          }
        ],
        "format": {
          "cardBackground": "#FFFFFF",
          "cardBorderRadius": 8,
          "valueFontSize": 32,
          "labelFontSize": 12
        },
        "filters": [],
        "visible": true
      },
      {
        "id": "viz-bar-trips",
        "type": "barChart",
        "x": 24, "y": 220, "width": 840, "height": 400, "z": 1,
        "wells": [
          {
            "wellId": "category",
            "fields": [{ "type": "column", "table": "Directorate", "column": "Name" }]
          },
          {
            "wellId": "values",
            "fields": [
              { "type": "measure", "measure": "Trips" },
              { "type": "measure", "measure": "Trips LY", "alias": "Prior Year" }
            ]
          }
        ],
        "format": {
          "showTitle": true,
          "titleText": "Trips by Directorate",
          "showLegend": true,
          "legendPosition": "top",
          "showDataLabels": false
        },
        "filters": [],
        "visible": true
      },
      {
        "id": "viz-slicer-year",
        "type": "slicer",
        "x": 1400, "y": 80, "width": 320, "height": 60, "z": 2,
        "wells": [
          {
            "wellId": "field",
            "fields": [{ "type": "column", "table": "Date", "column": "Year" }]
          }
        ],
        "format": {
          "slicerType": "dropdown",
          "singleSelect": true
        },
        "filters": [],
        "visible": true
      }
    ],
    "pageFilters": [
      {
        "table": "Date",
        "column": "Year",
        "type": "basic",
        "config": { "operator": "in", "values": [2026] }
      }
    ]
  },
  "reportFilters": [],
  "defaultInteractionMode": "filter",
  "createdAt": "2026-10-29T10:00:00Z",
  "updatedAt": "2026-10-29T14:30:00Z",
  "createdBy": "user-42"
}
```

### 11.2 Versioning

The report definition uses a `version` counter. Each save increments it. The
API supports optimistic concurrency: a save with a stale version is rejected
(`409 Conflict`), and the client must reload and merge.

### 11.3 Validation

Before saving, the client validates:
1. Every `VisualDefinition.type` is a known visual type.
2. Every `FieldBinding` references an existing table/column/measure in the
   dataset model.
3. Every visual's required wells have at least `min` fields.
4. Positions and sizes are within the page bounds (warning, not error).
5. No circular filter references.
6. JSON schema validation against the report definition schema.

---

## 12. Theming

### 12.1 Theme hierarchy

```
Built-in defaults
  └── Workspace theme (set by admin)
        └── Report theme overrides (set by author)
              └── Visual format overrides (set by author per visual)
```

Each level overrides the one above. The visual's `format` properties are the
most specific.

### 12.2 Theme tokens

A theme provides these tokens (matching the v2 design system):

```typescript
interface Theme {
  // Colours
  palette: string[];           // categorical colour palette (8–12 colours)
  background: string;          // page background
  foreground: string;          // default text colour
  secondaryText: string;       // muted text
  cardBackground: string;      // visual card background
  cardBorder: string;          // visual card border
  gridlineColor: string;       // chart gridlines
  axisColor: string;           // axis lines and labels

  // Status colours (never used for categorical)
  statusGood: string;
  statusWarning: string;
  statusSerious: string;
  statusCritical: string;

  // Typography
  fontFamily: string;          // "Segoe UI", "Inter", etc.
  baseFontSize: number;        // 12
  titleFontSize: number;       // 16
  headerFontSize: number;      // 14
  labelFontSize: number;       // 11

  // Layout
  cardBorderRadius: number;    // 8
  cardPadding: number;         // 16
  cardShadow: string;          // CSS box-shadow value
  spacing: number;             // default gap between visuals (for auto-layout)
}
```

### 12.3 ECharts theme mapping

The Theme tokens are converted into an ECharts theme at load time:

```typescript
function toEChartsTheme(theme: Theme): object {
  return {
    color: theme.palette,
    backgroundColor: "transparent",  // card handles background
    textStyle: {
      fontFamily: theme.fontFamily,
      fontSize: theme.baseFontSize,
      color: theme.foreground,
    },
    title: {
      textStyle: {
        fontSize: theme.titleFontSize,
        color: theme.foreground,
      },
    },
    legend: {
      textStyle: { color: theme.secondaryText },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: theme.axisColor } },
      axisLabel: { color: theme.secondaryText },
      splitLine: { lineStyle: { color: theme.gridlineColor } },
    },
    valueAxis: {
      axisLine: { show: false },
      axisLabel: { color: theme.secondaryText },
      splitLine: { lineStyle: { color: theme.gridlineColor } },
    },
  };
}
```

### 12.4 MSD ERP default theme

The MSD ERP workspace ships with the v2 "ERP Native" theme:

```typescript
const msdTheme: Theme = {
  palette: ["#1B2A4A", "#2E5090", "#E8792F", "#4CA882", "#7B68A8", "#C44E52", "#D4A843", "#5BA4CF"],
  background: "#F5F6FA",
  foreground: "#1B2A4A",
  secondaryText: "#6B7A8D",
  cardBackground: "#FFFFFF",
  cardBorder: "#E2E6ED",
  gridlineColor: "#EBEEF2",
  axisColor: "#6B7A8D",
  statusGood: "#4CA882",
  statusWarning: "#D4A843",
  statusSerious: "#E8792F",
  statusCritical: "#C44E52",
  fontFamily: "Segoe UI, Inter, sans-serif",
  baseFontSize: 12,
  titleFontSize: 16,
  headerFontSize: 14,
  labelFontSize: 11,
  cardBorderRadius: 8,
  cardPadding: 16,
  cardShadow: "0 1px 3px rgba(27, 42, 74, 0.08)",
  spacing: 16,
};
```

---

## 13. Keyboard and accessibility

### 13.1 Keyboard shortcuts

| Shortcut | Action |
|---|---|
| **Tab** | Cycle focus through visuals on the canvas |
| **Arrow keys** | Nudge selected visual by 1px (8px with snap) |
| **Shift+Arrow** | Nudge by 10px |
| **Delete** / **Backspace** | Delete selected visual |
| **Ctrl+A** | Select all visuals |
| **Ctrl+C / V / X** | Copy / Paste / Cut |
| **Ctrl+D** | Duplicate selected visual |
| **Ctrl+Z / Y** | Undo / Redo |
| **Ctrl+S** | Save report |
| **Ctrl+G** | Group selected visuals (future) |
| **Ctrl+Shift+G** | Ungroup (future) |
| **Escape** | Deselect / close property pane / exit mode |
| **F2** | Edit text (for text box visuals) |
| **Ctrl+]** / **Ctrl+[** | Bring forward / Send backward |

### 13.2 ARIA roles

| Element | Role | Notes |
|---|---|---|
| Canvas | `role="application"` | Indicates custom keyboard interaction |
| Visual container | `role="group"` + `aria-label` | e.g., "Bar chart: Trips by Directorate" |
| Well | `role="listbox"` | Accepts drag-and-drop items |
| Well chip | `role="option"` | Removable, reorderable |
| Property control | Standard form roles | Input, checkbox, slider, etc. |
| Data pane tree | `role="tree"` / `role="treeitem"` | |
| Filter card | `role="group"` | |

### 13.3 Screen reader announcements

Key state changes are announced via `aria-live="polite"` regions:
- "Added Trips measure to Values well. Showing 8 data points."
- "Visual moved to 120, 340."
- "Visual resized to 400 by 300."
- "Filter applied: Year equals 2026."

---

## 14. Responsive layout (future)

Not in the MVP. The MVP uses fixed-position layout only. Future:

### 14.1 Concept

The user defines **breakpoints** (e.g., mobile: 375px, tablet: 768px,
desktop: 1280px+). For each breakpoint, visuals can have different positions,
sizes, or visibility. This is similar to Power BI's mobile layout view.

### 14.2 Implementation approach

Each visual's position becomes an array of `(breakpoint, x, y, w, h)` tuples.
The viewer selects the matching breakpoint at render time.

```typescript
interface ResponsivePosition {
  breakpoint: "mobile" | "tablet" | "desktop";
  x: number; y: number;
  width: number; height: number;
  visible: boolean;
}
```

The designer shows a breakpoint picker in the toolbar. Switching breakpoints
shows the canvas at that width, and the user rearranges visuals for that size.

---

## 15. State management

### 15.1 Architecture

The designer uses a single Zustand store:

```typescript
interface DesignerStore {
  // Report definition (the source of truth)
  report: ReportDefinition;

  // UI state (not persisted)
  selectedVisualIds: string[];
  hoveredVisualId: string | null;
  zoom: number;                       // 0.25 to 2.0
  activePaneTab: "build" | "format";
  filterPaneOpen: boolean;
  editInteractionsMode: boolean;
  isDirty: boolean;                   // unsaved changes?

  // Cross-filter state (runtime only)
  crossFilter: CrossFilterState | null;

  // Query cache (runtime only)
  queryCache: Map<string, DSR>;

  // Undo stack (runtime only)
  undoStack: UndoEntry[];
  redoStack: UndoEntry[];

  // Actions
  addVisual(type: string, position?: { x: number; y: number }): void;
  moveVisual(id: string, x: number, y: number): void;
  resizeVisual(id: string, width: number, height: number): void;
  deleteVisual(id: string): void;
  setWellField(visualId: string, wellId: string, fields: FieldBinding[]): void;
  setFormatProperty(visualId: string, property: string, value: any): void;
  addFilter(level: "report" | "page" | "visual", filter: FilterDefinition): void;
  setCrossFilter(state: CrossFilterState | null): void;
  undo(): void;
  redo(): void;
  save(): Promise<void>;
}
```

### 15.2 Derived state

Several values are computed from the store:

```typescript
// Active visual's definition
const activeVisual = useDesigner(s =>
  s.report.page.visuals.find(v => v.id === s.selectedVisualIds[0])
);

// The semantic query for a visual (derived from its wells + all filter levels)
function buildSemanticQuery(visual: VisualDefinition, report: ReportDefinition): SemanticQuery {
  const visualType = visualRegistry[visual.type];
  return visualType.toQuery(
    visual.wells,
    [
      ...report.reportFilters,
      ...report.page.pageFilters,
      ...visual.filters,
    ]
  );
}
```

### 15.3 Query lifecycle

When a visual's wells or filters change:

1. `buildSemanticQuery` generates the new SemanticQuery.
2. Check the `queryCache` for an existing result with the same cache key.
3. If miss: POST the SemanticQuery to the engine API → receive DSR.
4. Store the DSR in the cache.
5. Pass the DSR to the visual's `render` function.

Each visual manages its own loading state (skeleton while querying) so the
rest of the page stays interactive.

### 15.4 Debouncing

Format property changes (e.g., dragging a colour slider) are debounced at
150ms — the visual re-renders immediately (using local state), but the undo
entry is only pushed after the debounce settles.

---

## 16. File structure

```
web/src/designer/
├── DesignerApp.tsx           # Top-level layout (canvas + panes)
├── store.ts                  # Zustand store (DesignerStore)
├── canvas/
│   ├── Canvas.tsx            # The canvas container (zoom, scroll, snap grid)
│   ├── VisualContainer.tsx   # Absolute-positioned wrapper for each visual
│   ├── SelectionBox.tsx      # Rubber-band selection
│   ├── SmartGuides.tsx       # Alignment guide lines
│   └── ResizeHandles.tsx     # 8 handles for drag-resize
├── panes/
│   ├── VisualPicker.tsx      # Grid of visual type icons
│   ├── BuildPane.tsx         # Wells for the selected visual
│   ├── FormatPane.tsx        # Format property sections
│   ├── DataPane.tsx          # Table/column/measure tree
│   └── FilterPane.tsx        # Report/page/visual filter cards
├── wells/
│   ├── Well.tsx              # A single well (drop target)
│   ├── WellChip.tsx          # A field chip in a well
│   └── AggregationMenu.tsx   # SUM/AVG/COUNT dropdown
├── filters/
│   ├── FilterCard.tsx        # One filter rule
│   ├── BasicFilter.tsx       # Checkbox list
│   ├── AdvancedFilter.tsx    # Condition builder
│   ├── TopNFilter.tsx        # Top/Bottom N
│   └── RelativeDateFilter.tsx
├── format-controls/
│   ├── TextInput.tsx
│   ├── NumberInput.tsx
│   ├── ColorPicker.tsx
│   ├── Toggle.tsx
│   ├── Dropdown.tsx
│   ├── Slider.tsx
│   └── FontPicker.tsx
├── interactions/
│   ├── CrossFilterManager.tsx   # Manages cross-filter state
│   ├── InteractionEditor.tsx    # Edit-interactions mode UI
│   └── HighlightOverlay.tsx     # Dims non-matching marks
├── toolbar/
│   ├── Toolbar.tsx              # Top bar: save, undo, zoom, edit interactions
│   └── ZoomControl.tsx
├── hooks/
│   ├── useDragVisual.ts         # dnd-kit hook for moving visuals
│   ├── useResizeVisual.ts       # dnd-kit hook for resize handles
│   ├── useDragField.ts          # dnd-kit hook for field → well
│   ├── useVisualQuery.ts        # Fetches DSR when wells/filters change
│   └── useUndoRedo.ts           # Keyboard shortcut wiring
└── utils/
    ├── snapToGrid.ts            # Snap coordinates to grid
    ├── smartGuides.ts            # Compute alignment guides
    ├── jsonPatch.ts             # RFC 6902 patch generation
    └── reportValidation.ts      # Pre-save validation
```

---

## Summary: what this spec pins down

| Question | Answer |
|---|---|
| What does the designer look like? | §2 — three-pane layout: canvas + right panel (wells + format + data) + filter drawer |
| How are visuals positioned? | §3 — free-form absolute positioning in page-pixel coordinates, snap-to-grid, smart guides |
| How does data get into a visual? | §5 — drag fields from data pane into typed wells; each drop re-queries and re-renders |
| How do visuals interact? | §8 — cross-filter by default; configurable per source→target pair |
| What is the report saved as? | §11 — a single JSON file with typed interfaces for every element |
| How does theming work? | §12 — theme tokens → ECharts theme; four-level override hierarchy |
| How is state managed? | §15 — single Zustand store, JSON Patch undo/redo, debounced format changes |
| What's the file structure? | §16 — ~30 React components in `web/src/designer/` |

This spec and the visuals library analysis together define the entire frontend.
The designer handles layout and configuration; the visual wrappers handle
rendering; the query engine handles data.
