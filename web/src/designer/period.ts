/** Calendar order and a zero for every month the axis skips. */

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

interface MonthPoint {
  index: number;
  year?: number;
}

export function parseMonthLabel(label: string): MonthPoint | undefined {
  const match = /^([A-Za-z]{3,9})(?:\s+(\d{2}|\d{4}))?$/.exec(label.trim());
  if (!match) return undefined;
  const month = MONTHS.indexOf(match[1].slice(0, 3).toLowerCase());
  if (month < 0) return undefined;
  if (!match[2]) return { index: month };
  const year = match[2].length === 2 ? 2000 + Number(match[2]) : Number(match[2]);
  return { index: year * 12 + month, year };
}

function labelFor(index: number, withYear: boolean): string {
  const month = MONTHS[index % 12] ?? "jan";
  const text = month.charAt(0).toUpperCase() + month.slice(1);
  if (!withYear) return text;
  const year = Math.floor(index / 12) % 100;
  return `${text} ${String(year).padStart(2, "0")}`;
}

export function arrangeMonths(
  categories: string[],
  series: { name: string; values: number[] }[],
): { categories: string[]; series: { name: string; values: number[] }[] } | undefined {
  const points = categories.map(parseMonthLabel);
  if (points.some((point) => point === undefined)) return undefined;
  const parsed = points as MonthPoint[];
  const withYear = parsed.every((point) => point.year !== undefined);
  const withoutYear = parsed.every((point) => point.year === undefined);
  if (!withYear && !withoutYear) return undefined;
  const totals = new Map<number, number[]>();
  parsed.forEach((point, row) => {
    const values = totals.get(point.index) ?? series.map(() => 0);
    series.forEach((item, seriesIndex) => {
      values[seriesIndex] = (values[seriesIndex] ?? 0) + (item.values[row] ?? 0);
    });
    totals.set(point.index, values);
  });
  const keys = [...totals.keys()];
  const start = Math.min(...keys);
  const end = Math.max(...keys);
  const filled: number[] = [];
  for (let index = start; index <= end; index += 1) filled.push(index);
  return {
    categories: filled.map((index) => labelFor(index, withYear)),
    series: series.map((item, seriesIndex) => ({
      name: item.name,
      values: filled.map((index) => totals.get(index)?.[seriesIndex] ?? 0),
    })),
  };
}
