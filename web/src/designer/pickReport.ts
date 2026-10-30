/** Choose which saved report the designer opens. */

export interface SavedReport {
  id: string;
  dataset_id: string;
}

export function pickReport<T extends SavedReport>(
  reports: T[],
  datasetId: string,
  reportId: string | null,
): T | undefined {
  if (reportId) {
    const requested = reports.find((report) => report.id === reportId);
    if (requested) return requested;
  }
  return reports.find((report) => report.dataset_id === datasetId);
}
