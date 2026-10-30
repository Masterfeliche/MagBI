# 08 — Visuals & ECharts

> **Status: Planned**

---

## What It Does

The visuals layer is what the user actually sees — charts, tables, cards, and
slicers rendered on the report canvas. Each visual receives data from the query
engine and renders it using a combination of ECharts (for charts), TanStack
Table (for tabular visuals), and plain HTML/CSS (for cards and slicers).

MagBI ships 14 visual types:

| # | Visual | Rendering Engine | Category |
|---|--------|-----------------|----------|
| 1 | Bar chart (clustered / stacked) | ECharts | Comparison |
| 2 | Line chart (line / area) | ECharts | Trend |
| 3 | Pie chart (pie / donut) | ECharts | Composition |
| 4 | Scatter / bubble chart | ECharts | Correlation |
| 5 | Treemap | ECharts | Hierarchy |
| 6 | Funnel | ECharts | Process |
| 7 | Gauge / speedometer | ECharts | KPI |
| 8 | Waterfall | ECharts | Variance |
| 9 | Map (geographic) | ECharts geo | Spatial |
| 10 | Card / KPI tile | HTML / CSS | Single value |
| 11 | Slicer | HTML / CSS | Filter control |
| 12 | Table (flat) | TanStack Table | Detail |
| 13 | Matrix (pivot) | TanStack Table | Cross-tab |
| 14 | Multi-row card | HTML / CSS | Multiple values |

### Why three rendering engines?

Each engine is best at what it does:

- **ECharts** excels at charts with axes, legends, tooltips, animations, and
  zoom. You hand it a JSON configuration object and it draws the chart. Trying
  to build a flat data table in ECharts would be fighting the library.
- **TanStack Table** is a headless table library — it handles sorting, column
  resizing, virtualization, and grouping. Rendering a 10,000-row table in
  ECharts would be impractical; TanStack Table virtualizes the DOM so only
  visible rows exist.
- **HTML/CSS** is the right tool for cards and slicers — simple layouts that
  display a number, a label, and maybe a sparkline. No charting library needed.

---

## Why This Approach

### Why ECharts over alternatives

| Library | Strengths | Why rejected |
|---------|-----------|-------------|
| **D3.js** | Maximum flexibility, bindable to any SVG/Canvas primitive | You build everything from scratch. A bar chart is 50+ lines. For 14 visual types, D3 would multiply development time 5x. D3 is a toolkit, not a chart library. |
| **Chart.js** | Simple, lightweight, good defaults | Limited chart types (no treemap, funnel, waterfall, gauge). Limited animation and interaction. |
| **Recharts** | React-native, declarative, uses D3 under the hood | Narrower chart type coverage, fewer configuration options, less mature than ECharts. |
| **Plotly** | Feature-rich, great for notebooks | Very heavy bundle (>3MB), opinionated layout engine fights our free-form canvas, Python-centric ecosystem. |
| **Highcharts** | Polished, enterprise-grade | Commercial license required for non-personal use. ECharts is Apache 2.0. |
| **ECharts** | **Chosen** | Declarative JSON API covers all 14 chart types. Apache 2.0 license. 50k+ GitHub stars. Canvas + SVG rendering. Built-in tooltips, legends, zoom, brush. Active Apache project. |

The decisive factor: **ECharts' option API**. Every chart is a function:

```typescript
(data: unknown[], bindings: WellBinding[]) => EChartsOption
```

Pass the option object to `chart.setOption(option)`, and ECharts renders it.
No imperative drawing commands, no bindable selections, no SVG path
calculations. This is exactly what a BI tool needs — the visual type defines
how to map data and bindings to the option object.

---

## How It Works

### The VisualDefinition Registry

Every visual type registers itself in a central registry:

```typescript
interface VisualDefinition {
  type: string;            // "barChart", "lineChart", etc.
  displayName: string;     // "Bar Chart"
  icon: string;            // SVG icon for the visual picker
  wells: WellDefinition[]; // What fields the visual accepts
  buildOption: (data: DSR, bindings: Record<string, FieldBinding[]>) => EChartsOption;
}
```

