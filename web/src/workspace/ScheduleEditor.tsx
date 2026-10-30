/** Preset or raw cron for a dataset refresh. */

import { useState } from "react";

import { apiFetch } from "../shared/api";
import { SCHEDULE_PRESETS } from "./refreshPlan";

export function ScheduleEditor({
  workspaceId,
  datasetId,
  cron,
  onChange,
}: {
  workspaceId: string;
  datasetId: string;
  cron: string | null;
  onChange: (cron: string | null) => void;
}) {
  const [raw, setRaw] = useState(cron ?? "0 6 * * *");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(next: string) {
    setSaving(true);
    setError("");
    try {
      const saved = await apiFetch<{ cron: string }>(
        `/workspaces/${workspaceId}/datasets/${datasetId}/schedule`,
        { method: "PUT", body: JSON.stringify({ cron: next }) },
      );
      setRaw(saved.cron);
      onChange(saved.cron);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Schedule failed");
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setSaving(true);
    setError("");
    try {
      await apiFetch<void>(`/workspaces/${workspaceId}/datasets/${datasetId}/schedule`, { method: "DELETE" });
      onChange(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not clear the schedule");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="schedule-editor">
      <p className="ws-hint">{cron ? `Scheduled: ${cron}` : "No schedule"}</p>
      <div className="schedule-presets">
        {SCHEDULE_PRESETS.map((preset) => (
          <button key={preset.id} type="button" className="ws-btn small" disabled={saving} onClick={() => void save(preset.cron)}>
            {preset.label}
          </button>
        ))}
      </div>
      <div className="form-group">
        <label>Cron</label>
        <input value={raw} onChange={(event) => setRaw(event.target.value)} />
      </div>
      <div className="form-actions">
        <button type="button" className="ws-btn primary small" disabled={saving} onClick={() => void save(raw.trim())}>
          Save schedule
        </button>
        <button type="button" className="ws-btn small" disabled={saving || !cron} onClick={() => void clear()}>
          Remove
        </button>
      </div>
      {error && <p className="ws-error">{error}</p>}
    </div>
  );
}
