/** The DAX functions the server supports, for autocomplete and the function list. */

import { apiFetch } from "../shared/api";

export interface DaxFunction {
  name: string;
  signature: string;
  description: string;
}

let cached: Promise<DaxFunction[]> | null = null;

export function loadDaxFunctions(): Promise<DaxFunction[]> {
  cached ??= apiFetch<{ supported: DaxFunction[] }>("/dax/functions")
    .then((body) => body.supported)
    .catch(() => {
      cached = null;
      return [];
    });
  return cached;
}

/** Functions whose name or description contains the search, names first. */
export function searchFunctions(all: DaxFunction[], search: string): DaxFunction[] {
  const term = search.trim().toLowerCase();
  if (!term) return all;
  const byName = all.filter((item) => item.name.toLowerCase().includes(term));
  const byText = all.filter((item) => !byName.includes(item) && item.description.toLowerCase().includes(term));
  return [...byName, ...byText];
}

/** What to type for a function: its name and an open bracket. */
export function insertText(item: DaxFunction): string {
  return `${item.name}(`;
}