The `wells` array defines what the visual needs:

```typescript
// Bar chart wells
[
  { name: "axis",   displayName: "Axis",   type: "grouping", min: 1, max: 1 },
  { name: "values", displayName: "Values", type: "measure",  min: 1, max: 10 },
  { name: "legend", displayName: "Legend", type: "grouping", min: 0, max: 1 },
]
```

When the user drags a field onto a well, the designer:
1. Updates the report definition JSON
2. Builds a SemanticQuery from the well bindings
3. Sends the query to the engine
4. Passes the result (DSR) and bindings to `buildOption()`
5. Calls `chart.setOption(option)` to render

### The ECharts Option API

An ECharts chart is a JSON object called an "option." Here is a bar chart:

```json
{
  "xAxis": {
    "type": "category",
    "data": ["Q1", "Q2", "Q3", "Q4"]
  },
  "yAxis": {
    "type": "value"
  },
  "series": [{
    "type": "bar",
    "data": [120, 200, 150, 80]
  }]
}
```

Pass this to `chart.setOption(option)` and ECharts renders a bar chart with
four bars. The option object is the **contract** between MagBI's data layer
and ECharts' rendering engine.

For MagBI, we use ECharts' more powerful **dataset/encode** model instead of
inline data:

```json
{
  "dataset": {
    "source": [
      ["Quarter", "Revenue", "Cost"],
      ["Q1", 120, 80],
      ["Q2", 200, 130],
      ["Q3", 150, 100],
      ["Q4", 80, 60]
    ]
  },
  "xAxis": { "type": "category" },
  "yAxis": {},
  "series": [
    { "type": "bar", "encode": { "x": "Quarter", "y": "Revenue" } },
    { "type": "bar", "encode": { "x": "Quarter", "y": "Cost" } }
  ]
}
```

The dataset/encode model decouples data from visual mapping. The same dataset
can drive multiple series — and the mapping from well bindings to encode
properties is mechanical.

### Canvas vs. SVG Rendering

ECharts supports two rendering backends:

| Backend | When to use | Trade-offs |
|---------|------------|------------|
| **Canvas** (default) | Most charts, especially with many data points | Fast drawing, small DOM, but no individual element events. Screenshots work via `toDataURL()`. |
| **SVG** | Exporting to PDF/print, accessibility tools that read the DOM | Slower for >10k points, larger DOM, but each element is inspectable. |

MagBI defaults to Canvas for performance and switches to SVG for export.

### Cross-Filtering Wiring

Cross-filtering is the interaction pattern where clicking one visual filters
all others on the page. Here is how it flows:

```
1. User clicks "Q3" bar in the revenue chart
2. BarChart component captures the ECharts click event
3. It emits a CrossFilterEvent: { table: "Calendar", column: "Quarter", values: ["Q3"] }
4. The designer's interaction manager receives the event
5. For each OTHER visual on the page:
   a. Check the interaction config (crossFilter / crossHighlight / none)
   b. If crossFilter: add the filter to that visual's query and re-execute
   c. If crossHighlight: send a highlight command (dims unmatched series)
   d. If none: do nothing
6. Filtered visuals re-render with updated data
```

The interaction config is per visual pair — the report author can set whether
Visual A cross-filters Visual B, cross-highlights it, or has no effect.

### How each visual type builds its option

**Bar chart:** Maps the axis well to `xAxis.type: "category"`, each measure in
the values well becomes a series of type `"bar"`. If a legend field is present,
the data is pivoted so each legend value becomes a separate series.

**Line chart:** Same structure as bar, but series type is `"line"`. Area fill
is controlled by the `areaStyle` property.

**Pie chart:** The grouping well maps to pie segment labels. The measure well
maps to segment values. Uses `series[0].type: "pie"`. Donut mode sets
`radius: ["40%", "70%"]`.

**Waterfall:** Uses ECharts' stacked bar trick — an invisible "base" series
positions each bar at its starting value, and a visible series draws the delta.
Positive deltas are one color, negative another.

