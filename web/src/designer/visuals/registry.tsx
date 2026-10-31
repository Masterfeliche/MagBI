/** Visual renderer registry — maps RenderModel.kind to React components. */

import ReactECharts from "echarts-for-react";
import { useEffect, useRef, useState } from "react";

import { canvasTextWidth, fitCardFontSize } from "../cardFont";
import { cardSignColor } from "../condFormat";
import { categoryOpacity } from "../filters";
import {
  axisText,
  categoryAxisLabel,
  chartColors,
  formatMeasure,
  formatNumber,
  labelPlacement,
  legendFrom,
  markLines,
  titleFrom,
  trendValues,
  unitsFormatter,
  type FormatProps,
} from "../formatChart";
import type {
  CartesianModel,
  FunnelModel,
  GaugeModel,
  NoteModel,
  PieModel,
  RenderModel,
  ScatterModel,
  TreemapModel,
  WaterfallModel,
} from "../render";

const PALETTE = ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2", "#D9B300", "#36B37E"];

interface RendererProps {
  model: RenderModel;
  title: string;
  color: string;
  properties?: FormatProps;
  palette?: string[];
  onCategory?: (category: string) => void;
  onDrill?: (category: string) => void;
  highlightCategory?: string;
}

/** The visual's own "Whole" setting wins; otherwise the measure's format string. */
function cardText(value: unknown, format: string | null | undefined, valueFormat: unknown): string {
  if (valueFormat === "Whole") return formatNumber(value, { whole: true });
  return formatMeasure(value, format);
}

export function VisualRenderer({ model, title, color, properties, palette, onCategory, onDrill, highlightCategory }: RendererProps) {
  switch (model.kind) {
    case "note":
      return <NoteView model={model} title={title} />;
    case "card":
      return (
        <CardVisual
          title={title}
          value={cardText(model.value, model.format, properties?.valueFormat)}
          color={properties?.condFormat === "cardSign" ? cardSignColor(cardText(model.value, model.format, properties?.valueFormat)) : undefined}
        />
      );
    case "cartesian":
      return <CartesianChart model={model} title={title} color={color} properties={properties} palette={palette} onCategory={onCategory} onDrill={onDrill} highlightCategory={highlightCategory} />;
    case "pie":
      return <PieChart model={model} title={title} properties={properties} palette={palette} onCategory={onCategory} highlightCategory={highlightCategory} />;
    case "scatter":
      return <ScatterChart model={model} title={title} />;
    case "funnel":
      return <FunnelChart model={model} title={title} />;
    case "gauge":
      return <GaugeChart model={model} title={title} />;
    case "treemap":
      return <TreemapChart model={model} title={title} onCategory={onCategory} />;
    case "waterfall":
      return <WaterfallChart model={model} title={title} color={color} />;
    case "table":
      return null;
  }
}

function CardVisual({ title, value, color }: { title: string; value: string; color?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [fontSize, setFontSize] = useState(28);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = canvasTextWidth(getComputedStyle(node).fontFamily);
    const apply = () => {
      const box = node.getBoundingClientRect();
      setFontSize(fitCardFontSize(value, box.width, box.height, measure));
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(node);
    return () => observer.disconnect();
  }, [value]);

  return (
    <div className="card-value" ref={ref}>
      {title && <span className="visual-label">{title}</span>}
      <span className="card-number" style={{ fontSize, color }}>{value}</span>
    </div>
  );
}

function NoteView({ model, title }: { model: NoteModel; title: string }) {
  return (
    <div className="note">
      {title && <strong>{title}</strong>}
      <div>{model.message}</div>
    </div>
  );
}

function titleOption(title: string) {
  return title ? { text: title, left: 8, textStyle: { fontSize: 14, fontWeight: 600 } } : undefined;
}

