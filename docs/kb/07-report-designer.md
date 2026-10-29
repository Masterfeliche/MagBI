# 07 — Report Designer

> **Status: Shipped in MAGBI-009.** The viewer and embed SDK stay in Sprint 10.

The designer route is `/workspaces/:workspaceId/datasets/:datasetId/designer`.
It loads that dataset and draws each visual with `POST /api/v1/workspaces/{workspaceId}/datasets/{datasetId}/query`.
Column, bar, line, pie, card, and table render the result. Map explains that it needs coordinates.
Slicer writes a page filter. Scatter, funnel, gauge, treemap, and waterfall stay in the gallery and are not drawn as a column chart.
Publish stores the definition and `is_published` with `POST` and `PUT /api/v1/workspaces/{workspaceId}/reports`.
Opening a published report is Sprint 10.

---

## What It Does

The report designer is where users build dashboards. Filters and Build are right-side rails, and only one is open so the 1760×990 page stays large:

```
┌──────────────────────────────────────────────┬────────┬────┐
│ Ribbon: name, Undo, Redo, Publish           │        │    │
├──────────────────────────────────────────────┤ Build  │ F  │
│                                              │ or     │ i  │
│            Page (1760×990, scaled)           │ Filters│ l  │
│                                              │        │ t  │
└──────────────────────────────────────────────┴────────┴────┘
```

The Build rail lists fields, the visual gallery, and the wells (Y-axis, X-axis, Legend).
Format on that rail sets a title and one color. The Filters rail adds page filters (`eq` and `in`).
Dragging a visual records one undo patch when the pointer goes up.
The result is a **Report Definition** — a JSON document that describes everything on the page.

---

## Why This Approach

### Free-form canvas, not a grid

Two layout philosophies exist in BI tools:

| Approach | Examples | Pros | Cons |
|----------|---------|------|------|
| **Free-form canvas** | Power BI, Tableau | Pixel-perfect control; any layout | Does not reflow on resize |
| **Grid/tile layout** | Metabase, Superset, Grafana | Auto-reflows; responsive | Limited layout flexibility |

MagBI uses a free-form canvas because:

1. **The first customer (MSD ERP)** needs pixel-perfect dashboards that match
   specific mockups. Grid layouts cannot reproduce arbitrary designs.
2. **Canvas is what Power BI users expect.** Our target users already know how
   to position visuals by dragging and resizing.
3. **Grid can be added later** as an alternative mode. But you cannot go from
   grid to free-form — the abstractions do not compose that way.

**The trade-off is responsiveness.** A 1760×990 canvas looks perfect on a 1920×1080
display. On a tablet or phone, it must be scaled down (with `transform: scale()`)
or scrolled. True responsive reflow is a future feature, not a launch
requirement.

### Why 1760×990?

This is the MagBI standard canvas size. The reasoning:

- **1920×1080** is the most common display resolution (Full HD)
- Subtract browser chrome, scrollbar, and ERP sidebar: ~160px horizontal,
  ~90px vertical
- **1760×990** fits within the ERP embed viewport at 1:1 scale — no scrolling,
  no scaling on the most common monitor

The canvas is defined in the report JSON and can technically be any size, but
1760×990 is the default and the size our standard dashboards target.

### dnd-kit for drag-and-drop

**Why dnd-kit** (over alternatives):

| Library | Pros | Cons | Verdict |
|---------|------|------|---------|
| **dnd-kit** | Headless (no DOM opinions), keyboard/a11y built in, modular (core + sortable + utilities), smooth animations | Newer, smaller community | **Chosen** |
| react-beautiful-dnd | Polished drag animations, large community | Not maintained (Atlassian archived it), list-focused (not free-form) | Archived |
| react-dnd | Flexible, supports custom backends | Complex API, no built-in a11y, requires understanding backends/monitors | Too low-level |
| react-grid-layout | Perfect for dashboard grids | Grid only — cannot do free-form positioning | Wrong paradigm |