**Card:** Pure HTML/CSS. Queries a single measure, renders the value in large
text with an optional trend sparkline (a tiny ECharts line chart with no axes).

**Table/Matrix:** TanStack Table handles column definitions, sorting, and
virtualization. The DSR columns map to TanStack column definitions. Matrix adds
row grouping and column pivoting via TanStack's grouping API.

**Slicer:** Queries distinct values for a dimension column. Renders them as a
dropdown, checkbox list, or range slider. User selections become filters that
are applied to all other visuals.

---

## Key Concepts

### Declarative vs. imperative charting

**Imperative** (D3 style):
```javascript
svg.selectAll("rect")
   .data(data)
   .join("rect")
   .attr("x", d => xScale(d.category))
   .attr("y", d => yScale(d.value))
   .attr("width", xScale.bandwidth())
   .attr("height", d => height - yScale(d.value));
```

**Declarative** (ECharts style):
```javascript
chart.setOption({
  xAxis: { type: "category", data: categories },
  series: [{ type: "bar", data: values }]
});
```

The imperative approach gives you pixel-level control. The declarative approach
gives you productivity. For a BI tool with 14 visual types, each of which must
handle theming, tooltips, legends, animations, and responsiveness, declarative
wins by a wide margin. We trade customisation ceiling for development speed.

### The dataset/encode pattern

ECharts supports two ways to provide data:

1. **Inline data:** Each series carries its own data array. Simple, but
   duplicates data across series and makes data transformations harder.
2. **Dataset/encode:** A single `dataset.source` holds all the data (like a
   table). Each series uses `encode` to specify which columns map to which axes.
   This mirrors how BI data works — one query result, multiple visual mappings.

MagBI uses dataset/encode exclusively because:
- The DSR (DataShapeResult) from the query engine is already a table
- Multiple series naturally share the same data
- ECharts can even do built-in transforms (filter, sort) on the dataset

### Virtual DOM and chart rendering

React re-renders components when state changes. If a chart component re-renders,
should ECharts redraw? No — ECharts manages its own canvas. The pattern:

