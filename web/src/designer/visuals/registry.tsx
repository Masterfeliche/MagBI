/** Visual renderer registry — maps RenderModel.kind to React components. */

import ReactECharts from "echarts-for-react";

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
  onCategory?: (category: string) => void;
}

export function VisualRenderer({ model, title, color, onCategory }: RendererProps) {
  switch (model.kind) {
    case "note":
      return <NoteView model={model} title={title} />;
    case "card":
      return (
        <div className="card-value">
          {title && <span className="visual-label">{title}</span>}
          {model.value}
        </div>
      );
    case "cartesian":
      return <CartesianChart model={model} title={title} color={color} onCategory={onCategory} />;
    case "pie":
      return <PieChart model={model} title={title} onCategory={onCategory} />;
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
  onCategory,
}: {
  model: CartesianModel;
  title: string;
  color: string;
  onCategory?: (category: string) => void;
}) {
  const horizontal = model.orientation === "bar";
  const option = {
    color: [color, ...PALETTE.slice(1)],
    title: titleOption(title),
    tooltip: { trigger: "axis" as const },
    grid: { left: 48, right: 16, top: title ? 36 : 16, bottom: 32 },
    xAxis: horizontal ? { type: "value" as const } : { type: "category" as const, data: model.categories },
    yAxis: horizontal ? { type: "category" as const, data: model.categories } : { type: "value" as const },
    series: model.series.map((s) => ({
      type: model.orientation === "line" ? ("line" as const) : ("bar" as const),
      name: s.name,
      data: s.values,
    })),
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (p: { name?: string }) => { if (p.name && onCategory) onCategory(p.name); } }}
    />
  );
}

function PieChart({
  model,
  title,
  onCategory,
}: {
  model: PieModel;
  title: string;
  onCategory?: (category: string) => void;
}) {
  const option = {
    color: PALETTE,
    title: titleOption(title),
    tooltip: { trigger: "item" as const },
    series: [{ type: "pie" as const, radius: "70%", data: model.slices }],
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
