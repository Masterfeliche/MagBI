/** API request/response types. */

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface Workspace {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface DatasetSummary {
  id: string;
  name: string;
  description?: string;
  mode?: string;
  current_version?: number;
  schedule_cron?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ReportSummary {
  id: string;
  name: string;
  dataset_id: string;
  is_published?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface EmbedToken {
  token: string;
  expiresAt: string;
  embedUrl: string;
}