dnd-kit is headless — it provides the drag-and-drop logic (collision detection,
drop targets, keyboard handling) without dictating the DOM structure. This is
critical for a free-form canvas where visuals can overlap, snap to grid, and
resize from any edge.

### Zustand for state management

**Why Zustand** (over Redux, MobX, Jotai):

| Library | Pros | Cons | Verdict |
|---------|------|------|---------|
| **Zustand** | Minimal API (~7 functions), no boilerplate, React-external access, TypeScript-native | Smaller ecosystem than Redux | **Chosen** |
| Redux Toolkit | Huge ecosystem, devtools, middleware | Boilerplate (slices, reducers, selectors), complex for medium apps | Overkill |
| MobX | Automatic reactivity, no selectors | Magic proxies hide data flow, hard to debug | Too implicit |
| Jotai | Atomic state, great for independent atoms | Awkward for interrelated state (canvas + selection + undo) | Too granular |

The designer's state is highly interrelated: selecting a visual affects the
property pane, the wells, and the canvas highlights. Zustand lets us model this
as a single store with simple functions:

```typescript
const useDesignerStore = create<DesignerState>((set, get) => ({
  report: null,
  selectedVisualId: null,
  undoStack: [],
  redoStack: [],

  selectVisual: (id) => set({ selectedVisualId: id }),
  moveVisual: (id, x, y) => { /* update + push to undo stack */ },
  undo: () => { /* apply reverse patch */ },
}));
```

Any component can read (`useDesignerStore(s => s.selectedVisualId)`) or write
(`useDesignerStore.getState().selectVisual("v1")`) without props drilling.

---

## How It Works

### Visual lifecycle

1. **Add:** User selects a visual type from the toolbar (bar chart, table,
   card, etc.). A new visual appears at the centre of the canvas with default
   size.
2. **Configure:** User drags fields from the data pane into wells (Axis, Values,
   Legend). The visual fires a semantic query and renders the result.
3. **Position:** User drags the visual to the desired location. Snap-to-grid
   aligns it to an 8px grid. Smart guides show alignment lines when the visual
   approaches the edge of another visual.
4. **Format:** User adjusts properties in the property pane (title, colours,
   axis labels, data labels, etc.).
5. **Change type:** User switches the visual type (e.g., bar chart → line
   chart). Wells are remapped: Axis stays Axis, Values stays Values.
6. **Delete:** User selects the visual and presses Delete. The visual is
   removed from the report JSON.
7. **Copy/paste:** Ctrl+C copies the visual definition to an internal clipboard.
   Ctrl+V places a copy offset by (20px, 20px).

### Snap-to-grid and smart guides

**Snap-to-grid:** All positions round to the nearest 8px. This keeps visuals
aligned without manual effort. The grid is invisible but its effect is visible
when dragging — the visual "jumps" in 8px increments.

**Smart guides:** When a visual is dragged near the edge or centre of another
visual, a guide line appears:

```
 ┌────────────┐
 │  Visual A  │
 └────────────┘
       │          ← guide line (centre alignment)
 ┌─────┴──────┐
 │  Visual B  │
 └────────────┘
```

Smart guides activate within 4px of alignment. They snap to:
- Left/right/top/bottom edges of other visuals
- Centre (horizontal and vertical) of other visuals
- Page margins (20px from each edge)

### The wells system

Wells are the typed field buckets that define a visual's data binding. Each
visual type declares which wells it supports:

| Visual type | Wells |
|-------------|-------|
| Bar chart | Axis (1–2 groupings), Values (1+ measures), Legend (0–1 grouping) |
| Line chart | Axis (1 grouping, typically date), Values (1+ measures), Legend (0–1 grouping) |
| Pie chart | Category (1 grouping), Values (1 measure) |
| Card | Values (1 measure) |
| Table | Values (1+ columns or measures) |
| Matrix | Rows (1+ groupings), Columns (0+ groupings), Values (1+ measures) |
| Scatter | X Axis (1 measure), Y Axis (1 measure), Size (0–1 measure), Details (0–1 grouping) |
| Slicer | Field (1 column) |

