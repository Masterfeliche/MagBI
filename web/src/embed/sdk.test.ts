import { describe, expect, it } from "vitest";

import { embedUrlFor, originAllowed } from "./sdk";

describe("embed SDK helpers", () => {
  it("builds an embed URL with the host-minted token", () => {
    expect(embedUrlFor("r1", "tok", "Page1", "https://bi.example")).toBe(
      "https://bi.example/embed/r1?token=tok&page=Page1",
    );
  });

  it("blocks a host origin that is not on the allow list", () => {
    expect(originAllowed(["https://erp.example"], "https://evil.example")).toBe(false);
    expect(originAllowed(["*"], "https://erp.example")).toBe(true);
  });
});
