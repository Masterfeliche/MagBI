/** API request/response types. */

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface Workspace {
  id: string;
  name: string;
  role: "admin" | "editor" | "viewer" | "embed-only";
}

export interface DatasetSummary {
  id: string;
  name: string;
  lastRefresh?: string;
  refreshStatus?: "idle" | "running" | "failed";
}

export interface ReportSummary {
  id: string;
  name: string;
  datasetId: string;
  updatedAt: string;
}

export interface EmbedToken {
  token: string;
  expiresAt: string;
  embedUrl: string;
}