**Well chips:** Each field in a well appears as a chip:

```
┌─ Values ──────────────────────┐
│ [Revenue ▼] [Profit ▼]       │
└───────────────────────────────┘
```

The dropdown on each chip lets the user change the aggregation (Sum, Count,
Average, Min, Max, Distinct Count) or remove the field.

**Auto-aggregation:** When a user drags a numeric column into the Values well,
the designer auto-wraps it in `SUM()`. When they drag a text column, it
auto-wraps in `COUNT()`. The user can change this via the chip dropdown.

### Property pane (JSON Schema-driven)

Each visual type defines its configurable properties as a JSON Schema:

```json
{
  "title": { "type": "string", "default": "" },
  "showLegend": { "type": "boolean", "default": true },
  "xAxisLabel": { "type": "string", "default": "" },
  "barColor": { "type": "string", "format": "color", "default": "#4472C4" },
  "dataLabels": {
    "type": "object",
    "properties": {
      "show": { "type": "boolean", "default": false },
      "position": { "type": "string", "enum": ["inside", "outside"] }
    }
  }
}
```

The property pane reads this schema and generates a form: text inputs for
strings, toggles for booleans, colour pickers for `format: color`, dropdowns
for enums, and collapsible sections for nested objects.

**Why JSON Schema:** It is a standard. Every visual author defines their
properties once; the property pane renders them automatically. No custom React
form per visual type. When a visual adds a new property, the property pane
picks it up without code changes.

### Cross-filtering and interactions

When the user clicks a data point in one visual, it cross-filters other visuals
on the page. The designer lets users configure interaction types:

| Type | Effect |
|------|--------|
| **Cross-filter** | Clicked value becomes a filter for other visuals |
| **Cross-highlight** | Other visuals dim non-matching data (without removing it) |
| **None** | No interaction from this source to this target |

**How it works technically:**

1. User clicks "Electronics" on a bar chart
2. The bar chart emits an event: `{ table: "Product", column: "Category", value: "Electronics" }`
3. The designer's interaction manager checks each other visual's interaction
   config
4. For each visual set to "cross-filter," the manager adds a filter to the
   visual's semantic query and re-executes it
5. The affected visuals re-render with the new data

**Performance:** Only affected visuals re-query. The bar chart itself does not
re-query (it just highlights the clicked bar). Visuals set to "none" are skipped
entirely.

### Filter hierarchy

Filters stack in a hierarchy:

```
Report filter (applies to all pages)
  └── Page filter (applies to all visuals on this page)
        └── Visual filter (applies to this visual only)
              └── Cross-filter (from user interaction)
                    └── RLS filter (from security, always present)
```

All filters combine with AND. A visual's effective filter is the conjunction of
all filters in its hierarchy chain. The designer's filter pane shows each level
and lets users add/remove filters at any level.

### Undo/redo with JSON Patch

Every edit to the report generates a **JSON Patch** (RFC 6902) — a minimal diff
describing what changed:

```json
[
  { "op": "replace", "path": "/pages/0/visuals/2/x", "value": 400 },
  { "op": "replace", "path": "/pages/0/visuals/2/y", "value": 200 }
]
```

The undo stack stores these patches. Undo applies the reverse patch; redo
re-applies the forward patch.

**Why JSON Patch instead of the Command pattern:**

The Command pattern requires a separate class for each operation (MoveCommand,
ResizeCommand, AddVisualCommand, etc.). Each class must implement `execute()` and
`undo()`. For 30+ operations, this means 30+ classes.

JSON Patch is generic. ANY change to the report JSON — move, resize, add,
delete, change property, change filter — is automatically captured as a patch.
One mechanism handles all operations. The `fast-json-patch` library computes
patches efficiently.

