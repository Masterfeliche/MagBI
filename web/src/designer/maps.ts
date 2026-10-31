/**
 * Maps without a tile service: region boundaries come from one bundled file,
 * public/maps/tanzania-regions.json (GeoJSON, one feature per region, the name
 * in properties.name or properties.shapeName). Points are placed by latitude
 * and longitude, over the boundaries when the file is there.
 */

export const REGIONS_URL = "/maps/tanzania-regions.json";
export const MAP_NAME = "tanzania-regions";

interface Feature {
  properties?: Record<string, unknown>;
}
export interface Regions {
  type: string;
  features: Feature[];
}

/** A region name as both the data and the boundary file might spell it. */
export function regionKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/\bregion\b|\bmkoa wa\b/g, "")
    .replace(/[^a-z]/g, "");
}

export function featureName(feature: Feature): string {
  const props = feature.properties ?? {};
  const value = props.name ?? props.shapeName ?? props.NAME_1 ?? props.region ?? "";
  return String(value);
}

/**
 * Matches the data's names to the boundary file's, ignoring case, spaces,
 * hyphens and the word "Region". Names with no boundary are returned apart.
 */
export function matchRegions(
  regions: Regions,
  values: { name: string; value: number }[],
): { matched: { name: string; value: number }[]; unmatched: string[] } {
  const byKey = new Map(regions.features.map((feature) => [regionKey(featureName(feature)), featureName(feature)]));
  const matched: { name: string; value: number }[] = [];
  const unmatched: string[] = [];
  for (const item of values) {
    const name = byKey.get(regionKey(item.name));
    if (name) matched.push({ name, value: item.value });
    else unmatched.push(item.name);
  }
  return { matched, unmatched };
}

let loading: Promise<Regions | null> | null = null;

/** The boundary file, or null when it isn't installed. */
export function loadRegions(): Promise<Regions | null> {
  loading ??= fetch(REGIONS_URL)
    .then((response) => (response.ok ? (response.json() as Promise<Regions>) : null))
    .then((body) => (body && Array.isArray(body.features) && body.features.length > 0 ? body : null))
    .catch(() => null);
  return loading;
}
