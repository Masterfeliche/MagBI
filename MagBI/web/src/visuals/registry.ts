/**
 * Visual definition registry — maps visual type to its component,
 * well definitions, default options, and ECharts config builder.
 */
export interface VisualDefinition {
  type: string;
  displayName: string;
  icon: string;
  wells: WellDefinition[];
  buildOption: (data: unknown, bindings: unknown) => unknown;
}

export interface WellDefinition {
  name: string;
  displayName: string;
  type: "grouping" | "measure" | "any";
  min: number;
  max: number;
}

const registry = new Map<string, VisualDefinition>();

export function registerVisual(def: VisualDefinition) {
  registry.set(def.type, def);
}

export function getVisual(type: string) {
  return registry.get(type);
}

export function allVisuals() {
  return Array.from(registry.values());
}
