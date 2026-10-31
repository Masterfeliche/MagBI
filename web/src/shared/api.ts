/**
 * API client — typed fetch wrapper with JWT token injection.
 */
import { clearToken, getToken, isEmbedded } from "./session";

const BASE = "/api/v1";

export function buildApiHeaders(token: string | null, init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  const form = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (form) {
    headers.delete("Content-Type");
  } else if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: buildApiHeaders(token, init),
  });
  if (res.status === 401 && token && !isEmbedded() && !new Headers(init?.headers).has("Authorization")) {
    // The session expired or was revoked: sign in again and come back here.
    clearToken();
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
  if (!res.ok) throw new Error(await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json();
}

export function messageFromErrorBody(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const error = (payload as { error?: { message?: string; problems?: unknown; validation?: { errors?: Array<{ message?: string }> } } }).error;
  const first = error?.validation?.errors?.[0]?.message;
  if (typeof first === "string" && first) return first;
  // A refused theme lists every check it failed, one per line after the message.
  const problems = Array.isArray(error?.problems) ? error.problems.filter((item): item is string => typeof item === "string") : [];
  if (typeof error?.message === "string" && error.message) return [error.message, ...problems].join("\n");
  return null;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const parsed = messageFromErrorBody(await res.json());
    if (parsed) return parsed;
  } catch {
    /* body is not JSON */
  }
  return `API ${res.status}: ${res.statusText}`;
}
