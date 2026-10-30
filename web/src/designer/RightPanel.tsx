import { useState } from "react";

import type { FieldBinding } from "../types/report";
import type { WellSpec } from "./catalog";
import { DataPane } from "./DataPane";
import { FormatPane } from "./FormatPane";
import { AnalyticsPane } from "./AnalyticsPane";
import { InteractionEditor } from "./InteractionEditor";
import { WellsPanel } from "./WellsPanel";
import type { DesignerTable } from "./model";

type Tab = "data" | "format" | "analytics" | "interact";

export function RightPanel({
  tables,
  wells,
  bindings,
  onRemoveBinding,
}: {
  tables: DesignerTable[];
  wells: WellSpec[];
  bindings: Record<string, FieldBinding[]>;
  onRemoveBinding: (wellName: string, index: number) => void;
}) {
  const [tab, setTab] = useState<Tab>("data");

  return (
    <div className="right-panel">
      <div className="rp-tabs">
        {(["data", "format", "analytics", "interact"] as const).map((t) => (
          <button
            key={t}
            type="button"
            className={`rp-tab${tab === t ? " active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <div className="rp-content">
        {tab === "data" && (
          <>
            <div className="fields-list">
              <DataPane tables={tables} />
            </div>
            <div className="wells">
              <WellsPanel wells={wells} bindings={bindings} onRemove={onRemoveBinding} />
            </div>
          </>
        )}
        {tab === "format" && <FormatPane />}
        {tab === "analytics" && <AnalyticsPane />}
        {tab === "interact" && <InteractionEditor />}
      </div>
    </div>
  );
}
