/** The MSD standard visual kit: data, panel chrome, and every kit visual. */

import ReactECharts from "echarts-for-react";
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { whereClauses } from "../designer/query";
import { useDesignerStore } from "../designer/store";
import { apiFetch } from "../shared/api";
import type { DSR } from "../types/query";
import type { FilterDefinition, VisualDefinition } from "../types/report";
import { kitQuery, memberQuery, mergeMembers } from "./query";
import {
  fill,
  formatValue,
  isNoData,
  isTone,
  STATUS,
  toNumber,
  toneOf,
  TOKENS,
  type Tone,
  type ToneRule,
  type ValueFormat,
} from "./tone";
import "./kit.css";

type Props = Record<string, unknown>;

const PANEL_TYPES = new Set(["calendar", "donut", "pareto", "heatmap", "grid", "meter", "bars", "stack100", "flow"]);
const STATIC_TYPES = new Set(["header", "label", "frame"]);
export const EMPTY_TEXT = "Nothing recorded for this view yet";

interface Loaded {
  rows: unknown[][];
  ignored: string[];
  centre: unknown;
}

function str(props: Props, key: string, fallback = ""): string {
  const value = props[key];
  return typeof value === "string" ? value : fallback;
}

function post(workspaceId: string, datasetId: string, query: unknown, roles: string[], signal: AbortSignal): Promise<DSR & { ignoredFilters?: string[] }> {
  return apiFetch(`/workspaces/${workspaceId}/datasets/${datasetId}/query`, {
    method: "POST",
    body: JSON.stringify({ query, roles }),
    signal,
  });
}

function useKitData(visual: VisualDefinition, workspaceId: string, datasetId: string, filters: FilterDefinition[]) {
  const roles = useDesignerStore((state) => state.viewAs?.roles);
  const query = useMemo(() => kitQuery(visual, filters), [visual, filters]);
  const members = useMemo(() => memberQuery(visual), [visual]);
  const centre = visual.wells.centre?.[0];
  const key = JSON.stringify([query, members, centre, filters, roles]);
  const [state, setState] = useState<{ data: Loaded | null; error: string; loading: boolean }>({ data: null, error: "", loading: true });

  useEffect(() => {
    if (STATIC_TYPES.has(visual.type) || !query || !workspaceId || !datasetId) {
      setState({ data: null, error: "", loading: false });
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const asked = roles ?? [];
      const main = post(workspaceId, datasetId, query, asked, controller.signal);
      const all = members ? post(workspaceId, datasetId, members, asked, controller.signal) : Promise.resolve(null);
      const where = whereClauses(filters);
      const side = centre?.measure
        ? post(
            workspaceId,
            datasetId,
            { from: [], select: [{ measure: { table: centre.table, measure: centre.measure } }], ...(where.length ? { where } : {}) },
            asked,
            controller.signal,
          )
        : Promise.resolve(null);
      Promise.all([main, all, side])
        .then(([result, memberResult, sideResult]) => {
          if (controller.signal.aborted) return;
          const rows = memberResult ? mergeMembers(visual, result.rows, memberResult.rows) : result.rows;
          setState({
            data: { rows, ignored: result.ignoredFilters ?? [], centre: sideResult?.rows[0]?.[0] ?? null },
            error: "",
            loading: false,
          });
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setState({ data: null, error: reason instanceof Error ? reason.message : "the query failed", loading: false });
        });
    }, 150);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // `key` captures every input that changes the questions asked.
  }, [key, workspaceId, datasetId]);
  return state;
}