1. The React component holds a `ref` to the ECharts instance
2. When data or options change, the component calls `chart.setOption(newOption)`
3. ECharts diffs the new option against the current one and applies minimal
   updates (it has its own internal diffing, separate from React's virtual DOM)
4. Animations handle transitions between old and new data

This means ECharts and React do not fight — React manages the component tree,
ECharts manages the chart pixels.

### Responsive visuals

Each visual lives in a resizable container on the canvas. When the user resizes
the container:

1. A ResizeObserver detects the new dimensions
2. The visual calls `chart.resize()` which tells ECharts the new canvas size
3. ECharts recalculates layout (axis positions, label placement, legend position)
4. The chart redraws at the new size

This is "responsive within bounds" — the visual adapts to its container, but
the container's position on the canvas is absolute. True responsive layout
(reflowing visuals to different screen sizes) is a future feature.

---

## Theming

MagBI has a four-level theming hierarchy:

```
Level 1: Built-in defaults (ECharts' default theme)
  └── Level 2: MagBI base theme (the product's standard look)
       └── Level 3: Workspace/report theme (customer branding)
            └── Level 4: Per-visual overrides (one visual's custom colors)
```

Each level overrides the one above it. The merging is deep — a per-visual
override that sets `series[0].color` does not wipe out the base theme's font
settings.

**MagBI theme tokens → ECharts theme:**

MagBI defines a theme as a set of tokens:

```typescript
interface ThemeOverrides {
  colors?: string[];    // Categorical palette
  font?: string;        // Font family
  background?: string;  // Chart background color
}
```

These map to an ECharts theme object:

```javascript
{
  color: theme.colors,                    // Series colors
  textStyle: { fontFamily: theme.font },  // Global font
  backgroundColor: theme.background,      // Chart background
  // ... 50+ more properties derived from the tokens
}
```

The theme is registered with `echarts.registerTheme("magbi", themeObject)` and
applied when creating the chart instance: `echarts.init(dom, "magbi")`.

---

## Accessibility

BI dashboards are often projected on screens or shared as screenshots, so
accessibility is about more than screen readers:

1. **Legends always present** for >= 2 series — identity is never color-alone
2. **Tooltips on every chart** — hover reveals exact values
3. **Table view fallback** — every chart can be switched to a data table
4. **Sufficient color contrast** — the palette is validated against WCAG 2.1
5. **Keyboard navigation** — Tab moves between visuals, Enter activates
   cross-filter, Escape clears filters

---

## Performance Considerations

### Many data points

A scatter plot with 50,000 points:
- **Canvas rendering** handles this well — ECharts batches draw calls
- **SVG rendering** would create 50,000 DOM elements — unusable
- **Progressive rendering** (`large: true` in ECharts) enables chunked drawing
  for very large datasets

### Many visuals on one page

A dashboard with 20 visuals means 20 ECharts instances, 20 canvas elements,
and 20 concurrent queries. Mitigations:
- **Lazy rendering** — only render visuals in the viewport (IntersectionObserver)
- **Query batching** — send multiple queries in one request
- **Shared dataset** — if multiple visuals query the same data, reuse the result

### Animation cost

ECharts animations (bars growing, lines drawing) are smooth but cost CPU. For
dashboards that auto-refresh every 30 seconds, we disable animations after the
first render to avoid constant re-animation.

---

## Strengths

- **One API for all chart types** — every chart is `setOption(json)`, no
  per-type rendering code beyond the option builder
- **Built-in interactivity** — tooltips, legends, zoom, brush selection come
  free with ECharts
- **Canvas + SVG** — fast rendering for viewing, crisp rendering for export
- **Declarative theming** — register a theme once, all charts use it
- **Active ecosystem** — ECharts is an Apache project with regular releases

## Weaknesses & Risks

- **Customisation ceiling** — if a visual needs something ECharts cannot express
  in its option API, we must write a custom series (rare but very complex)
- **Bundle size** — ECharts is ~800KB minified. Tree-shaking helps (import only
  `BarChart`, `LineChart`, etc.) but the core is still large
- **Two rendering worlds** — ECharts manages its own canvas, React manages the
  DOM. Coordinating the two (click events, resize, disposal) requires careful
  lifecycle management
- **No built-in accessibility** — ECharts does not produce ARIA attributes.
  The table view fallback and our own keyboard handlers are the accessibility
  story
- **Learning curve** — ECharts' option API is powerful but the documentation is
  extensive and sometimes hard to navigate. New developers need time to learn
  which options exist and how they compose

---

## For Agents

1. Visual components live in `web/src/visuals/`. One file per visual type.
2. Every visual must register itself in `registry.ts` with its VisualDefinition.
3. The `buildOption` function is the heart of each visual — it converts DSR data
   and well bindings into an ECharts option object. Keep this function pure (no
   side effects, no DOM access).
4. Use the dataset/encode model, not inline data in series.
5. Always call `chart.dispose()` in the React component's cleanup function to
   prevent memory leaks.
6. Test option builders with snapshot tests — given known DSR data and bindings,
   the option output should be deterministic.
7. When adding a new visual type:
   - Create the component in `web/src/visuals/`
   - Register it in `registry.ts`
   - Define its wells (what fields it accepts)
   - Implement `buildOption`
   - Update this chapter

---

## Further Reading

- [ECharts Configuration Handbook](https://apache.github.io/echarts-handbook/)
- [ECharts Option API Reference](https://echarts.apache.org/en/option.html)
- [ECharts Dataset Tutorial](https://echarts.apache.org/handbook/en/concepts/dataset/)
- [TanStack Table Documentation](https://tanstack.com/table/latest)
- [Canvas vs. SVG Performance](https://css-tricks.com/when-to-use-svg-vs-when-to-use-canvas/)
- [WCAG 2.1 — Use of Color](https://www.w3.org/WAI/WCAG21/Understanding/use-of-color.html)
