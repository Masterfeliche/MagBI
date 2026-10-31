/** Email subscriptions and data alerts for the report being viewed. */
import { useEffect, useMemo, useState } from "react";

import {
  alertableVisuals,
  CONDITIONS,
  scheduleLabel,
  SCHEDULES,
  sharing,
  type Condition,
  type DataAlert,
  type Subscription,
} from "../shared/sharing";
import type { ReportDefinition } from "../types/report";

function failed(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "never";
}

export function SubscribeDialog({ reportId, reportName, onClose }: { reportId: string; reportName: string; onClose: () => void }) {
  const [items, setItems] = useState<Subscription[]>([]);
  const [mailReady, setMailReady] = useState(true);
  const [cron, setCron] = useState(SCHEDULES[1].cron);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    sharing
      .subscriptions()
      .then((body) => {
        setMailReady(body.mailReady);
        setItems(body.items.filter((item) => item.reportId === reportId));
      })
      .catch((reason: unknown) => setError(failed(reason, "Couldn't load your subscriptions")));
  }
  useEffect(load, [reportId]);

  async function run(action: () => Promise<unknown>, done: string, fallback: string) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      await action();
      setNote(done);
      load();
    } catch (reason: unknown) {
      setError(failed(reason, fallback));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal notify-dialog" role="dialog" aria-label={`Subscribe to ${reportName}`} onClick={(event) => event.stopPropagation()}>
        <h3>Subscribe to “{reportName}”</h3>
        <p className="ws-muted">The report is emailed to you as a PDF, as you see it, on the schedule you choose.</p>
        {!mailReady && (
          <p className="ws-error" role="status">Mail isn't set up on this server yet, so subscriptions can't be sent. Ask an admin to set MAGBI_SMTP_HOST.</p>
        )}
        <div className="form-row">
          <select className="ws-input" aria-label="Schedule" value={cron} onChange={(event) => setCron(event.target.value)} disabled={!mailReady}>
            {SCHEDULES.map((item) => <option key={item.cron} value={item.cron}>{item.label}</option>)}
          </select>
          <button
            type="button"
            className="ws-btn primary"
            disabled={busy || !mailReady}
            onClick={() => void run(() => sharing.subscribe(reportId, cron), "Subscribed.", "Couldn't subscribe")}
          >
            Subscribe
          </button>
        </div>
        {error && <p className="ws-error">{error}</p>}
        {note && <p className="ws-muted" role="status">{note}</p>}
        {items.length > 0 && (
          <table className="ws-table">
            <thead>
              <tr><th>Schedule</th><th>Last sent</th><th></th></tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{scheduleLabel(item.cron)}</td>
                  <td className="ws-muted">
                    {when(item.lastSentAt)}
                    {item.lastError && <span className="ws-test-fail" title={item.lastError}> · not sent: {item.lastError}</span>}
                  </td>
                  <td className="notify-actions">
                    <button type="button" className="ws-btn small" disabled={busy}
                      onClick={() => void run(() => sharing.sendNow(item.id), "Sent. Check your inbox.", "Couldn't send")}>
                      Send now
                    </button>
                    <button type="button" className="ws-btn small" disabled={busy}
                      onClick={() => void run(() => sharing.unsubscribe(item.id), "Unsubscribed.", "Couldn't unsubscribe")}>
                      Unsubscribe
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="modal-footer">
          <button type="button" className="ws-btn" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}

export function AlertDialog({ reportId, report, onClose }: { reportId: string; report: ReportDefinition; onClose: () => void }) {
  const visuals = useMemo(() => alertableVisuals(report), [report]);
  const [items, setItems] = useState<DataAlert[]>([]);
  const [visualId, setVisualId] = useState(visuals[0]?.id ?? "");
  const [condition, setCondition] = useState<Condition>("gt");
  const [threshold, setThreshold] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    sharing
      .alerts()
      .then((all) => setItems(all.filter((item) => item.reportId === reportId)))
      .catch((reason: unknown) => setError(failed(reason, "Couldn't load your alerts")));
  }
  useEffect(load, [reportId]);

  const value = Number(threshold);
  const valid = visualId !== "" && threshold.trim() !== "" && Number.isFinite(value);

  async function add() {
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    try {
      await sharing.addAlert({ reportId, visualId, condition, threshold: value });
      setThreshold("");
      load();
    } catch (reason: unknown) {
      setError(failed(reason, "Couldn't add the alert"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await sharing.deleteAlert(id);
      load();
    } catch (reason: unknown) {
      setError(failed(reason, "Couldn't remove the alert"));
    }
  }

  const label = (id: Condition) => CONDITIONS.find((item) => item.id === id)?.label.toLowerCase() ?? id;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal notify-dialog" role="dialog" aria-label="Data alerts" onClick={(event) => event.stopPropagation()}>
        <h3>Data alerts</h3>
        <p className="ws-muted">
          Get a notification, and an email when mail is set up, when a card's value crosses a threshold. Alerts are checked after each data refresh.
        </p>
        {visuals.length === 0 ? (
          <p className="ws-muted">This report has no cards, KPI cards or gauges to watch.</p>
        ) : (
          <div className="form-row notify-alert-row">
            <select className="ws-input" aria-label="Card to watch" value={visualId} onChange={(event) => setVisualId(event.target.value)}>
              {visuals.map((visual) => (
                <option key={visual.id} value={visual.id}>{visual.title}{report.pages.length > 1 ? ` (${visual.page})` : ""}</option>
              ))}
            </select>
            <select className="ws-input" aria-label="Condition" value={condition} onChange={(event) => setCondition(event.target.value as Condition)}>
              {CONDITIONS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            <input className="ws-input" aria-label="Threshold" type="number" inputMode="decimal" placeholder="Threshold" value={threshold}
              onChange={(event) => setThreshold(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void add()} />
            <button type="button" className="ws-btn primary" disabled={!valid || busy} onClick={() => void add()}>Add alert</button>
          </div>
        )}
        {error && <p className="ws-error">{error}</p>}
        {items.length > 0 && (
          <table className="ws-table">
            <thead>
              <tr><th>Alert</th><th>Now</th><th>Last fired</th><th></th></tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.visualTitle ?? "A removed card"} {label(item.condition)} {item.threshold.toLocaleString()}</td>
                  <td className="ws-muted">{item.lastValue === null ? "—" : item.lastValue.toLocaleString()}</td>
                  <td className="ws-muted">{when(item.lastFiredAt)}</td>
                  <td><button type="button" className="ws-btn small" onClick={() => void remove(item.id)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="modal-footer">
          <button type="button" className="ws-btn" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
