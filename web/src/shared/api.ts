/**
 * API client — typed fetch wrapper with JWT token injection.
 */
const BASE = "/api/v1";
const TOKEN_KEY = "magbi.token";

export function buildApiHeaders(token: string | null, init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const form = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (form) {
    headers.delete("Content-Type");
  } else if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = window.localStorage.getItem(TOKEN_KEY);
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: buildApiHeaders(token, init),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const payload = (await res.json()) as { error?: { message?: string } };
    if (payload.error?.message) return payload.error.message;
  } catch {
    /* body is not JSON */
  }
  return `API ${res.status}: ${res.statusText}`;
}
