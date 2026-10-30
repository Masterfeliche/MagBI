export const STATUS_COLORS: Record<string, string> = {
  approved: "#10B981",
  pending: "#F59E0B",
  rejected: "#EF4444",
};

export function statusColor(value: string): string | undefined {
  return STATUS_COLORS[value.trim().toLowerCase()];
}

export function cardSignColor(value: string): string | undefined {
  const number = Number(value.replace(/[^0-9.-]/g, ""));
  if (!Number.isFinite(number) || number === 0) return undefined;
  return number < 0 ? "#EF4444" : "#10B981";
}

export function colorScale(values: number[], value: number): string {
  const finite = values.filter((item) => Number.isFinite(item));
  if (finite.length === 0) return "#E0E3E8";
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const t = max === min ? 0.5 : (value - min) / (max - min);
  const r = Math.round(17 + t * (239 - 17));
  const g = Math.round(141 + (1 - t) * (185 - 141));
  const b = Math.round(255 - t * (255 - 68));
  return `rgb(${r}, ${g}, ${b})`;
}

export function dataBarWidth(values: number[], value: number): string {
  const max = Math.max(0, ...values.filter((item) => Number.isFinite(item)));
  if (max <= 0) return "0%";
  return `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
}
