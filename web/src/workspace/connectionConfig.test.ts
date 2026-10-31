import { describe, expect, it } from "vitest";

import { blankFields, buildConnectionConfig, missingFields } from "./connectionConfig";

describe("buildConnectionConfig", () => {
  it("builds each kind's config the way the server validates it", () => {
    const pg = { ...blankFields("postgresql"), host: " pg.local ", database: "erp", username: "bi", password: "x" };
    expect(buildConnectionConfig("postgresql", pg)).toEqual({ host: "pg.local", port: 5432, database: "erp", username: "bi", password: "x", sslmode: "prefer" });

    const my = { ...blankFields("mysql"), host: "my.local", username: "bi", password: "x" };
    expect(buildConnectionConfig("mysql", my)).toEqual({ host: "my.local", port: 3306, username: "bi", password: "x", ssl: false });

    const open = { ...blankFields("odata"), url: "https://data.example.org/odata/" };
    expect(buildConnectionConfig("odata", open)).toEqual({ url: "https://data.example.org/odata/", format: "odata", authentication: "none" });

    const rest = { ...blankFields("odata"), url: "https://x.org/api", format: "json" as const, authentication: "bearer", password: "t", recordsPath: "data.items" };
    expect(buildConnectionConfig("odata", rest)).toEqual({
      url: "https://x.org/api", format: "json", authentication: "bearer", password: "t", table_name: "records", records_path: "data.items", next_path: "",
    });

    const windows = { ...blankFields("sqlserver"), host: "sql", database: "ERP", authentication: "integrated", username: "u", password: "p" };
    expect(buildConnectionConfig("sqlserver", windows)).not.toHaveProperty("password");
  });
});

describe("missingFields", () => {
  it("names what each kind still needs", () => {
    expect(missingFields("postgresql", blankFields("postgresql"))).toEqual(["host", "database", "user name", "password"]);
    expect(missingFields("mysql", { ...blankFields("mysql"), host: "h", username: "u", password: "p" })).toEqual([]);
    expect(missingFields("odata", { ...blankFields("odata"), url: "ftp://x" })).toEqual(["URL"]);
    expect(missingFields("odata", { ...blankFields("odata"), url: "https://x.org", authentication: "bearer" })).toEqual(["token"]);
    expect(missingFields("odata", { ...blankFields("odata"), url: "https://x.org", authentication: "basic", password: "p" })).toEqual(["user name"]);
  });
});
