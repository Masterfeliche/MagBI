import { useDesignerStore } from "./store";

const ANALYTICS_ITEMS = [
  { key: "trend", title: "Trend line", desc: "Show linear or polynomial trend", color: "#2B5797" },
  { key: "constant", title: "Constant line", desc: "Add a reference line at a fixed value", color: "#EF4444" },
  { key: "average", title: "Average line", desc: "Show the average across all data points", color: "#F59E0B" },
  { key: "min", title: "Min line", desc: "Show the minimum value", color: "#10B981" },
  { key: "max", title: "Max line", desc: "Show the maximum value", color: "#10B981" },
  { key: "percentile", title: "Percentile line", desc: "Show a percentile value (median, P25, P75)", color: "#7C3AED" },
  { key: "errorBars", title: "Error bars", desc: "Show standard deviation or custom error ranges", color: "#2B5797" },
  { key: "forecast", title: "Forecast", desc: "Project future values with confidence interval", color: "#E8913A" },
] as const;

export function AnalyticsPane() {
  const selectedId = useDesignerStore((s) => s.selectedVisualId);
  const report = useDesignerStore((s) => s.report);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const setProperties = useDesignerStore((s) => s.setProperties);

  const page = report.pages[activePageIndex];
  const visual = page?.visuals.find((v) => v.id === selectedId);

  if (!visual) {
    return <div className="analytics-section"><p className="hint">Select a visual to add analytics.</p></div>;
  }

  const props = visual.properties ?? {};

  function toggle(key: string) {
    if (!visual) return;
    const analyticsKey = `analytics_${key}`;
    setProperties(visual.id, { [analyticsKey]: !props[analyticsKey] });
  }

  return (
    <div className="analytics-section">
      {ANALYTICS_ITEMS.map((item) => {
        const enabled = !!props[`analytics_${item.key}`];
        return (
          <button
            key={item.key}
            type="button"
            className={`analytics-item${enabled ? " enabled" : ""}`}
            onClick={() => toggle(item.key)}
          >
            <div className="ai-title" style={{ color: item.color }}>
              {enabled && <span className="ai-check">✓ </span>}
              {item.title}
            </div>
            <div className="ai-desc">{item.desc}</div>
          </button>
        );
      })}
    </div>
  );
}
