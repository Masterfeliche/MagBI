import { describe, expect, it } from "vitest";

import { blankReport } from "./layout";
import { EMPTY_HISTORY, record, redo, undo } from "./history";

describe("undo", () => {
  it("restores the previous document and reapplies it", () => {
    const before = blankReport("Board", "ds");
    const page = before.pages[0];
    if (!page) throw new Error("missing page");
    const after = {
      ...before,
      pages: [
        {
          ...page,
          visuals: [{ id: "a", type: "card", x: 0, y: 0, width: 360, height: 140, wells: {} }],
        },
      ],
    };
    const saved = record(before, after, EMPTY_HISTORY);
    const back = undo(after, saved);
    expect(back.doc.pages[0]?.visuals).toEqual([]);
    const forward = redo(back.doc, back.history);
    expect(forward.doc.pages[0]?.visuals).toHaveLength(1);
    expect(undo(before, EMPTY_HISTORY).doc).toBe(before);
  });
});
