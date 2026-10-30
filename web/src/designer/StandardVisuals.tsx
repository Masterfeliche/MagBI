/** KPI, chain, donut, Pareto, heat matrix, and the page header. */

import ReactECharts from "echarts-for-react";

import type { CartesianModel, PieModel, TableModel } from "./render";
import { ERP_NATIVE, formatDate, isNoDataLabel, statusOf } from "./standard";

export function HeaderVisual({ properties }: { properties: Record<string, unknown> }) {
  const text = (key: string, fallback = "") => (typeof properties[key] === "string" ? properties[key] : fallback);
  return (
    <div className="dash-header">
      <div>
        <div className="dash-crumb">{text("breadcrumb", "Warehouse / Stock and expiry")}</div>
        <div className="dash-title">{text("title", "Stock & Expiry")}</div>
        <div className="dash-question">{text("question", "What is on the shelf, and what expires before we can use it?")}</div>
      </div>
      <div className="dash-asat">
        Data as at <b>{text("asAt", "the last query")}</b>
        <div>{text("units", "BATCHES · STOCK LINES · DAYS")}</div>
      </div>
    </div>
  );
}

export function StatusKpi({ caption, value, tone, context }: { caption: string; value: string; tone: string; context: string }) {
  const status = statusOf(tone);
  const blank = value === "" || value === "null";
  return (
    <div className="status-kpi" style={{ borderLeftColor: status.color }}>
      <div className="status-kpi-cap">{caption}</div>
      <div className="status-kpi-val">{blank ? "–" : value}</div>
      <div className="status-kpi-st" style={{ color: status.ink }}>{status.glyph} {status.word}</div>
      <div className="status-kpi-cx">{context}</div>
    </div>
  );
}

export function ChainVisual({ model }: { model: TableModel }) {
  const stage = model.columns.findIndex((name) => /stage/i.test(name));
  const label = model.columns.findIndex((name) => /label|count|unit/i.test(name));
  const tone = model.columns.findIndex((name) => /tone|status/i.test(name));
  return (
    <div className="chain">
      {model.rows.map((row) => {
        const status = statusOf(tone >= 0 ? row[tone] ?? "none" : "none");
        return (
          <div key={row[stage] ?? row.join("-")} className="chain-step" style={{ borderBottomColor: status.color }}>
            <b>{row[stage] ?? ""} <span style={{ color: status.ink }}>{status.glyph}</span></b>
            <i>{row[label] ?? ""}</i>
          </div>
        );
      })}
    </div>
  );
}

export function DonutVisual({ model }: { model: PieModel }) {
  const total = model.slices.reduce((sum, slice) => sum + slice.value, 0);
  const ranked = model.slices.filter((slice) => !isNoDataLabel(slice.name)).sort((a, b) => b.value - a.value);
  const colorOf = (name: string) => (isNoDataLabel(name) ? ERP_NATIVE.none : ERP_NATIVE.data[ranked.findIndex((slice) => slice.name === name)] ?? ERP_NATIVE.data[0]);
  return (
    <div className="donut-wrap">
      <ReactECharts
        style={{ height: 220, width: 170 }}
        option={{
          title: { text: total.toLocaleString("en-GB"), subtext: "batches", left: "center", top: "center", itemGap: 2, textStyle: { fontSize: 22, fontWeight: 600, color: ERP_NATIVE.ink }, subtextStyle: { fontSize: 12, color: ERP_NATIVE.muted } },
          series: [{ type: "pie", radius: ["62%", "90%"], label: { show: false }, data: model.slices.map((slice) => ({ name: slice.name, value: slice.value, itemStyle: { color: colorOf(slice.name) } })) }],
        }}
      />
      <table className="legend-table">
        <thead><tr><th>Class</th><th>Batches</th><th>Share</th></tr></thead>
        <tbody>
          {model.slices.map((slice) => (
            <tr key={slice.name}>
              <td><i style={{ background: colorOf(slice.name) }} />{slice.name}</td>
              <td>{slice.value.toLocaleString("en-GB")}</td>
              <td>{total === 0 ? "–" : `${Math.round((100 * slice.value) / total)}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ParetoVisual({ model }: { model: CartesianModel }) {
  const pairs = model.categories.map((name, index) => ({ name, value: model.series[0]?.values[index] ?? 0 }));
  pairs.sort((a, b) => b.value - a.value);
  const total = pairs.reduce((sum, item) => sum + item.value, 0);
  let run = 0;
  const cumulative = pairs.map((item) => {
    run += item.value;
    return total === 0 ? 0 : Math.round((100 * run) / total);
  });
  return (
    <ReactECharts
      style={{ height: "100%", width: "100%" }}
      option={{
        legend: { top: 0, data: ["Batches", "Cumulative %"] },
        xAxis: { type: "category", data: pairs.map((item) => item.name), axisLabel: { rotate: 25, fontSize: 11 } },
        yAxis: [{ type: "value" }, { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } }],
        series: [
          { name: "Batches", type: "bar", data: pairs.map((item) => item.value), itemStyle: { color: ERP_NATIVE.data[0] } },
          { name: "Cumulative %", type: "line", yAxisIndex: 1, data: cumulative, itemStyle: { color: ERP_NATIVE.watch }, markLine: { symbol: "none", data: [{ yAxis: 80 }], lineStyle: { type: "dashed" }, label: { formatter: "80%" } } },
        ],
      }}
    />
  );
}

export function HeatVisual({ model }: { model: TableModel }) {
  const cat = model.columns.findIndex((name) => /categor/i.test(name));
  const win = model.columns.findIndex((name) => /window/i.test(name));
  const val = model.columns.findIndex((name) => /batch|value|count/i.test(name));
  const categories = [...new Set(model.rows.map((row) => row[cat] ?? ""))];
  const windows = [...new Set(model.rows.map((row) => row[win] ?? ""))];
  const max = Math.max(1, ...model.rows.map((row) => Number(row[val] ?? 0)));
  return (
    <table className="heat-matrix">
      <thead>
        <tr><th>Category</th>{windows.map((window) => <th key={window}>{window}</th>)}</tr>
      </thead>
      <tbody>
        {categories.map((category) => (
          <tr key={category}>
            <td>{category}</td>
            {windows.map((window, index) => {
              const found = model.rows.find((row) => row[cat] === category && row[win] === window);
              const value = Number(found?.[val] ?? 0);
              if (!value) return <td key={window} className="heat-zero">–</td>;
              const alpha = 0.2 + 0.8 * Math.sqrt(value / max);
              const background = index === 0 ? `rgba(199,110,108,${alpha})` : `rgba(63,111,176,${alpha})`;
              return <td key={window} style={{ background }}>{value.toLocaleString("en-GB")}</td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function formatCell(column: string, value: string): string {
  if (/expir|date/i.test(column) && /^\d{4}-\d{2}-\d{2}/.test(value)) return formatDate(value);
  return value;
}
