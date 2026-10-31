/**
 * Sharing and staying informed: shares, apps, PDF export, subscriptions,
 * data alerts and notifications (server: magbi/api/sharing.py and notify.py).
 */
import type { ReportDefinition, VisualDefinition } from "../types/report";
import { apiFetch, buildApiHeaders, messageFromErrorBody } from "./api";
import { getToken } from "./session";

export interface Share {
  userId: string;
  email: string;
  name: string;
  sharedBy: string;
}

export interface SharedReport {
  reportId: string;
  reportName: string;
  workspaceId: string;
  workspaceName: string;
  sharedBy: string;
  sharedAt: string;
}

export interface MagApp {
  id: string;
  workspaceId: string;
  workspaceName: string;
  name: string;
  description: string | null;
  isPublished: boolean;
  reports: { id: string; name: string }[];
  audience: string[];
  updatedBy: string | null;
  updatedAt: string | null;
}

export interface AppDraft {
  name: string;
  description: string | null;
  reportIds: string[];
  audience: string[];
  isPublished: boolean;
}

export interface Subscription {
  id: string;
  reportId: string;
  reportName: string | null;
  workspaceId: string | null;
  cron: string;
  isActive: boolean;
  lastSentAt: string | null;
  lastError: string | null;
}

export type Condition = "gt" | "gte" | "lt" | "lte" | "eq" | "ne";

export interface DataAlert {
  id: string;
  reportId: string;
  reportName: string | null;
  visualId: string;
  visualTitle: string | null;
  condition: Condition;
  threshold: number;
  isActive: boolean;
  lastValue: number | null;
  lastMet: boolean;
  lastCheckedAt: string | null;
  lastFiredAt: string | null;
}

export interface AppNotification {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string | null;
  createdAt: string;
  read: boolean;
}

export const CONDITIONS: { id: Condition; label: string }[] = [
  { id: "gt", label: "Above" },
  { id: "gte", label: "At or above" },
  { id: "lt", label: "Below" },
  { id: "lte", label: "At or below" },
  { id: "eq", label: "Equal to" },
  { id: "ne", label: "Not equal to" },
];

/** Schedules offered for subscriptions, as five-field cron (server time). */
export const SCHEDULES: { cron: string; label: string }[] = [
  { cron: "0 7 * * *", label: "Every day at 07:00" },
  { cron: "0 7 * * 1-5", label: "Weekdays at 07:00" },
  { cron: "0 7 * * 1", label: "Mondays at 07:00" },
  { cron: "0 7 1 * *", label: "First of the month at 07:00" },
];

export function scheduleLabel(cron: string): string {
  return SCHEDULES.find((item) => item.cron === cron)?.label ?? cron;
}

const ALERTABLE = new Set(["card", "kpi", "gauge"]);

function valueBinding(visual: VisualDefinition) {
  return (visual.wells?.["y-axis"] ?? []).find((binding) => binding.table && (binding.measure || binding.column));
}

/** The visuals an alert can watch: cards, KPI cards and gauges that have a value. */
export function alertableVisuals(report: ReportDefinition): { id: string; title: string; page: string }[] {
  return report.pages.flatMap((page) =>
    page.visuals
      .filter((visual) => ALERTABLE.has(visual.type) && valueBinding(visual))
      .map((visual) => {
        const title = typeof visual.properties?.title === "string" && visual.properties.title.trim() ? visual.properties.title.trim() : "";
        const binding = valueBinding(visual);
        return { id: visual.id, title: title || binding?.measure || binding?.column || "Card", page: page.displayName ?? page.name };
      }),
  );
}

/** Email addresses typed one per line or separated by commas, de-duplicated. */
export function parseEmails(text: string): string[] {
  const seen = new Set<string>();
  for (const part of text.split(/[\s,;]+/)) {
    const email = part.trim().toLowerCase();
    if (email) seen.add(email);
  }
  return [...seen];
}

export const sharing = {
  shares: (wid: string, rid: string) => apiFetch<Share[]>(`/workspaces/${wid}/reports/${rid}/shares`),
  share: (wid: string, rid: string, email: string) =>
    apiFetch<Share>(`/workspaces/${wid}/reports/${rid}/shares`, { method: "POST", body: JSON.stringify({ email }) }),
  unshare: (wid: string, rid: string, userId: string) =>
    apiFetch<void>(`/workspaces/${wid}/reports/${rid}/shares/${userId}`, { method: "DELETE" }),
  sharedWithMe: () => apiFetch<SharedReport[]>("/me/shared"),

  myApps: () => apiFetch<MagApp[]>("/me/apps"),
  app: (id: string) => apiFetch<MagApp>(`/apps/${id}`),
  workspaceApps: (wid: string) => apiFetch<MagApp[]>(`/workspaces/${wid}/apps`),
  saveApp: (wid: string, draft: AppDraft, id?: string) =>
    apiFetch<MagApp>(id ? `/workspaces/${wid}/apps/${id}` : `/workspaces/${wid}/apps`, {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(draft),
    }),
  deleteApp: (wid: string, id: string) => apiFetch<void>(`/workspaces/${wid}/apps/${id}`, { method: "DELETE" }),

  subscriptions: () => apiFetch<{ mailReady: boolean; items: Subscription[] }>("/me/subscriptions"),
  subscribe: (reportId: string, cron: string) =>
    apiFetch<Subscription>("/me/subscriptions", { method: "POST", body: JSON.stringify({ reportId, cron }) }),
  sendNow: (id: string) => apiFetch<Subscription>(`/me/subscriptions/${id}/send`, { method: "POST" }),
  unsubscribe: (id: string) => apiFetch<void>(`/me/subscriptions/${id}`, { method: "DELETE" }),

  alerts: () => apiFetch<DataAlert[]>("/me/alerts"),
  addAlert: (body: { reportId: string; visualId: string; condition: Condition; threshold: number }) =>
    apiFetch<DataAlert>("/me/alerts", { method: "POST", body: JSON.stringify(body) }),
  deleteAlert: (id: string) => apiFetch<void>(`/me/alerts/${id}`, { method: "DELETE" }),

  notifications: () => apiFetch<{ unread: number; items: AppNotification[] }>("/me/notifications"),
  markRead: (ids?: string[]) =>
    apiFetch<void>("/me/notifications/read", { method: "POST", body: JSON.stringify(ids ? { ids } : {}) }),
};

/** Download the report as a PDF, as the signed-in person sees it. */
export async function downloadPdf(wid: string, rid: string, fallbackName: string): Promise<void> {
  const res = await fetch(`/api/v1/workspaces/${wid}/reports/${rid}/export.pdf`, { headers: buildApiHeaders(getToken()) });
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try {
      message = messageFromErrorBody(await res.json()) ?? message;
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  const named = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1];
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = named ?? `${fallbackName}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
