/**
 * What each kind of connection asks for, and the config the server expects
 * (server/magbi/connectors/*.py: SqlServerConfig, PostgresConfig, MySqlConfig, ODataConfig).
 */

export type ConnectionKind = "sqlserver" | "postgresql" | "mysql" | "odata";

export const KIND_LABELS: Record<string, string> = {
  sqlserver: "SQL Server",
  postgresql: "PostgreSQL",
  mysql: "MySQL / MariaDB",
  odata: "OData or REST JSON (web)",
};

export const DEFAULT_PORTS: Record<string, number> = { sqlserver: 1433, postgresql: 5432, mysql: 3306 };

export interface ConnectionFields {
  host: string;
  port: number;
  database: string;
  authentication: string;
  username: string;
  password: string;
  encrypt: boolean;
  trustCert: boolean;
  sslmode: string;
  ssl: boolean;
  url: string;
  format: "odata" | "json";
  tableName: string;
  recordsPath: string;
  nextPath: string;
}

export function blankFields(kind: string): ConnectionFields {
  return {
    host: "",
    port: DEFAULT_PORTS[kind] ?? 0,
    database: "",
    authentication: kind === "odata" ? "none" : "sql",
    username: "",
    password: "",
    encrypt: true,
    trustCert: false,
    sslmode: "prefer",
    ssl: false,
    url: "",
    format: "odata",
    tableName: "records",
    recordsPath: "",
    nextPath: "",
  };
}

/** Whether the connection uses a user name and password (or, for the web, a token). */
export function needsLogin(kind: string, fields: ConnectionFields): boolean {
  if (kind === "sqlserver") return fields.authentication === "sql";
  if (kind === "odata") return fields.authentication !== "none";
  return true;
}

export function buildConnectionConfig(kind: string, f: ConnectionFields): Record<string, unknown> {
  const login = needsLogin(kind, f);
  if (kind === "postgresql") {
    return { host: f.host.trim(), port: f.port, database: f.database.trim(), username: f.username, password: f.password, sslmode: f.sslmode };
  }
  if (kind === "mysql") {
    return {
      host: f.host.trim(),
      port: f.port,
      ...(f.database.trim() ? { database: f.database.trim() } : {}),
      username: f.username,
      password: f.password,
      ssl: f.ssl,
    };
  }
  if (kind === "odata") {
    return {
      url: f.url.trim(),
      format: f.format,
      authentication: f.authentication,
      ...(f.authentication === "basic" ? { username: f.username } : {}),
      ...(login ? { password: f.password } : {}),
      ...(f.format === "json"
        ? { table_name: f.tableName.trim() || "records", records_path: f.recordsPath.trim(), next_path: f.nextPath.trim() }
        : {}),
    };
  }
  return {
    host: f.host.trim(),
    port: f.port,
    database: f.database.trim(),
    authentication: f.authentication,
    ...(login ? { username: f.username, password: f.password } : {}),
    encrypt: f.encrypt,
    trust_server_certificate: f.trustCert,
  };
}

/** The fields still missing before the connection can be tested or saved. */
export function missingFields(kind: string, f: ConnectionFields): string[] {
  const missing: string[] = [];
  if (kind === "odata") {
    if (!/^https?:\/\/[^/\s]+/i.test(f.url.trim())) missing.push("URL");
  } else {
    if (!f.host.trim()) missing.push("host");
    if (kind !== "mysql" && !f.database.trim()) missing.push("database");
  }
  if (needsLogin(kind, f)) {
    if (kind !== "odata" || f.authentication === "basic") {
      if (!f.username.trim()) missing.push("user name");
    }
    if (!f.password) missing.push(kind === "odata" && f.authentication === "bearer" ? "token" : "password");
  }
  return missing;
}
