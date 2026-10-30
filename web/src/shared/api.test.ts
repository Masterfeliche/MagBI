import { describe, expect, it } from "vitest";

import { buildApiHeaders, messageFromErrorBody } from "./api";

describe("buildApiHeaders", () => {
  it("sets JSON content type for ordinary requests", () => {
    const headers = buildApiHeaders("tok");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer tok");
  });

  it("keeps an explicit Authorization header", () => {
    const headers = buildApiHeaders("stored", { headers: { Authorization: "Bearer embed" } });
    expect(headers.get("Authorization")).toBe("Bearer embed");
  });

  it("omits JSON content type for FormData uploads", () => {
    const body = new FormData();
    body.append("file", new Blob(["a"]), "sales.csv");
    const headers = buildApiHeaders(null, { method: "POST", body });
    expect(headers.has("Content-Type")).toBe(false);
  });
});

describe("messageFromErrorBody", () => {
  it("prefers the first validation error for invalid DAX", () => {
    expect(
      messageFromErrorBody({
        error: {
          message: "definition has errors",
          validation: { errors: [{ message: "Total: unknown column (line 1, column 5)" }] },
        },
      }),
    ).toBe("Total: unknown column (line 1, column 5)");
  });
});