function CartesianChart({
  model,
  title,
  color,
  properties = {},
  palette,
  onCategory,
  onDrill,
  highlightCategory,
}: {
  model: CartesianModel;
  title: string;
  color: string;
  properties?: FormatProps;
  palette?: string[];
  onCategory?: (category: string) => void;
  onDrill?: (category: string) => void;
  highlightCategory?: string;
}) {
  const horizontal = model.orientation === "bar";
  const props = { ...properties, title: properties.title || title, color: properties.color || color };
  const values = model.series[0]?.values ?? [];
  const lines = markLines(values, props);
  const format = unitsFormatter(props.yUnits);
  const valueLabel = (value: number) => formatNumber(value, { units: "auto", decimals: 0 });
  const exact = (value: number) => formatNumber(value);
  const categories = model.categories.length;
  const option = {
    color: chartColors(props, palette),
    title: titleFrom(props),
    legend: legendFrom(props),
    tooltip: {
      trigger: "axis" as const,
      extraCssText: "padding:8px 12px;border:1px solid #E0E3E8;border-radius:4px;background:#fff;",
      formatter: (params: unknown) => {
        const items = Array.isArray(params) ? params : [params];
        const index = Number((items[0] as { dataIndex?: number } | undefined)?.dataIndex ?? 0);
        const lines = items.map((item) => {
          const point = item as { seriesName?: string; value?: unknown };
          return `${point.seriesName ?? ""}: ${exact(Number(point.value))}`;
        });
        for (const extra of model.tooltips ?? []) {
          lines.push(`${extra.name}: ${extra.values[index] ?? ""}`);
        }
        return `<div>${lines.join("<br/>")}</div>`;
      },
    },
    grid: { left: 56, right: 16, top: props.title ? 36 : 16, bottom: categories > 12 ? 64 : 32 },
    xAxis: horizontal
      ? { type: "value" as const, show: props.yShow !== false, axisLabel: { formatter: format ?? valueLabel } }
      : {
          type: "category" as const,
          data: model.categories,
          axisLabel: categoryAxisLabel(categories, axisText(props.xShow, props.xFontSize, props.xColor)),
        },
    yAxis: horizontal
      ? {
          type: "category" as const,
          data: model.categories,
          axisLabel: categoryAxisLabel(categories, axisText(props.xShow, props.xFontSize, props.xColor)),
        }
      : { type: "value" as const, show: props.yShow !== false, axisLabel: { formatter: format ?? valueLabel } },
    series: [
      ...model.series.map((s) => ({
        type: model.orientation === "line" ? ("line" as const) : ("bar" as const),
        name: s.name,
        data: s.values.map((value, index) => ({
          value,
          itemStyle: {
            opacity: categoryOpacity(model.categories[index] ?? "", highlightCategory),
          },
        })),
        label: { show: props.labelsShow === true, position: labelPlacement(props.labelsPos) },
        markLine: lines.length > 0 ? { data: lines, symbol: "none" } : undefined,
      })),
      ...(props.analytics_trend
        ? [{ type: "line" as const, name: "Trend", data: trendValues(values), lineStyle: { type: "dashed" as const }, symbol: "none" }]
        : []),
    ],
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      onEvents={{
        click: (p: { name?: string }) => { if (p.name && onCategory) onCategory(p.name); },
        dblclick: (p: { name?: string }) => { if (p.name && onDrill) onDrill(p.name); },
      }}
    />
  );
}

function PieChart({
  model,
  title,
  properties = {},
  palette,
  onCategory,
  highlightCategory,
}: {
  model: PieModel;
  title: string;
  properties?: FormatProps;
  palette?: string[];
  onCategory?: (category: string) => void;
  highlightCategory?: string;
}) {
  const props = { ...properties, title: properties.title || title };
  const option = {
    color: chartColors(props, palette),
    title: titleFrom(props),
    legend: legendFrom(props),
    tooltip: { trigger: "item" as const },
    series: [{
      type: "pie" as const,
      radius: "70%",
      data: model.slices.map((slice) => ({
        ...slice,
        itemStyle: { opacity: categoryOpacity(slice.name, highlightCategory) },
      })),
    }],
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (p: { name?: string }) => { if (p.name && onCategory) onCategory(p.name); } }}
    />
  );
}

function ScatterChart({ model, title }: { model: ScatterModel; title: string }) {
  const option = {
    color: PALETTE,
    title: titleOption(title),
    tooltip: { trigger: "item" as const },
    grid: { left: 48, right: 16, top: title ? 36 : 16, bottom: 32 },
    xAxis: { type: "value" as const },
    yAxis: { type: "value" as const },
    series: model.series.map((s) => ({ type: "scatter" as const, name: s.name, data: s.data })),
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />;
}

function FunnelChart({ model, title }: { model: FunnelModel; title: string }) {
  const option = {
    color: PALETTE,
    title: titleOption(title),
    tooltip: { trigger: "item" as const },
    series: [{ type: "funnel" as const, data: model.items, left: "10%", width: "80%" }],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />;
}

function GaugeChart({ model, title }: { model: GaugeModel; title: string }) {
  const option = {
    title: titleOption(title),
    series: [{
      type: "gauge" as const,
      data: [{ value: model.value, name: model.name }],
      detail: { formatter: "{value}" },
    }],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />;
}

function TreemapChart({
  model,
  title,
  onCategory,
}: {
  model: TreemapModel;
  title: string;
  onCategory?: (category: string) => void;
}) {
  const option = {
    color: PALETTE,
    title: titleOption(title),
    tooltip: { trigger: "item" as const },
    series: [{ type: "treemap" as const, data: model.items.map((i) => ({ name: i.name, value: i.value })) }],
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (p: { name?: string }) => { if (p.name && onCategory) onCategory(p.name); } }}
    />
  );
}

function WaterfallChart({ model, title, color }: { model: WaterfallModel; title: string; color: string }) {
  let running = 0;
  const base: (number | string)[] = [];
  const positive: (number | string)[] = [];
  const negative: (number | string)[] = [];
  for (const v of model.values) {
    if (v >= 0) {
      base.push(running);
      positive.push(v);
      negative.push("-");
      running += v;
    } else {
      running += v;
      base.push(running);
      positive.push("-");
      negative.push(-v);
    }
  }
  const option = {
    title: titleOption(title),
    tooltip: { trigger: "axis" as const },
    grid: { left: 48, right: 16, top: title ? 36 : 16, bottom: 32 },
    xAxis: { type: "category" as const, data: model.categories },
    yAxis: { type: "value" as const },
    series: [
      {
        type: "bar" as const,
        stack: "wf",
        data: base,
        itemStyle: { color: "transparent" },
        emphasis: { itemStyle: { color: "transparent" } },
      },
      { type: "bar" as const, stack: "wf", name: "Increase", data: positive, itemStyle: { color: color || "#118DFF" } },
      { type: "bar" as const, stack: "wf", name: "Decrease", data: negative, itemStyle: { color: "#E66C37" } },
    ],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />;
}
