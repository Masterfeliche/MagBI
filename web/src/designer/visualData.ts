/** Last query result per visual, used for Export data. */

const cache = new Map<string, { columns: string[]; rows: unknown[][] }>();

export function rememberVisualData(id: string, columns: string[], rows: unknown[][]): void {
  cache.set(id, { columns, rows });
}

export function visualDataOf(id: string): { columns: string[]; rows: unknown[][] } | undefined {
  return cache.get(id);
}