**Trade-off:** JSON Patch captures *what* changed, not *why*. The undo
description says "moved visual" (inferred from the path), not a rich
description like "moved Revenue Chart to the top-right corner." For our
purposes, this is acceptable.

---

## The Report Definition JSON

The report definition is the output of the designer — a complete description of
every page, visual, binding, filter, and formatting choice:

```typescript
interface ReportDefinition {
  schemaVersion: string;
  name: string;
  datasetId: string;
  pages: PageDefinition[];
  theme?: ThemeOverrides;
  filters?: FilterDefinition[];  // Report-level filters
}

interface PageDefinition {
  name: string;
  displayName: string;
  width: number;   // Default: 1760
  height: number;  // Default: 990
  visuals: VisualDefinition[];
  filters?: FilterDefinition[];  // Page-level filters
}

interface VisualDefinition {
  id: string;        // UUID
  type: string;      // "barChart", "lineChart", "card", etc.
  x: number;         // Absolute position (pixels)
  y: number;
  width: number;
  height: number;
  wells: Record<string, FieldBinding[]>;  // "axis": [...], "values": [...]
  properties?: Record<string, unknown>;    // Visual-specific formatting
  filters?: FilterDefinition[];            // Visual-level filters
  interactions?: InteractionConfig;
}
```

This JSON is stored in the PostgreSQL metadata database and served to the
frontend viewer. The viewer reads it and renders each visual by:

1. Reading the visual's type and looking it up in the visual registry
2. Building a semantic query from the wells and filters
3. Sending the query to the engine
4. Passing the DSR result to the visual's ECharts config builder
5. Rendering the chart

---

## Theming

MagBI themes apply at four levels:

| Level | What it controls | Who sets it |
|-------|-----------------|-------------|
| **System default** | Base colours, fonts, chart defaults | MagBI built-in |
| **Workspace theme** | Organisation-wide overrides | Workspace admin |
| **Report theme** | Report-specific overrides | Report author |
| **Visual override** | Per-visual formatting | Report author |

Lower levels override higher levels. A report author can override the workspace
theme for one report, and then override the report theme for one specific chart.

**ECharts theme mapping:** The theme system generates an ECharts theme object
from MagBI theme tokens:

```typescript
// MagBI theme tokens
{ colors: ["#4472C4", "#ED7D31", "#A5A5A5", ...], font: "Segoe UI" }

// Translated to ECharts theme
{ color: ["#4472C4", "#ED7D31", ...], textStyle: { fontFamily: "Segoe UI" } }
```

