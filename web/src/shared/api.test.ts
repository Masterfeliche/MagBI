import { describe, expect, it } from "vitest";

import { buildApiHeaders } from "./api";

describe("buildApiHeaders", () => {
  it("sets JSON content type for ordinary requests", () => {
    const headers = buildApiHeaders("tok");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer tok");
  });

  it("omits JSON content type for FormData uploads", () => {
    const body = new FormData();
    body.append("file", new Blob(["a"]), "sales.csv");
    const headers = buildApiHeaders(null, { method: "POST", body });
    expect(headers.has("Content-Type")).toBe(false);
  });
});
