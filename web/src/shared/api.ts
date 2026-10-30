/**
 * API client — typed fetch wrapper with JWT token injection.
 */
const BASE = "/api/v1";
const TOKEN_KEY = "magbi.token";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = window.localStorage.getItem(TOKEN_KEY);
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  if (res.status === 204) return undefined as T;
  return res.json();
}
