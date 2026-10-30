# Visuals library analysis — Apache ECharts for v2

A deep look at ECharts as the charting engine for our BI product: what it gives
us, what it doesn't, how every Power BI visual maps onto it, and why it's the
right pick over Highcharts, Plotly, D3 and the rest.

| | |
|---|---|
| Written | 29 October 2026 |
| Library | Apache ECharts 6.1.0 (Apache-2.0) |
| Context | v2 BI engine — ~12 visual types, designer + viewer, ERP embed |

---

## Contents

1. [Why ECharts](#1-why-echarts)
2. [ECharts architecture in one picture](#2-echarts-architecture-in-one-picture)
3. [Every Power BI visual mapped to ECharts](#3-every-power-bi-visual-mapped-to-echarts)
4. [What ECharts does not give us](#4-what-echarts-does-not-give-us)
5. [The visual wrapper contract](#5-the-visual-wrapper-contract)
6. [Interaction: cross-filter, drill, selection](#6-interaction-cross-filter-drill-selection)
7. [Theming](#7-theming)
8. [Performance](#8-performance)
9. [Alternatives compared](#9-alternatives-compared)
10. [Build vs assemble decision](#10-build-vs-assemble-decision)
11. [Implementation plan](#11-implementation-plan)

---

## 1. Why ECharts

| Criterion | ECharts | Notes |
|---|---|---|
| **Licence** | Apache-2.0 | Free for commercial, no per-seat, no "contact sales" |
| **Visual coverage** | ~40 series types built in | Covers every Power BI visual MSD uses except KPI card, matrix and slicer |
| **Rendering** | Canvas (default) + SVG fallback | Canvas handles 10k+ data points; SVG for small charts that need DOM events |
| **Bundle size** | 1 MB full / ~400 KB tree-shaken + gzip ~130 KB | One library, no per-chart imports needed (but available) |
| **Theming** | JSON theme registration, design tokens in v6, runtime dark/light switch | Maps directly to our "ERP Native" theme |
| **Dataset & transforms** | Built-in `dataset` component with filter/sort transforms | Server sends one dataset, ECharts can slice it client-side |
| **Interaction** | `dataZoom`, brush, tooltip, events, `echarts.connect()` | Building blocks for cross-filter |
| **Custom series** | v6 registerable custom series via npm (`@echarts-x/*`) | Our KPI card, bullet chart, waterfall wrapper ship as custom series |
| **Community** | 63k+ GitHub stars, Apache Foundation, used in Superset, Grafana, Alibaba, Baidu | Not a small project that might go away |
| **React wrapper** | `echarts-for-react` 3.0.6 (MIT) | Handles init/dispose/resize; thin enough to replace if needed |
| **TypeScript** | Full type definitions | |

The short version: ECharts is the closest open-source equivalent to Power BI's
visual runtime — canvas-rendered, declarative (JSON options), dataset-aware,
with built-in interaction primitives. It doesn't have a BI-specific layer
(semantic queries, field wells, cross-filter orchestration), but that's our job.

---

## 2. ECharts architecture in one picture

```
 Developer / our visual wrapper
┌────────────────────────────────────────────────────────────────────────┐
│  option = {                                                            │
│    dataset: { source: [...] },         ← data from our query engine    │
│    xAxis: { type: 'category' },                                       │
│    yAxis: { type: 'value' },                                          │
│    series: [{ type: 'bar', encode: { x: 'Month', y: 'Trips' } }],    │
│    tooltip: { trigger: 'axis' },                                      │
│    dataZoom: [{ type: 'slider' }],                                    │
│  }                                                                     │
└────────────────────┬───────────────────────────────────────────────────┘
                     │ chart.setOption(option)
                     ▼
 ECharts core
┌────────────────────────────────────────────────────────────────────────┐
│  Option manager       merge + validate options                         │
│  Data pipeline        dataset → transform → series data                │
│  Component model      axis, tooltip, legend, dataZoom, brush, …        │
│  Layout engine        grid, polar, geo, calendar, matrix (v6)          │
│  Series renderers     bar, line, pie, scatter, tree, sankey, …         │
│  Animation engine     morph transitions between states                 │
│  Event system         click, mouseover, brush, dataZoom, legendSelect  │
└────────────────────┬───────────────────────────────────────────────────┘
                     │
                     ▼
 zrender (rendering layer)
┌────────────────────────────────────────────────────────────────────────┐
│  Shape primitives    rect, circle, arc, path, text, image, group       │
│  Canvas painter      default — fast, GPU-composited                    │
│  SVG painter         opt-in — DOM access, CSS styling, SSR             │
│  Event handling      hit-test on canvas shapes (no DOM per element)    │
│  Animation           interpolation, easing, morph                      │
└────────────────────────────────────────────────────────────────────────┘
```

Key insight: ECharts is **declarative**. We build a JSON `option` object and
call `setOption()`. ECharts diffs it against the previous state and transitions
smoothly. This is exactly the model our visual wrappers need: the query engine
returns data, the wrapper builds `option`, ECharts renders. No imperative
drawing code.

---

## 3. Every Power BI visual mapped to ECharts

### 3.1 Direct matches (ECharts series type exists)

| Power BI visual | ECharts series | Notes |
|---|---|---|
| **Clustered bar** | `type: 'bar'` | Horizontal: swap x/y axes |
| **Stacked bar** | `type: 'bar'` + `stack: 'total'` | 100%: normalise in data or use dataset transform |
| **Clustered column** | `type: 'bar'` (vertical is default) | |
| **Stacked column** | `type: 'bar'` + `stack` | |
| **Line** | `type: 'line'` | Multiple series, smooth, step, area fill |
| **Area** | `type: 'line'` + `areaStyle: {}` | Stacked area: add `stack` |
| **Combo (line + column)** | Mixed series: one `bar` + one `line` on same grid | Different y-axis indices if needed (but we avoid dual axis) |
| **Pie** | `type: 'pie'` | |
| **Donut** | `type: 'pie'` + `radius: ['40%', '70%']` | Centre label via `graphic` component |
| **Scatter** | `type: 'scatter'` | Size encoding via `symbolSize` callback |
| **Treemap** | `type: 'treemap'` | Built in, with drill-down |
| **Funnel** | `type: 'funnel'` | |
| **Gauge** | `type: 'gauge'` | Highly customisable (pointer, progress arc, axis labels) |
| **Map (filled)** | `type: 'map'` or GeoJSON + `visualMap` | Choropleth; we'll use Leaflet for interactive maps instead |
| **Sankey** | `type: 'sankey'` | |
| **Radar** | `type: 'radar'` | |
| **Heatmap** | `type: 'heatmap'` | On grid or calendar coordinate |
| **Boxplot** | `type: 'boxplot'` | With dataset transform for auto quartiles |

### 3.2 Built with ECharts features (no native series, but straightforward)

| Power BI visual | ECharts approach | Complexity |
|---|---|---|
| **Waterfall** | Stacked bar with invisible base segment | Low — [documented pattern in ECharts handbook](https://echarts.apache.org/handbook/en/how-to/chart-types/bar/waterfall). Our wrapper computes running totals and the invisible segment |
| **Bullet** | Overlapping bars (`barGap: '-100%'`) + `markLine` for target | Medium — two series: a wide pale bar (range) and a narrow solid bar (actual), plus a line marker for target |
| **Sparkline** (inside a KPI card) | Tiny `line` chart with no axes, no tooltip, minimal config | Low |
| **100% stacked bar** | `bar` + `stack` + dataset transform that normalises to percentages | Low |
| **Ribbon / range area** | Custom series or two stacked areas with bottom one transparent | Medium |

### 3.3 Not a chart — built as HTML/CSS components

| Power BI visual | v2 approach | Why not ECharts |
|---|---|---|
| **Card (single number)** | React component: big number + delta + optional sparkline (ECharts) | A number isn't a chart; HTML gives us `clamp()`, ellipsis, and the ERP's typography |
| **Multi-row card / KPI row** | CSS grid of card components | Same reason |
| **Table** | TanStack Table (virtualised, sortable, resizable columns) | ECharts has no table. Tables need column resize, pagination, conditional formatting, data bars — all DOM |
| **Matrix (pivot)** | TanStack Table with grouped rows/columns + subtotals | Same |
| **Slicer** | React component: checkbox list, dropdown, date range picker, numeric range | Slicers are form controls, not charts |
| **Text box** | `<div contenteditable>` or rich text component | |
| **Image** | `<img>` | |
| **Button** | `<button>` with navigation action | |
| **Shape** | CSS or inline SVG | |

### 3.4 Coverage summary

| Category | Count | How |
|---|---|---|
| Direct ECharts series | 17 | `setOption()` with the right type |
| ECharts patterns (wrapper computes data) | 5 | Waterfall, bullet, sparkline, 100% stacked, range area |
| HTML/CSS components | 9 | Card, KPI, table, matrix, slicer, text, image, button, shape |
| **Total MVP visuals** | **~20** | More than the ~12 Power BI types MSD uses |

ECharts 6's custom series system (`@echarts-x/*`) lets us package waterfall
and bullet as reusable npm modules if we want, but the stacked-bar and
overlapping-bar patterns are simpler and well-documented.

---

## 4. What ECharts does not give us

These are gaps we fill in our wrapper/framework layer:

| Gap | What Power BI does | What we build |
|---|---|---|
| **Cross-filtering** | Clicking a bar filters every other visual's query | Event handler → update shared filter state → re-query each visual. ECharts gives us the click events and `echarts.connect()` for linked tooltips; the filter logic is ours |
| **Semantic query** | A visual asks for `[Trips] by [Month]` | Our visual definition's `toQuery()` method builds the semantic query from the field wells; ECharts never sees measure names |
| **Field wells** | Drag "Month" onto X-axis, "Trips" onto Values | React UI above ECharts; the wrapper translates wells → `encode` + `dataset` |
| **Format pane** | Per-visual formatting (title, colours, labels, axes) | Generated from a JSON schema per visual type; writes into the ECharts `option` |
| **Conditional formatting** | Colour a bar by a rule (red if < target) | `itemStyle.color` callback or `visualMap` component — both built into ECharts, but the rules come from our format model |
| **Data reduction** | Top N categories, max points on a line | Applied by the query engine (server-side `LIMIT`), not ECharts |
| **Totals row in a table** | Pinned footer row with re-aggregated totals | TanStack Table feature + query engine returning totals |
| **Responsive / fit-to-page** | Report scales to fit the container | CSS scaling on the page container + `chart.resize()` on the ECharts instances |
| **Accessibility** | Keyboard nav, screen reader | ECharts has `aria` option (auto-generates `aria-label` from data). We add keyboard focus and tab order across visuals |
| **Data bars in table cells** | Mini inline bars inside a table column | Inline `<div>` with percentage width — pure CSS, not ECharts |
| **Print / PDF** | Export a page as PDF | `chart.getDataURL()` gives a PNG; compose into a PDF with the page layout |

**None of these gaps are reasons to pick a different library.** Every charting
library has the same gaps — they're charting libraries, not BI frameworks.
Highcharts, Plotly and D3 all need the same wrapper work. ECharts is the one
that needs the *least* wrapper work because its `dataset`, `encode`, `dataZoom`,
`brush` and event system are designed for dashboard use.

---

## 5. The visual wrapper contract

Every visual in v2 is a TypeScript module that bridges our BI model and
ECharts:

```typescript
// visuals/bar/definition.ts
import type { VisualDefinition, WellSpec, SemanticQuery, VisualHandle } from '../types';

export const barChart: VisualDefinition = {
  type: 'barChart',
  label: 'Bar chart',
  icon: 'chart-bar',

  wells: [
    { id: 'category', label: 'Axis',    accepts: ['string', 'date'], max: 1, required: true },
    { id: 'values',   label: 'Values',  accepts: ['measure'],        max: 5, required: true },
    { id: 'legend',   label: 'Legend',   accepts: ['string'],         max: 1 },
    { id: 'tooltips', label: 'Tooltips', accepts: ['measure'],        max: 3 },
  ],

  // JSON schema for the Format pane — drives the UI automatically
  formatSchema: {
    type: 'object',
    properties: {
      title:      { type: 'object', properties: { show: { type: 'boolean' }, text: { type: 'string' } } },
      dataLabels: { type: 'object', properties: { show: { type: 'boolean' }, position: { enum: ['outside', 'inside'] } } },
      legend:     { type: 'object', properties: { show: { type: 'boolean' }, position: { enum: ['top', 'bottom', 'right'] } } },
      orientation:{ enum: ['vertical', 'horizontal'] },
      stacking:   { enum: ['none', 'stacked', 'stacked100'] },
    }
  },

  // Translate well bindings into a semantic query for the engine
  toQuery(wells, pageFilters, reportFilters): SemanticQuery {
    return {
      groupBy: [
        wells.category[0],
        ...(wells.legend || []),
      ],
      measures: [
        ...wells.values,
        ...(wells.tooltips || []),
      ],
      filters: [...pageFilters, ...reportFilters],
    };
  },

  // Render the chart — called on mount and on data change
  render(el, data, format, theme, events): VisualHandle {
    const chart = echarts.init(el, theme.echartsThemeName, { renderer: 'canvas' });

    const option: echarts.EChartsOption = {
      dataset: { source: data.rows, dimensions: data.columns.map(c => c.name) },
      xAxis: format.orientation === 'horizontal'
        ? { type: 'value' }
        : { type: 'category', data: undefined /* from dataset */ },
      yAxis: format.orientation === 'horizontal'
        ? { type: 'category' }
        : { type: 'value' },
      series: buildSeries(data, format, wells),
      tooltip: { trigger: 'axis', confine: true },
      legend: format.legend?.show !== false ? { top: 'top' } : { show: false },
      grid: { containLabel: true, left: 12, right: 12, top: 40, bottom: 12 },
    };

    chart.setOption(option);

    // Cross-filter: on click, emit the clicked category value
    chart.on('click', (params) => {
      if (params.componentType === 'series') {
        events.onCrossFilter({
          column: wells.category[0],
          value: params.name,
        });
      }
    });

    return {
      resize: () => chart.resize(),
      update: (newData, newFormat) => chart.setOption(buildOption(newData, newFormat)),
      getImage: () => chart.getDataURL({ type: 'png', pixelRatio: 2 }),
      dispose: () => chart.dispose(),
    };
  },
};
```

The pattern is the same for every visual:
1. **Wells** declare what can be dropped where.
2. **`toQuery()`** turns wells into a semantic query — no SQL, no ECharts.
3. **`render()`** turns query results into an ECharts `option`.
4. **Events** bubble up to the dashboard's filter state.

---

## 6. Interaction: cross-filter, drill, selection

### Cross-filter

Power BI's cross-filter: clicking a bar in Visual A adds a filter to every
other visual's query. ECharts doesn't do this automatically, but it gives us
the primitives:

```
User clicks a bar in Visual A (bar chart)
  │
  ▼
ECharts emits 'click' event with { name: "Operations", seriesName: "Trips" }
  │
  ▼
Visual A's wrapper calls events.onCrossFilter({ column: "Directorate", value: "Operations" })
  │
  ▼
Dashboard filter state updates: crossFilters["v_bar_1"] = { "Directorate": "Operations" }
  │
  ▼
Every OTHER visual re-runs its query with the merged filter set
  (its own wells + page filters + report filters + cross-filters from other visuals)
  │
  ▼
Each visual calls chart.setOption(newOption) — ECharts morphs smoothly
```

**`echarts.connect()`** synchronises tooltips and axis pointers across charts
on the same page, so hovering over "January" highlights January everywhere.
This is free — one line of code per dashboard.

### Drill-down on hierarchies

A bar chart bound to `Date[Year → Quarter → Month]`:

1. Initial: bars show years. The wrapper queries `groupBy: ["Date[Year]"]`.
2. Click "2026": wrapper pushes `{ "Date[Year]": 2026 }` onto the drill stack
   and queries `groupBy: ["Date[Quarter]"]` with filter `Year = 2026`.
3. Click "Q3": pushes again, queries `groupBy: ["Date[Month]"]` with filter
   `Year = 2026 AND Quarter = "Q3"`.
4. A "drill up" button pops the stack.

ECharts' `treemap` has built-in drill-down. For bar/line/pie we implement
it in the wrapper by changing the `groupBy` and re-querying.

### Brush selection

ECharts has a `brush` component that lets users drag a rectangle or lasso over
data points. We wire this to cross-filter as a set of values (for scatter) or
a range (for time axes with `dataZoom`).

---

## 7. Theming

### ECharts themes are JSON

```json
{
  "color": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  "backgroundColor": "transparent",
  "textStyle": { "fontFamily": "\"Anthropic Sans\", system-ui, sans-serif", "color": "#52514e" },
  "title": { "textStyle": { "fontWeight": 500, "fontSize": 16, "color": "#0b0b0b" } },
  "categoryAxis": {
    "axisLine": { "lineStyle": { "color": "#c3c2b7" } },
    "axisTick": { "lineStyle": { "color": "#c3c2b7" } },
    "axisLabel": { "color": "#898781" },
    "splitLine": { "lineStyle": { "color": "#e1e0d9", "type": "dashed" } }
  },
  "valueAxis": {
    "axisLine": { "show": false },
    "axisLabel": { "color": "#898781" },
    "splitLine": { "lineStyle": { "color": "#e1e0d9", "type": "dashed" } }
  },
  "bar": { "itemStyle": { "borderRadius": [4, 4, 0, 0] }, "barMaxWidth": 24 },
  "line": { "lineStyle": { "width": 2 }, "symbolSize": 8 },
  "pie": { "itemStyle": { "borderColor": "#fcfcfb", "borderWidth": 2 } }
}
```

Register once: `echarts.registerTheme('erp-native-light', lightTheme)` and
`echarts.registerTheme('erp-native-dark', darkTheme)`. Every `echarts.init()`
passes the theme name. Switching themes at runtime is one `dispose()` +
`init()` + `setOption()`.

### Mapping our design tokens to ECharts

| Our token | ECharts property | Light | Dark |
|---|---|---|---|
| Categorical palette (Cove order) | `color` array | `#2a78d6, #eb6834, …` | `#3987e5, #d95926, …` |
| `--text-primary` | `title.textStyle.color` | `#0b0b0b` | `#f0efec` |
| `--text-muted` | `axisLabel.color`, `legend.textStyle.color` | `#898781` | `#898781` |
| `--border` / gridline | `splitLine.lineStyle.color` | `#e1e0d9` | `#2c2c2a` |
| Axis baseline | `axisLine.lineStyle.color` | `#c3c2b7` | `#383835` |
| `--surface-1` | `backgroundColor` or transparent (host provides bg) | transparent | transparent |
| Bar border-radius | `bar.itemStyle.borderRadius` | `[4,4,0,0]` | same |
| Pie segment gap | `pie.itemStyle.borderColor` + `borderWidth: 2` | surface colour | surface colour |
| Status colours | Used in conditional formatting callbacks only | good/warn/serious/critical | same |

The Power BI theme (`erp-native`) becomes two ECharts themes (light + dark)
plus a CSS file for the HTML components (card, table, slicer). One source of
truth: `theme/erp-native.tokens.json`, from which both are generated.

### Mark specs enforced by the theme

| Rule | How |
|---|---|
| Bars ≤ 24px | `barMaxWidth: 24` in theme |
| 4px rounded data-end, square at baseline | `borderRadius: [4, 4, 0, 0]` (top-left, top-right, bottom-right, bottom-left) |
| Lines 2px | `lineStyle.width: 2` in theme |
| Markers ≥ 8px | `symbolSize: 8` in theme |
| 2px surface gap between segments | `borderColor: surfaceColor, borderWidth: 2` on pie/stacked bar |
| No vertical gridlines on time axis | `xAxis.splitLine.show: false` when axis is date/category |
| Text uses text tokens, not series colour | Labels use `color` from theme text tokens, not `inherit` |

**These are set in the theme and cannot be overridden from the format pane.**
An analyst can turn data labels on or off, but they cannot make bars 60px wide
or use rainbow colours. This is how the five audit scripts (`v2_series_audit.py`,
`v2_palette_sweep.py`, `v2_text_fit.py`, etc.) become unnecessary — the rules
are in the renderer, not in post-hoc checks.

---

## 8. Performance

### ECharts canvas rendering — what it handles

| Scenario | Data points | ECharts behaviour |
|---|---|---|
| Typical dashboard visual (bar/line/pie) | 10–500 | Instant; the bottleneck is the HTTP request |
| Large table/matrix | 1,000–10,000 rows | Not ECharts — TanStack Table with virtualisation |
| Dense scatter | 5,000–50,000 | Canvas handles it; enable `large: true` for GPU-accelerated rendering |
| Time series with zoom | 10,000–100,000 points | `dataZoom` with `sampling: 'lttb'` (Largest-Triangle-Three-Buckets) — renders ~1,000 visible points |
| Extreme (log/monitoring) | 100k–1M | ECharts `dataset` + `appendData` in streaming mode; not a BI use case |

For MSD's volumes (fact tables in the tens of thousands, visuals showing
aggregated results of 10–200 rows), ECharts will never be the bottleneck.

### Incremental rendering

ECharts 6 supports `progressive` rendering: it draws the first N elements,
yields to the browser, then continues. On a scatter with 50k points, this
means the chart appears immediately and fills in over ~200ms instead of
blocking for 200ms then appearing all at once.

### Memory

Each `echarts.init()` creates one canvas element and one zrender instance.
A dashboard with 8 visuals = 8 canvases. On a typical page this uses 20–40 MB.
Disposing charts on page navigation (`chart.dispose()`) frees it.

---

## 9. Alternatives compared

### 9.1 Head to head

| Criterion | ECharts 6.1 | Highcharts 13 | Plotly.js 4.1 | D3 7.9 | Chart.js 4.6 | AG Charts 14 |
|---|---|---|---|---|---|---|
| **Licence** | Apache-2.0 | Commercial (free for personal) | MIT | ISC | MIT | MIT (community) |
| **Cost for commercial** | Free | ~$500/dev/year | Free | Free | Free | Free (community) |
| **Rendering** | Canvas + SVG | SVG (+ Canvas boost module) | SVG + WebGL scatter | SVG (manual) | Canvas | Canvas |
| **Declarative API** | JSON `option` | JSON `options` | JSON `data`+`layout` | No — imperative | JSON `config` | JSON `options` |
| **Series types built in** | ~40 | ~30 | ~50 | 0 (build everything) | ~8 | ~20 |
| **Dataset component** | Yes (encode, transforms) | No (per-series data) | No | No | No (per-dataset) | No |
| **Theming** | JSON theme registration | JSON theme (limited) | `template` | CSS/manual | `defaults` | Theme API |
| **Built-in interaction** | dataZoom, brush, tooltip, events, connect | boost, events | crossfilter (basic), events | Manual | Zoom plugin, events | crosshair, events |
| **Waterfall** | Pattern (stacked bar) | Built-in series | Bar trace + base | Manual | Plugin | Built-in |
| **Gauge** | Built-in | Built-in | Indicator trace | Manual | Doughnut hack | Built-in |
| **Treemap** | Built-in | Built-in | Built-in | d3-hierarchy + manual render | No | Built-in |
| **Map/Geo** | Built-in (GeoJSON) | Built-in (with map data) | Built-in (Mapbox) | d3-geo (powerful) | No | Built-in |
| **Bundle (min+gz)** | ~130 KB | ~90 KB | ~1.1 MB | ~30 KB | ~25 KB | ~150 KB |
| **React wrapper** | echarts-for-react | Official wrapper | react-plotly.js | visx/nivo | react-chartjs-2 | Official |
| **BI product usage** | Apache Superset, Grafana | Qlik (via OEM), many SaaS | Dash (Plotly's own BI) | Observable, many bespoke | Simple dashboards | AG Grid companion |

### 9.2 Why not each alternative

**Highcharts** — The best alternative technically, with slightly more polished
defaults and a built-in waterfall series. But it costs money per developer seat,
and the OEM licence for embedding in our product is more expensive. For a product
we ship to customers, the licence model matters. ECharts does everything
Highcharts does for this use case, for free.

**Plotly.js** — Excellent for data science (Jupyter notebooks, Dash apps) and
has the most chart types (~50), but it is 1.1 MB gzipped — 8× ECharts. It uses
SVG by default, which is slower for large datasets. Its React integration
re-renders the entire chart on every prop change (no diffing like ECharts'
`setOption`). The WebGL scatter is powerful but limited to 4–8 instances per
page. And Plotly's styling is opinionated and hard to theme to match an ERP.

**D3** — The most powerful, but it's a toolkit, not a library. D3 gives you
scales, axes, shapes and layouts; *you* write the bindingcode,update pattern,
tooltips, legends, animation and accessibility. Building 20 visual types on
D3 means writing 20 renderers from scratch. ECharts is *built on top of*
this kind of rendering engine (zrender) and gives us the finished charts.
We'd use D3 only if we needed a visual that ECharts can't do at all (none so
far).

**Chart.js** — Simple, small (25 KB), great for a marketing dashboard with 3
charts. But it has only ~8 chart types, no treemap, no gauge, no sankey, no
geo, no dataset/encode concept, limited interaction. We'd outgrow it in week 2.

**AG Charts** — Good, and free in the community edition. But the community
edition deliberately omits features that steer you toward the enterprise
licence (which requires AG Grid Enterprise). ECharts' Apache-2.0 has no such
distinction. AG Charts also has a smaller community and fewer examples.

**Recharts / Nivo / visx** — React-specific wrappers around D3 or SVG. Nivo
has beautiful defaults. But they render SVG, which means DOM nodes per data
point, and they top out at ~2,000 points before the browser struggles. None
has a dataset/encode model. They're presentation libraries, not analysis
libraries.

### 9.3 The verdict

ECharts is the only library that checks every box:

- ✅ Free commercial licence (Apache-2.0)
- ✅ Canvas rendering (scales to 50k+ points)
- ✅ Declarative JSON API (option + setOption diffing)
- ✅ Dataset component with encode (our query results map directly)
- ✅ JSON theming with design tokens (v6)
- ✅ Built-in interaction primitives (dataZoom, brush, connect, events)
- ✅ ~40 series types covering all MSD visuals
- ✅ Custom series plugin system (v6, npm-based)
- ✅ Proven at scale (Superset, Grafana, Alibaba)
- ✅ Active development (v6.1 shipped May 2026)

---

## 10. Build vs assemble decision

Two approaches to the visual layer:

| Approach | What it means | Effort | Risk |
|---|---|---|---|
| **ECharts + wrappers** | One library; each visual is a thin wrapper (~100–300 lines) that maps wells/format/data to an ECharts `option`. HTML components (card, table, slicer) are standalone React. | Low–medium | Low — ECharts is proven; wrappers are testable |
| **Multiple libraries** | ECharts for charts, TanStack Table for tables, a slicer library, a KPI library, maybe Leaflet for maps. | Medium | Higher — different APIs, theming, event models to unify |
| **D3 from scratch** | Build every visual as a D3 component. Full control. | Very high | Very high — months of rendering code; reinventing what ECharts already does |
| **Custom canvas engine** | Build our own zrender equivalent. | Absurd | Don't |

**Recommendation: ECharts + wrappers + TanStack Table.**

- Charts (bar, line, pie, scatter, gauge, treemap, funnel, sankey, heatmap,
  radar, waterfall, bullet, combo, area): **ECharts** with visual wrappers.
- Tables and matrices: **TanStack Table** (virtualised, sortable, conditional
  formatting, data bars, subtotals).
- KPI cards, slicers, text, image, button, shape: **React components** with
  our theme tokens.
- Maps (if needed later): **Leaflet** with ECharts overlay for data points,
  or ECharts `geo` for simple choropleths.

This gives us one charting library to learn, theme and maintain, with the
smallest possible surface of custom rendering code.

---

## 11. Implementation plan

### Phase 2 of the v2 build (the visual layer)

| Week | Deliverable |
|---|---|
| 1 | `VisualDefinition` contract, `VisualHost` React component (handles mount/resize/dispose/re-query), ECharts theme from tokens |
| 2 | Bar/column (clustered, stacked, 100%), line/area, combo. Cross-filter wiring |
| 3 | Pie/donut, KPI card + sparkline, gauge. Format pane generated from JSON schemas |
| 4 | Table (TanStack: sort, resize, conditional format, data bars), matrix (grouped rows/columns + subtotals) |
| 5 | Slicer (list, dropdown, date range), waterfall, bullet. Drill-down on hierarchies |
| 6 | Treemap, funnel, scatter, heatmap. `echarts.connect()` for linked tooltips. Accessibility pass (`aria` option + keyboard nav) |

### What ships in each visual

Every visual wrapper includes:
- Well definitions (what can be dropped where)
- `toQuery()` → semantic query
- `render()` → ECharts option (or React component for non-chart visuals)
- Format schema → auto-generates the format pane
- Cross-filter event emission
- `getImage()` for export/print
- Empty-state rendering (no data, loading, error)
- Golden test: a fixture dataset + expected option snapshot

### File structure

```
web/src/visuals/
  types.ts                    VisualDefinition, WellSpec, VisualHandle, SemanticQuery
  registry.ts                 Map<string, VisualDefinition> — the visual palette
  VisualHost.tsx              React component: query + render + resize + error boundary
  theme/
    erp-native-light.json     ECharts theme (generated from tokens)
    erp-native-dark.json
    tokens.ts                 Design tokens as CSS variables
  charts/
    bar/         definition.ts, buildOption.ts, format.schema.json, bar.test.ts
    line/        ...
    pie/         ...
    combo/       ...
    scatter/     ...
    waterfall/   ...
    bullet/      ...
    gauge/       ...
    treemap/     ...
    funnel/      ...
    heatmap/     ...
    radar/       ...
    sankey/      ...
  components/
    card/        Card.tsx, CardSparkline.tsx, card.test.ts
    kpi-row/     KpiRow.tsx
    table/       DataTable.tsx, ConditionalFormat.tsx, DataBar.tsx
    matrix/      Matrix.tsx
    slicer/      Slicer.tsx, DateRangeSlicer.tsx, NumericSlicer.tsx
    text/        TextBox.tsx
    image/       ImageVisual.tsx
    button/      ButtonVisual.tsx
  interaction/
    FilterState.ts            Page-level filter + cross-filter + slicer state
    CrossFilter.ts            Orchestrates re-query on selection change
    DrillState.ts             Drill stack per visual
    useCrossFilter.ts         React hook
```
