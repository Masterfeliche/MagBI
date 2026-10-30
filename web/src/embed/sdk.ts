/**
 * MagBI Embed SDK — host pages pass a pre-minted token. This module never
 * calls POST /embed/token.
 */

export interface EmbedOptions {
  reportId: string;
  accessToken: string;
  embedUrl?: string;
  filters?: unknown[];
  pageName?: string;
  allowedOrigins?: string[];
}

export type EmbedEvent = "loaded" | "error" | "filterChanged" | "visualClicked" | "tokenExpiring";

export interface EmbeddedReport {
  setFilters: (filters: unknown[]) => void;
  setPage: (pageName: string) => void;
  setToken: (token: string) => void;
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
): string {
  const url = new URL(`/embed/${reportId}`, origin);
  url.searchParams.set("token", accessToken);
  if (pageName) url.searchParams.set("page", pageName);
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
      on(event, handler) {
        (handlers[event] ??= []).push(handler);
      },
    };
  }
  const iframe = document.createElement("iframe");
  iframe.src =
    options.embedUrl ??
    embedUrlFor(options.reportId, options.accessToken, options.pageName, origin);
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
    on(event, handler) {
      (handlers[event] ??= []).push(handler);
    },
  };
}
