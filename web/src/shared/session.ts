/** The signed-in user's token: kept across restarts only when they ask for it. */

const TOKEN_KEY = "magbi.token";

function stores(): Storage[] {
  const found: Storage[] = [];
  try {
    found.push(window.sessionStorage);
  } catch {
    /* storage blocked */
  }
  try {
    found.push(window.localStorage);
  } catch {
    /* storage blocked */
  }
  return found;
}

export function getToken(): string | null {
  for (const store of stores()) {
    const token = store.getItem(TOKEN_KEY);
    if (token) return token;
  }
  return null;
}

export function saveToken(token: string, remember: boolean): void {
  clearToken();
  const [session, local] = [window.sessionStorage, window.localStorage];
  (remember ? local : session).setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  for (const store of stores()) store.removeItem(TOKEN_KEY);
}

export function hasSession(): boolean {
  return getToken() !== null;
}

export class SignInError extends Error {
  constructor(
    message: string,
    readonly wrongCredentials: boolean,
  ) {
    super(message);
  }
}

/** POST /auth/login. A 401 means the email or password is wrong. */
export async function signIn(email: string, password: string, remember: boolean): Promise<void> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim(), password }),
  });
  if (res.status === 401) throw new SignInError("That email and password don't match.", true);
  if (!res.ok) throw new SignInError(`MagBI could not sign you in (error ${res.status}). Try again in a moment.`, false);
  const body = (await res.json()) as { token?: string };
  if (!body.token) throw new SignInError("MagBI could not sign you in. Try again in a moment.", false);
  saveToken(body.token, remember);
}
