/**
 * MagBI Embed SDK — host pages pass a pre-minted token. This module never
 * calls POST /embed/token.
 */

/** How the host app wants the report drawn. A locked organisation theme still wins, except High Contrast. */
export interface EmbedTheme {
  /** A built-in theme id ("health") or a saved one ("saved:<id>"). */
  id?: string;
  /** Changes on top, in the magbi.theme/1 shape, e.g. { data: { categorical: ["#0B5394"] } }. */
  overrides?: Record<string, unknown>;
  /** High Contrast for this reader. */
  contrast?: boolean;
}

export interface EmbedOptions {
  reportId: string;
  accessToken: string;
  embedUrl?: string;
  filters?: unknown[];
  pageName?: string;
  allowedOrigins?: string[];
  theme?: EmbedTheme;
}

export type EmbedEvent = "loaded" | "error" | "filterChanged" | "visualClicked" | "tokenExpiring";

export interface EmbeddedReport {
  setFilters: (filters: unknown[]) => void;
  setPage: (pageName: string) => void;
  setToken: (token: string) => void;
  setTheme: (theme: EmbedTheme) => void;
  on: (event: EmbedEvent, handler: (detail?: unknown) => void) => void;
}

export function originAllowed(allowed: string[] | undefined, origin: string): boolean {
  if (!allowed || allowed.length === 0 || allowed.includes("*")) return true;
  return allowed.includes(origin);
}

export function embedUrlFor(
  reportId: string,
  accessToken: string,
  pageName?: string,
  origin = "http://localhost",
  theme?: EmbedTheme,
): string {
  const url = new URL(`/embed/${reportId}`, origin);
  url.searchParams.set("token", accessToken);
  if (pageName) url.searchParams.set("page", pageName);
  if (theme?.id) url.searchParams.set("themeId", theme.id);
  if (theme?.contrast) url.searchParams.set("contrast", "1");
  return url.toString();
}

export function embed(container: HTMLElement, options: EmbedOptions): EmbeddedReport {
  const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
  const handlers: Partial<Record<EmbedEvent, Array<(detail?: unknown) => void>>> = {};
  const emit = (event: EmbedEvent, detail?: unknown) => {
    for (const handler of handlers[event] ?? []) handler(detail);
  };
  if (!originAllowed(options.allowedOrigins, origin)) {
    const error = new Error("this origin is not allowed to embed MagBI");
    queueMicrotask(() => emit("error", error));
    return {
      setFilters() {},
      setPage() {},
      setToken() {},
      setTheme() {},
      on(event, handler) {
        (handlers[event] ??= []).push(handler);
      },
    };
  }
  const iframe = document.createElement("iframe");
  iframe.src =
    options.embedUrl ??
    embedUrlFor(options.reportId, options.accessToken, options.pageName, origin, options.theme);
  iframe.style.border = "0";
  iframe.style.width = "100%";
  iframe.style.height = "100%";
  iframe.title = "MagBI report";
  container.replaceChildren(iframe);

  const post = (payload: Record<string, unknown>) => {
    iframe.contentWindow?.postMessage(payload, origin);
  };

  iframe.addEventListener("load", () => {
    if (options.filters) post({ type: "setFilters", filters: options.filters });
    if (options.theme?.overrides) post({ type: "setTheme", theme: options.theme });
    emit("loaded");
  });

  return {
    setFilters(filters) {
      post({ type: "setFilters", filters });
    },
    setPage(pageName) {
      post({ type: "setPage", pageName });
    },
    setToken(token) {
      post({ type: "setToken", token });
    },
    setTheme(theme) {
      post({ type: "setTheme", theme });
    },
    on(event, handler) {
      (handlers[event] ??= []).push(handler);
    },
  };
}
