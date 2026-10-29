/**
 * MagBI Embed SDK — standalone JS for embedding reports in iframes.
 *
 * Usage:
 *   const report = magbi.embed(container, {
 *     embedUrl: "...",
 *     token: "...",
 *     filters: [...],
 *   });
 *   report.on("loaded", () => { ... });
 *   report.setFilters([...]);
 */
export interface EmbedConfig {
  embedUrl: string;
  token: string;
  filters?: unknown[];
  theme?: string;
}

export function embed(_container: HTMLElement, _config: EmbedConfig) {
  // Placeholder — creates iframe, wires postMessage token refresh
}
