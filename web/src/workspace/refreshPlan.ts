/** Pure helpers for refresh scheduling and adding tables to a definition. */

export const SCHEDULE_PRESETS: { id: string; label: string; cron: string }[] = [
  { id: "hourly", label: "Hourly", cron: "0 * * * *" },
  { id: "6h", label: "Every 6 hours", cron: "0 */6 * * *" },
  { id: "daily", label: "Daily at 06:00", cron: "0 6 * * *" },
  { id: "weekly", label: "Weekly on Monday", cron: "0 6 * * 1" },
];

export interface SourceTable {
  schema: string;
  name: string;
}

interface DefinitionTable {
  name?: string;
  source?: { schema?: string; table?: string };
}

export function mergeImportTables(
  definition: Record<string, unknown>,
  picks: SourceTable[],
): { definition: Record<string, unknown>; added: string[] } {
  const current = Array.isArray(definition.tables) ? [...(definition.tables as DefinitionTable[])] : [];
  const seen = new Set(current.map((table) => (table.name ?? "").toLowerCase()));
  const added: string[] = [];
  for (const pick of picks) {
    const key = pick.name.toLowerCase();
    if (!pick.name || seen.has(key)) continue;
    current.push({
      name: pick.name,
      source: { type: "table", schema: pick.schema, table: pick.name },
      columns: [],
      measures: [],
    } as DefinitionTable);
    seen.add(key);
    added.push(pick.name);
  }
  return { definition: { ...definition, tables: current }, added };
}

export function isRefreshDone(status: string): boolean {
  return status === "succeeded" || status === "failed";
}