export function KitVisual({
  visual,
  workspaceId,
  datasetId,
  filters,
  onCategory,
  highlightCategory,
}: {
  visual: VisualDefinition;
  workspaceId: string;
  datasetId: string;
  filters: FilterDefinition[];
  onCategory?: (category: string) => void;
  highlightCategory?: string;
}) {
  const props = (visual.properties ?? {}) as Props;
  const { data, error, loading } = useKitData(visual, workspaceId, datasetId, filters);

  if (visual.type === "header") return <Header props={props} />;
  if (visual.type === "label") return <Label props={props} />;
  if (visual.type === "frame") return <Frame props={props} />;

  const body = (() => {
    if (error) return <div className="kit-state kit-error">Couldn't load: {error}</div>;
    if (loading && !data) return <div className="kit-state">Loading…</div>;
    const rows = data?.rows ?? [];
    const pick = (category: string) => onCategory?.(category);
    switch (visual.type) {
      case "kpi":
        return <Kpi props={props} rows={rows} />;
      case "chain":
        return <Chain props={props} rows={rows} />;
      case "meter":
        return <Meter props={props} rows={rows} />;
      case "flow":
        return <Flow props={props} rows={rows} visual={visual} />;
      default:
        break;
    }
    if (rows.length === 0 || (visual.type === "bars" && !visual.wells["x-axis"]?.length && rows[0]?.every((cell) => cell == null))) {
      return <div className="kit-state">{EMPTY_TEXT}</div>;
    }
    switch (visual.type) {
      case "calendar":
        return <Calendar props={props} rows={rows} onPick={pick} highlight={highlightCategory} />;
      case "donut":
        return <Donut props={props} rows={rows} centre={data?.centre ?? null} hasCentre={Boolean(visual.wells.centre?.length)} onPick={pick} />;
      case "pareto":
        return <Pareto props={props} rows={rows} onPick={pick} />;
      case "heatmap":
        return <Heat props={props} rows={rows} onPick={pick} />;
      case "grid":
        return <Grid props={props} rows={rows} />;
      case "bars":
        return <Bars props={props} rows={rows} visual={visual} onPick={pick} />;
      case "stack100":
        return <Stack100 props={props} rows={rows} onPick={pick} />;
      default:
        return <div className="kit-state">This visual type is not drawn.</div>;
    }
  })();

  const note = data && data.ignored.length > 0 ? `Not filtered by ${data.ignored.map(fieldLabel).join(", ")}` : "";
  if (!PANEL_TYPES.has(visual.type)) {
    return (
      <div className="kit-bare">
        {body}
        {note && <div className="kit-ignored" title={note}>{note}</div>}
      </div>
    );
  }
  return (
    <section className="kit-panel">
      <header className="kit-panel-hd">
        <h3>{str(props, "title")}</h3>
        <span className="kit-panel-sub">{str(props, "subtitle")}</span>
      </header>
      <div className="kit-panel-bd">{body}</div>
      {note && <div className="kit-ignored" title={note}>{note}</div>}
    </section>
  );
}

function fieldLabel(name: string): string {
  const match = /\[(.+)\]$/.exec(name);
  return match ? match[1] : name;
}

// ---------------------------------------------------------------- static parts

function Header({ props }: { props: Props }) {
  const asAt = useDesignerStore((state) => state.dataAsAt);
  const crumb = str(props, "crumb").split("/").map((part) => part.trim()).filter(Boolean);
  return (
    <div className="kit-header">
      <div className="kit-header-left">
        <div className="kit-crumb">
          {crumb.map((part, index) => (
            <span key={part}>
              {index > 0 && <span className="kit-crumb-sep"> / </span>}
              {index === crumb.length - 1 ? <b>{part}</b> : part}
            </span>
          ))}
        </div>
        <div className="kit-title">{str(props, "title")}</div>
        <div className="kit-question">{str(props, "question")}</div>
      </div>
      <div className="kit-header-right">
        <div className="kit-asat">
          Data as at <b>{asAt ? asAtText(asAt) : "–"}</b>
          {str(props, "source") && <> · {str(props, "source")}</>}
        </div>
        <div className="kit-units">{str(props, "units")}</div>
      </div>
    </div>
  );
}