The MSD ERP default theme uses navy blue (#1B2A4A) and orange (#ED7D31) from
the MSD colour palette.

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |
| Ctrl+C | Copy selected visual |
| Ctrl+V | Paste visual |
| Delete | Delete selected visual |
| Ctrl+A | Select all visuals |
| Arrow keys | Nudge selected visual by 1px (8px with Shift) |
| Tab | Cycle selection through visuals |
| Escape | Deselect |

**Accessibility:** All canvas operations are keyboard-accessible. Tab cycles
through visuals, Enter activates the property pane, and arrow keys move the
selected visual. Screen readers announce the visual type and position.

---

## Key Concepts

### What is a design canvas?

A design canvas is a 2D surface where objects are placed at absolute pixel
coordinates. Unlike a document (where content flows top-to-bottom) or a grid
(where items snap to cells), a canvas lets objects go anywhere — overlapping,
rotated, or precisely aligned.

**DOM implementation:** Each visual is an absolutely-positioned `<div>` with
`left`, `top`, `width`, and `height` set in pixels. The canvas itself is a
`<div>` with `position: relative` and fixed dimensions. CSS `transform: scale()`
handles zoom and fit-to-viewport.

### What is a semantic query vs. a visual query?

The semantic query is what the engine understands — tables, columns, measures,
filters. The visual query is what the visual needs — often a transformation of
the semantic query result:

- A bar chart needs `[{category: "Electronics", value: 45000}, ...]`
- ECharts needs `{xAxis: {data: [...]}, series: [{data: [...]}]}`

The visual wrapper (chapter 08) bridges this gap: it receives DSR from the
engine and transforms it into the format each chart library expects.

### What is RFC 6902 (JSON Patch)?

RFC 6902 defines a format for describing changes to a JSON document:

```json
[
  { "op": "add", "path": "/pages/0/visuals/-", "value": { "id": "v4", ... } },
  { "op": "remove", "path": "/pages/0/visuals/2" },
  { "op": "replace", "path": "/pages/0/visuals/0/x", "value": 100 },
  { "op": "move", "from": "/pages/0/visuals/1", "path": "/pages/0/visuals/0" }
]
```

Six operations: `add`, `remove`, `replace`, `move`, `copy`, `test`. The `path`
uses JSON Pointer (RFC 6901) syntax. The `fast-json-patch` npm library computes
patches by diffing two JSON objects.

---

## Strengths

- **Pixel-perfect control** — the canvas can reproduce any dashboard design
- **JSON Patch undo/redo** — one mechanism for all operations, no Command
  pattern boilerplate
- **JSON Schema-driven properties** — visual authors declare properties once;
  the UI is generated automatically
- **Wells system** — clear contract between visual type and data binding
- **dnd-kit** — accessible drag-and-drop with keyboard support

## Weaknesses & Risks

- **No responsive reflow** — dashboards designed at 1760×990 scale down on
  smaller screens but do not rearrange. Users who need phone layouts must design
  a separate report.
- **Canvas performance with many visuals** — 30+ absolutely-positioned divs
  with real-time charts can strain the browser. React's reconciliation may
  become a bottleneck.
- **Snap-to-grid is 8px only** — some users will want finer control (1px) or
  coarser (32px). The grid size should be configurable but is not yet.
- **Copy/paste is internal only** — you cannot copy a visual from one report to
  another (yet). Cross-report copy requires serialising the visual + its field
  bindings + resolving against the target dataset.
- **Complex interaction configuration** — for a dashboard with 12 visuals, the
  user may need to configure 12×11=132 interaction pairs. We default to
  cross-filter and let users disable specific pairs.

---

## For Agents

1. Designer components live in `web/src/designer/`. The page is `DesignerPage.tsx`.
   Wells are listed in `catalog.ts`. A dataset payload is adapted in `model.ts`.
   `query.ts` builds the semantic query. `render.ts` turns a DSR into a chart model.
2. State is in `web/src/designer/store.ts` (Zustand). Document edits go through
   that store so `history.ts` can record one JSON patch per commit.
3. Undo/redo uses `fast-json-patch`. Pointer moves update a local drag preview.
   The patch is recorded when the pointer goes up. Ctrl+Z and Ctrl+Y call the store.
4. The report definition TypeScript types are in `web/src/types/report.ts`.
   Keep them in sync with the server's validation.
5. When adding a new visual type, register it in `web/src/visuals/registry.ts`
   with its well definitions and property schema. The designer picks it up
   automatically.
6. Accessibility: every interactive element must be keyboard-reachable. Use
   dnd-kit's keyboard sensors, not custom keyboard handlers.

---

## Further Reading

- [dnd-kit documentation](https://docs.dndkit.com/)
- [Zustand documentation](https://docs.pmnd.rs/zustand/)
- [JSON Patch (RFC 6902)](https://datatracker.ietf.org/doc/html/rfc6902)
- [fast-json-patch npm](https://github.com/Starcounter-Jack/JSON-Patch)
- [Power BI canvas layout guide](https://learn.microsoft.com/en-us/power-bi/create-reports/)
- [Smart guides in design tools](https://figma.com/blog/behind-the-feature-smart-guides/)
- [CSS transform: scale() for responsive canvases](https://developer.mozilla.org/en-US/docs/Web/CSS/transform-function/scale)
