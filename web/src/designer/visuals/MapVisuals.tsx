import * as echarts from "echarts";
import ReactECharts from "echarts-for-react";
import { useEffect, useState } from "react";

import { BOUNDARY_CREDIT, loadRegions, MAP_NAME, matchRegions, REGIONS_URL, type Regions } from "../maps";
import type { FilledMapModel, MapModel } from "../render";
import { formatNumber } from "../formatChart";

/** The region boundaries, registered with ECharts once they load; null while loading, false when missing. */
function useRegions(): Regions | null | false {
  const [regions, setRegions] = useState<Regions | null | false>(null);
  useEffect(() => {
    let cancelled = false;
    void loadRegions().then((found) => {
      if (cancelled) return;
      if (found) echarts.registerMap(MAP_NAME, found as unknown as Parameters<typeof echarts.registerMap>[1]);
      setRegions(found ?? false);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return regions;
}

function Missing({ title }: { title: string }) {
  return (
    <div className="note">
      {title && <strong>{title}</strong>}
      <div>Region boundaries aren't installed. Add a GeoJSON file of Tanzania's regions at {REGIONS_URL} to draw this map.</div>
    </div>
  );
}

/** Regions shaded by value: one hue from light (low) to dark (high); regions with no value stay grey. */
export function FilledMap({
  model,
  title,
  palette,
  onCategory,
  highlightCategory,
}: {
  model: FilledMapModel;
  title: string;
  palette?: string[];
  onCategory?: (category: string) => void;
  highlightCategory?: string;
}) {
  const regions = useRegions();
  if (regions === null) return <div className="note">Loading map…</div>;
  if (regions === false) return <Missing title={title} />;
  const { matched, unmatched } = matchRegions(regions, model.regions);
  const values = matched.map((item) => item.value);
  const dark = palette?.[0] ?? "#3F6FB0";
  const option = {
    title: title ? { text: title, left: 8, textStyle: { fontSize: 14, fontWeight: 600 } } : undefined,
    tooltip: {
      trigger: "item" as const,
      formatter: (item: { name: string; value?: number }) =>
        Number.isFinite(item.value) ? `${item.name}: ${formatNumber(item.value)}` : `${item.name}: no value`,
    },
    visualMap: {
      min: Math.min(0, ...values),
      max: Math.max(1, ...values),
      left: 8,
      bottom: 8,
      calculable: false,
      itemHeight: 90,
      inRange: { color: ["#E3EBF5", dark] },
      text: ["High", "Low"],
    },
    series: [
      {
        type: "map" as const,
        map: MAP_NAME,
        roam: false,
        itemStyle: { areaColor: "#EEF1F5", borderColor: "#FFFFFF", borderWidth: 1 },
        emphasis: { label: { show: true }, itemStyle: { areaColor: undefined } },
        select: { disabled: true },
        data: matched.map((item) => ({
          ...item,
          itemStyle: highlightCategory && highlightCategory !== item.name ? { opacity: 0.35 } : undefined,
        })),
      },
    ],
  };
  return (
    <div className="map-wrap">
      <ReactECharts option={option} style={{ height: "100%", width: "100%" }} onEvents={{ click: (p: { name?: string }) => p.name && onCategory?.(p.name) }} />
      {unmatched.length > 0 && <div className="map-note" title={unmatched.join(", ")}>No boundary for {unmatched.length} name{unmatched.length === 1 ? "" : "s"}: {unmatched.slice(0, 3).join(", ")}</div>}
      <div className="map-credit">{BOUNDARY_CREDIT}</div>
    </div>
  );
}

/** Points placed by latitude and longitude, sized by the value; over the region boundaries when they are installed. */
export function PointMap({
  model,
  title,
  palette,
  onCategory,
}: {
  model: MapModel;
  title: string;
  palette?: string[];
  onCategory?: (category: string) => void;
}) {
  const regions = useRegions();
  if (regions === null) return <div className="note">Loading map…</div>;
  const sized = model.points.map((point) => point.value ?? 1);
  const largest = Math.max(1, ...sized.map(Math.abs));
  const data = model.points.map((point) => ({ name: point.name, value: [point.lon, point.lat, point.value] }));
  const colour = palette?.[0] ?? "#3F6FB0";
  const symbolSize = (value: number[]) => 8 + 22 * Math.sqrt(Math.abs(value[2] ?? 1) / largest);
  const series = {
    type: "scatter" as const,
    data,
    symbolSize,
    itemStyle: { color: colour, opacity: 0.85, borderColor: "#FFFFFF", borderWidth: 1 },
    ...(regions ? { coordinateSystem: "geo" as const } : {}),
  };
  const option = {
    title: title ? { text: title, left: 8, textStyle: { fontSize: 14, fontWeight: 600 } } : undefined,
    tooltip: {
      trigger: "item" as const,
      formatter: (item: { name: string; value: number[] }) =>
        `${item.name}${item.value[2] == null ? "" : `: ${formatNumber(item.value[2])}`}<br/>${item.value[1].toFixed(3)}, ${item.value[0].toFixed(3)}`,
    },
    ...(regions
      ? { geo: { map: MAP_NAME, roam: false, itemStyle: { areaColor: "#EEF1F5", borderColor: "#FFFFFF" }, silent: true } }
      : {
          // Without boundaries the points sit on plain axes, named along each axis, clear of the title.
          grid: { left: 56, right: 16, top: title ? 40 : 16, bottom: 44 },
          xAxis: { type: "value" as const, name: "Longitude", nameLocation: "middle" as const, nameGap: 26, scale: true },
          yAxis: { type: "value" as const, name: "Latitude", nameLocation: "middle" as const, nameGap: 36, scale: true },
        }),
    series: [series],
  };
  return (
    <div className="map-wrap">
      <ReactECharts option={option} style={{ height: "100%", width: "100%" }} onEvents={{ click: (p: { name?: string }) => p.name && onCategory?.(p.name) }} />
      {regions && <div className="map-credit">{BOUNDARY_CREDIT}</div>}
    </div>
  );
}