export function asAtText(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "–";
  const day = when.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const time = when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${day}, ${time}`;
}

function Label({ props }: { props: Props }) {
  return <div className={`kit-label kit-label-${str(props, "variant", "section")}`}>{str(props, "text")}</div>;
}

function Frame({ props }: { props: Props }) {
  const style: CSSProperties = {
    background: str(props, "fill", TOKENS.surface),
    border: `1px solid ${str(props, "border", TOKENS.line)}`,
    borderRadius: typeof props.radius === "number" ? props.radius : 6,
  };
  return <div className="kit-frame" style={style} />;
}

// ---------------------------------------------------------------- KPI and chain

function Kpi({ props, rows }: { props: Props; rows: unknown[][] }) {
  const row = rows[0] ?? [];
  const format = str(props, "format", "whole") as ValueFormat;
  const extraFormats = (Array.isArray(props.extraFormats) ? props.extraFormats : []) as ValueFormat[];
  const shown = [formatValue(row[0], format), ...row.slice(1).map((value, index) => formatValue(value, extraFormats[index] ?? "whole"))];
  const value = toNumber(row[0]);
  // A card may show one figure and take its status from another, e.g. transfers coloured by late ones.
  const toneValue = typeof props.toneFrom === "number" ? toNumber(row[props.toneFrom]) : value;
  const tone = toneOf(toneValue, props.rule as ToneRule | undefined);
  const status = STATUS[tone];
  const words = (props.status ?? {}) as Partial<Record<Tone, string>>;
  const zeroContext = value === 0 && typeof props.contextZero === "string" ? props.contextZero : null;
  return (
    <div className="kit-kpi" style={{ borderLeftColor: status.color }}>
      <div className="kit-kpi-cap">{str(props, "caption")}</div>
      <div className="kit-kpi-val">{shown[0]}</div>
      <div className="kit-kpi-st" style={{ color: status.ink }}>
        {status.glyph} {fill(words[tone] ?? status.word, shown)}
      </div>
      <div className="kit-kpi-cx">{fill(zeroContext ?? str(props, "context"), shown)}</div>
    </div>
  );
}

/** Chain rows: Stage, StageOrder, Unit, BaseTone, FlagTone, AgeLimit, Count, AgeDays, Flags. */
export function chainTone(count: number | null, age: number | null, flags: number | null, ageLimit: number | null, base: unknown, flag: unknown): Tone {
  if (!count) return "none";
  if (flags && flags > 0) return isTone(flag) ? flag : "watch";
  if (ageLimit !== null && age !== null && age > ageLimit) return "watch";
  return isTone(base) ? base : "info";
}

function Chain({ props, rows }: { props: Props; rows: unknown[][] }) {
  const highlight = new Set(Array.isArray(props.highlight) ? props.highlight.map(String) : []);
  const notes = (props.notes ?? {}) as Record<string, string>;
  const stages = [...rows].sort((a, b) => (toNumber(a[1]) ?? 0) - (toNumber(b[1]) ?? 0));
  return (
    <div className="kit-chain">
      {stages.map((row) => {
        const name = String(row[0] ?? "");
        const count = toNumber(row[6]);
        const tone = chainTone(count, toNumber(row[7]), toNumber(row[8]), toNumber(row[5]), row[3], row[4]);
        const status = STATUS[tone];
        const text = `${formatValue(count ?? 0)} ${String(row[2] ?? "")}`.trim();
        const tip = [`${name}: ${text}`, `${status.glyph} ${status.word}`, notes[name]].filter(Boolean).join(" · ");
        return (
          <div key={name} className={highlight.has(name) ? "kit-step on" : "kit-step"} title={tip}>
            <b>
              <span>{name}</span>
              <span style={{ color: status.ink }}>{status.glyph}</span>
            </b>
            <i>{text}</i>
            <u style={{ background: status.color }} />
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- charts

const AXIS = { color: TOKENS.muted, fontSize: 11, fontFamily: "Segoe UI, IBM Plex Sans, sans-serif" };
const BASE = { textStyle: { fontFamily: "Segoe UI, IBM Plex Sans, sans-serif", color: TOKENS.ink }, animationDuration: 300 };

function colourFor(name: string, rank: number, colours: Record<string, string>): string {
  const set = colours[name];
  if (set) return isTone(set) ? STATUS[set].color : set;
  if (isNoData(name)) return STATUS.none.color;
  return TOKENS.data[Math.min(rank, TOKENS.data.length - 1)] ?? TOKENS.data[0];
}

/** Calendar rows: Label, SortKey, Flag, Value. Every member is present when allMembers is on. */
function Calendar({ props, rows, onPick, highlight }: { props: Props; rows: unknown[][]; onPick: (value: string) => void; highlight?: string }) {
  const ordered = [...rows].sort((a, b) => String(a[1] ?? "").localeCompare(String(b[1] ?? "")));
  const flagTone = (isTone(props.flagTone) ? props.flagTone : "watch") as Tone;
  const template = str(props, "tooltip", "{0} in {1}");
  const every = typeof props.labelEvery === "number" ? props.labelEvery : 1;
  return (
    <ReactECharts
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (event: { name?: string }) => event.name && onPick(event.name) }}
      option={{
        ...BASE,
        grid: { left: 40, right: 12, top: 22, bottom: 26 },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          formatter: (items: { name: string; value: number }[]) => {
            const item = items[0];
            if (!item) return "";
            return fill(template, [item.value ? formatValue(item.value) : "No", item.name]);
          },
        },
        xAxis: {
          type: "category",
          data: ordered.map((row) => String(row[0] ?? "")),
          axisLabel: { ...AXIS, interval: every - 1 },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: TOKENS.line2 } },
        },
        yAxis: { type: "value", minInterval: 1, axisLabel: AXIS, splitLine: { lineStyle: { color: TOKENS.line2 } } },
        series: [
          {
            type: "bar",
            barMaxWidth: 26,
            data: ordered.map((row) => {
              const name = String(row[0] ?? "");
              const flagged = toNumber(row[2]) === 1;
              const dim = highlight && highlight !== name;
              return {
                value: toNumber(row[3]) ?? 0,
                itemStyle: {
                  color: flagged ? STATUS[flagTone].color : TOKENS.data[0],
                  opacity: dim ? 0.3 : 1,
                  borderRadius: [2, 2, 0, 0],
                },
              };
            }),
            label: { show: true, position: "top", fontSize: 10.5, color: TOKENS.ink, formatter: (item: { value: number }) => (item.value ? formatValue(item.value) : "") },
          },
        ],
      }}
    />
  );
}

/** Donut rows: Name, Value. The centre is the sum of the visible slices unless a centre measure is set. */
function Donut({ props, rows, centre, hasCentre, onPick }: { props: Props; rows: unknown[][]; centre: unknown; hasCentre: boolean; onPick: (value: string) => void }) {
  const slices = rows
    .map((row) => ({ name: String(row[0] ?? "") || "Not set", value: toNumber(row[1]) ?? 0 }))
    .filter((slice) => slice.value > 0);
  const colours = (props.colours ?? {}) as Record<string, string>;
  const ranked = slices.filter((slice) => !colours[slice.name] && !isNoData(slice.name)).sort((a, b) => b.value - a.value).map((slice) => slice.name);
  const colourOf = (name: string) => colourFor(name, ranked.indexOf(name), colours);
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const centreText = hasCentre ? formatValue(centre, str(props, "centreFormat", "whole") as ValueFormat) : formatValue(total);
  const ordered = [...slices].sort((a, b) => {
    if (isNoData(a.name) !== isNoData(b.name)) return isNoData(a.name) ? 1 : -1;
    return b.value - a.value;
  });
  if (slices.length === 0) return <div className="kit-state">{EMPTY_TEXT}</div>;
  return (
    <div className="kit-donut">
      <div className="kit-donut-ring" data-centre={centreText} data-total={total}>
        <ReactECharts
          style={{ height: "100%", width: "100%" }}
          onEvents={{ click: (event: { name?: string }) => event.name && onPick(event.name) }}
          option={{
            ...BASE,
            tooltip: { trigger: "item", formatter: (item: { name: string; value: number; percent: number }) => `${item.name}: ${formatValue(item.value)} ${str(props, "unit")} (${Math.round(item.percent)}%)` },
            series: [
              {
                type: "pie",
                radius: ["62%", "90%"],
                center: ["50%", "50%"],
                label: { show: false },
                labelLine: { show: false },
                itemStyle: { borderColor: "#FFFFFF", borderWidth: 2 },
                data: ordered.map((slice) => ({ name: slice.name, value: slice.value, itemStyle: { color: colourOf(slice.name) } })),
              },
            ],
          }}
        />
        <div className="kit-donut-centre">
          <b>{centreText}</b>
          <span>{str(props, "centreWord", str(props, "unit"))}</span>
        </div>
      </div>
      <table className="kit-legend">
        <thead>
          <tr>
            <th>{str(props, "header", "Name")}</th>
            <th>{str(props, "valueHeader", "Count")}</th>
            <th>Share</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((slice) => (
            <tr key={slice.name}>
              <td>
                <i style={{ background: colourOf(slice.name) }} />
                {slice.name}
              </td>
              <td>{formatValue(slice.value)}</td>
              <td>{total ? `${Math.round((100 * slice.value) / total)}%` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Pareto rows: Category, Value. */
function Pareto({ props, rows, onPick }: { props: Props; rows: unknown[][]; onPick: (value: string) => void }) {
  const pairs = rows.map((row) => ({ name: String(row[0] ?? ""), value: toNumber(row[1]) ?? 0 })).filter((pair) => pair.value > 0).sort((a, b) => b.value - a.value);
  const total = pairs.reduce((sum, pair) => sum + pair.value, 0);
  let running = 0;
  const cumulative = pairs.map((pair) => {
    running += pair.value;
    return total ? Math.round((100 * running) / total) : 0;
  });
  const series = str(props, "seriesName", "Count");
  if (pairs.length === 0) return <div className="kit-state">{EMPTY_TEXT}</div>;
  return (
    <ReactECharts
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (event: { name?: string }) => event.name && onPick(event.name) }}
      option={{
        ...BASE,
        grid: { left: 40, right: 44, top: 30, bottom: 50 },
        legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: TOKENS.muted, fontSize: 11 } },
        tooltip: { trigger: "axis" },
        xAxis: { type: "category", data: pairs.map((pair) => pair.name), axisLabel: { ...AXIS, interval: 0, rotate: pairs.length > 4 ? 25 : 0 }, axisTick: { show: false }, axisLine: { lineStyle: { color: TOKENS.line2 } } },
        yAxis: [
          { type: "value", minInterval: 1, axisLabel: AXIS, splitLine: { lineStyle: { color: TOKENS.line2 } } },
          { type: "value", min: 0, max: 100, axisLabel: { ...AXIS, formatter: "{value}%" }, splitLine: { show: false } },
        ],
        series: [
          { name: series, type: "bar", barMaxWidth: 40, data: pairs.map((pair) => pair.value), itemStyle: { color: TOKENS.data[0], borderRadius: [2, 2, 0, 0] }, label: { show: true, position: "top", fontSize: 10.5, color: TOKENS.ink } },
          {
            name: "Cumulative %",
            type: "line",
            yAxisIndex: 1,
            data: cumulative,
            symbolSize: 6,
            lineStyle: { color: STATUS.watch.color, width: 2.5 },
            itemStyle: { color: STATUS.watch.color },
            markLine: { silent: true, symbol: "none", data: [{ yAxis: 80 }], lineStyle: { color: TOKENS.muted, type: "dashed" }, label: { show: false } },
          },
        ],
      }}
    />
  );
}

/** Heat matrix rows: Row, Column, Value. Rows are ordered by total, columns by `columnOrder`. */
function Heat({ props, rows, onPick }: { props: Props; rows: unknown[][]; onPick: (value: string) => void }) {
  const order = Array.isArray(props.columnOrder) ? props.columnOrder.map(String) : [...new Set(rows.map((row) => String(row[1] ?? "")))];
  const action = str(props, "actionColumn");
  const cell = new Map(rows.map((row) => [`${String(row[0])}\u0000${String(row[1])}`, toNumber(row[2]) ?? 0]));
  const names = [...new Set(rows.map((row) => String(row[0] ?? "")))];
  const totals = new Map(names.map((name) => [name, order.reduce((sum, column) => sum + (cell.get(`${name}\u0000${column}`) ?? 0), 0)]));
  const shown = names.filter((name) => (totals.get(name) ?? 0) > 0).sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0));
  const max = Math.max(1, ...shown.flatMap((name) => order.map((column) => cell.get(`${name}\u0000${column}`) ?? 0)));
  if (shown.length === 0) return <div className="kit-state">{EMPTY_TEXT}</div>;
  return (
    <div className="kit-heat-wrap">
      <table className="kit-heat">
        <thead>
          <tr>
            <th>{str(props, "rowHeader", "Category")}</th>
            {order.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((name) => (
            <tr key={name}>
              <td className="kit-heat-row">
                <button type="button" onClick={() => onPick(name)}>{name}</button>
              </td>
              {order.map((column) => {
                const value = cell.get(`${name}\u0000${column}`) ?? 0;
                if (!value) return <td key={column} className="kit-heat-zero">–</td>;
                const alpha = 0.2 + 0.8 * Math.sqrt(value / max);
                const base = column === action ? "199,110,108" : "63,111,176";
                return (
                  <td key={column} style={{ background: `rgba(${base},${alpha.toFixed(2)})`, color: alpha > 0.55 ? "#FFFFFF" : TOKENS.ink }}>
                    {formatValue(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="kit-heat-key">
        <span><i style={{ background: "rgba(63,111,176,.9)" }} />More</span>
        <span><i style={{ background: "rgba(63,111,176,.25)" }} />Less</span>
        {action && <span><i style={{ background: "rgba(199,110,108,.85)" }} />{str(props, "actionLabel", action)}</span>}
      </div>
    </div>
  );
}

interface GridColumn {
  header?: string;
  format?: ValueFormat;
  align?: "left" | "right";
  hidden?: boolean;
  pill?: { rule?: ToneRule; map?: Record<string, Tone>; toneFrom?: number; text?: string };
}

export function pillTone(pill: NonNullable<GridColumn["pill"]>, value: unknown, row: unknown[]): Tone {
  if (pill.toneFrom !== undefined) {
    const tone = row[pill.toneFrom];
    return isTone(tone) ? tone : "none";
  }
  if (pill.map) return pill.map[String(value ?? "")] ?? "none";
  return toneOf(toNumber(value), pill.rule);
}

/** Grid rows arrive sorted and limited by the server. */
function Grid({ props, rows }: { props: Props; rows: unknown[][] }) {
  const columns = (Array.isArray(props.columns) ? props.columns : []) as GridColumn[];
  const visible = columns.map((column, index) => ({ column, index })).filter(({ column }) => !column.hidden);
  return (
    <div className="kit-grid-wrap">
      <table className="kit-grid">
        <thead>
          <tr>
            {visible.map(({ column, index }) => (
              <th key={index} className={column.align === "right" ? "n" : undefined}>{column.header ?? ""}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {visible.map(({ column, index }) => {
                const value = row[index];
                const text = formatValue(value, column.format ?? (typeof value === "number" ? "whole" : "text"));
                if (column.pill) {
                  const tone = pillTone(column.pill, value, row);
                  const status = STATUS[tone];
                  return (
                    <td key={index} className={column.align === "right" ? "n" : undefined}>
                      <span className="kit-pill" style={{ background: status.soft, color: status.ink }}>
                        {status.glyph} {fill(column.pill.text ?? "{0}", [text])}
                      </span>
                    </td>
                  );
                }
                return (
                  <td key={index} className={column.align === "right" ? "n" : undefined} title={text}>
                    {text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A value against a target, drawn as a half ring. Rows: [[value]]. */
function Meter({ props, rows }: { props: Props; rows: unknown[][] }) {
  const value = toNumber(rows[0]?.[0]);
  const target = toNumber(props.target);
  const tone = toneOf(value, props.rule as ToneRule | undefined);
  const status = STATUS[tone];
  const format = str(props, "format", "pct1") as ValueFormat;
  const words = (props.status ?? {}) as Partial<Record<Tone, string>>;
  const share = value === null ? 0 : Math.max(0, Math.min(1, value));
  const radius = 80;
  const arc = (from: number, to: number) => {
    const a0 = Math.PI * (1 - from);
    const a1 = Math.PI * (1 - to);
    const x0 = 100 + radius * Math.cos(a0);
    const y0 = 100 - radius * Math.sin(a0);
    const x1 = 100 + radius * Math.cos(a1);
    const y1 = 100 - radius * Math.sin(a1);
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${radius} ${radius} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  const tick = target === null ? null : Math.PI * (1 - target);
  const line =
    value === null
      ? str(props, "blankText", "– No data yet")
      : `${status.glyph} ${fill(words[tone] ?? status.word, [formatValue(value, format)])}${target === null ? "" : ` · Target ${formatValue(target, format === "pct1" ? "pct0" : format)}`}`;
  return (
    <div className="kit-meter">
      <svg viewBox="0 0 200 112" role="img" aria-label={`${formatValue(value, format)} ${line}`}>
        <path d={arc(0, 1)} stroke={TOKENS.line2} strokeWidth="16" fill="none" strokeLinecap="butt" />
        {value !== null && share > 0 && <path d={arc(0, share)} stroke={status.color} strokeWidth="16" fill="none" strokeLinecap="butt" />}
        {tick !== null && (
          <line
            x1={100 + (radius - 13) * Math.cos(tick)}
            y1={100 - (radius - 13) * Math.sin(tick)}
            x2={100 + (radius + 13) * Math.cos(tick)}
            y2={100 - (radius + 13) * Math.sin(tick)}
            stroke={TOKENS.ink}
            strokeWidth="2.5"
          />
        )}
        <text x="100" y="96" textAnchor="middle" fontSize="26" fontWeight="700" fill={value === null ? STATUS.none.ink : status.ink}>
          {formatValue(value, format)}
        </text>
      </svg>
      <div className="kit-meter-line" style={{ color: value === null ? STATUS.none.ink : status.ink }}>{line}</div>
    </div>
  );
}

/** Horizontal bars, from a category or from several measures. Largest on top; zero keeps its label. */
function Bars({ props, rows, visual, onPick }: { props: Props; rows: unknown[][]; visual: VisualDefinition; onPick: (value: string) => void }) {
  const labels = (Array.isArray(props.labels) ? props.labels : []) as string[];
  const byCategory = Boolean(visual.wells["x-axis"]?.length);
  const pairs = byCategory
    ? rows.map((row) => ({ name: String(row[0] ?? ""), value: toNumber(row[1]) ?? 0 }))
    : (visual.wells["y-axis"] ?? []).map((binding, index) => ({ name: labels[index] ?? binding.measure ?? binding.column ?? "", value: toNumber(rows[0]?.[index]) ?? 0 }));
  const sorted = props.sort === false ? pairs : [...pairs].sort((a, b) => b.value - a.value);
  return (
    <ReactECharts
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (event: { name?: string }) => byCategory && event.name && onPick(event.name) }}
      option={{
        ...BASE,
        grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
        tooltip: { trigger: "item", formatter: (item: { name: string; value: number }) => `${item.name}: ${formatValue(item.value)} ${str(props, "unit")}`.trim() },
        xAxis: { type: "value", show: false, minInterval: 1 },
        yAxis: { type: "category", inverse: true, data: sorted.map((pair) => pair.name), axisLabel: { ...AXIS, fontSize: 12, color: TOKENS.ink }, axisTick: { show: false }, axisLine: { lineStyle: { color: TOKENS.line2 } } },
        series: [
          {
            type: "bar",
            barMaxWidth: 22,
            data: sorted.map((pair) => ({ value: pair.value, itemStyle: { color: TOKENS.data[0], borderRadius: [0, 2, 2, 0] } })),
            label: { show: true, position: "right", fontSize: 11, color: TOKENS.ink, formatter: (item: { value: number }) => formatValue(item.value) },
          },
        ],
      }}
    />
  );
}

/** A share that never rounds to 0% or 100% unless it is exactly that. */
export function sharePercent(percent: number): string {
  if (percent > 0 && percent < 0.5) return "<1%";
  if (percent >= 99.5 && percent < 100) return `${(Math.floor(percent * 10) / 10).toFixed(1)}%`;
  return `${Math.round(percent)}%`;
}

/** 100% stacked horizontal bars. Rows: Category, Part, Value. */
function Stack100({ props, rows, onPick }: { props: Props; rows: unknown[][]; onPick: (value: string) => void }) {
  const categories = [...new Set(rows.map((row) => String(row[0] ?? "")))];
  const parts = Array.isArray(props.partOrder) ? props.partOrder.map(String) : [...new Set(rows.map((row) => String(row[1] ?? "")))];
  const colours = (props.colours ?? {}) as Record<string, string>;
  const value = (category: string, part: string) => toNumber(rows.find((row) => String(row[0]) === category && String(row[1]) === part)?.[2]) ?? 0;
  const totals = new Map(categories.map((category) => [category, parts.reduce((sum, part) => sum + value(category, part), 0)]));
  const shown = categories.filter((category) => (totals.get(category) ?? 0) > 0).sort((a, b) => (totals.get(b) ?? 0) - (totals.get(a) ?? 0));
  if (shown.length === 0) return <div className="kit-state">{EMPTY_TEXT}</div>;
  return (
    <ReactECharts
      style={{ height: "100%", width: "100%" }}
      onEvents={{ click: (event: { name?: string }) => event.name && onPick(event.name) }}
      option={{
        ...BASE,
        legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: TOKENS.muted, fontSize: 11 } },
        grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
        tooltip: {
          trigger: "item",
          formatter: (item: { name: string; seriesName: string; data: { count: number; value: number } }) =>
            `${item.name} · ${item.seriesName}: ${formatValue(item.data.count)} (${sharePercent(item.data.value)})`,
        },
        xAxis: { type: "value", max: 100, show: false },
        yAxis: { type: "category", inverse: true, data: shown, axisLabel: { ...AXIS, fontSize: 12, color: TOKENS.ink }, axisTick: { show: false }, axisLine: { show: false } },
        series: parts.map((part, rank) => ({
          name: part,
          type: "bar",
          stack: "all",
          barMaxWidth: 24,
          itemStyle: { color: colourFor(part, rank, colours) },
          label: {
            show: true,
            color: "#FFFFFF",
            fontSize: 11,
            formatter: (item: { data: { count: number; value: number } }) => (item.data.value >= 12 ? `${formatValue(item.data.count)} · ${sharePercent(item.data.value)}` : ""),
          },
          data: shown.map((category) => {
            const count = value(category, part);
            const total = totals.get(category) ?? 0;
            return { value: total ? (100 * count) / total : 0, count };
          }),
        })),
      }}
    />
  );
}

/** Stages from several measures, each drawn against the first. A zero stage is a thin watch stub. */
function Flow({ props, rows, visual }: { props: Props; rows: unknown[][]; visual: VisualDefinition }) {
  const labels = (Array.isArray(props.labels) ? props.labels : []) as string[];
  const stages = (visual.wells["y-axis"] ?? []).map((binding, index) => ({ name: labels[index] ?? binding.measure ?? "", value: toNumber(rows[0]?.[index]) ?? 0 }));
  const first = stages[0]?.value ?? 0;
  if (stages.length === 0 || first === 0) return <div className="kit-state">{EMPTY_TEXT}</div>;
  return (
    <div className="kit-flow">
      {stages.map((stage) => {
        const share = first ? stage.value / first : 0;
        const width = stage.value === 0 ? 2 : Math.max(6, share * 100);
        return (
          <div key={stage.name} className="kit-flow-row" title={`${stage.name}: ${formatValue(stage.value)} (${Math.round(share * 100)}% of ${stages[0]?.name ?? ""})`}>
            <div className="kit-flow-name">{stage.name}</div>
            <div className="kit-flow-track">
              <div className="kit-flow-bar" style={{ width: `${width}%`, background: stage.value === 0 ? STATUS.watch.color : TOKENS.data[0] }} />
            </div>
            <div className="kit-flow-val">
              <b>{formatValue(stage.value)}</b> <span>{Math.round(share * 100)}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function KitEmpty({ children }: { children?: ReactNode }) {
  return <div className="kit-state">{children ?? EMPTY_TEXT}</div>;
}
