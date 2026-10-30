import { describe, expect, it } from "vitest";

import { blankReport } from "./layout";
import { useDesignerStore } from "./store";

describe("designer store", () => {
  it("clears every visual on the page in one undo step", () => {
    useDesignerStore.getState().replaceReport(blankReport("Board", "ds"));
    useDesignerStore.getState().addVisual("card");
    useDesignerStore.getState().addVisual("card");
    expect(useDesignerStore.getState().report.pages[0]?.visuals).toHaveLength(2);
    const past = useDesignerStore.getState().history.past.length;
    useDesignerStore.getState().removeAllVisuals();
    expect(useDesignerStore.getState().report.pages[0]?.visuals).toEqual([]);
    expect(useDesignerStore.getState().history.past).toHaveLength(past + 1);
    useDesignerStore.getState().undo();
    expect(useDesignerStore.getState().report.pages[0]?.visuals).toHaveLength(2);
  });

  it("drills a hierarchy, captures a bookmark, and imports theme colors", () => {
    useDesignerStore.getState().replaceReport(blankReport("Board", "ds"));
    useDesignerStore.getState().addVisual("column");
    const id = useDesignerStore.getState().report.pages[0]?.visuals[0]?.id ?? "";
    useDesignerStore.getState().setWells(id, {
      hierarchy: [
        { table: "Ledger", column: "Year" },
        { table: "Ledger", column: "Month" },
      ],
    });
    useDesignerStore.getState().drillDown(id, "2024");
    const drilled = useDesignerStore.getState().report.pages[0]?.visuals[0];
    expect(drilled?.properties?.drillLevel).toBe(1);
    expect(drilled?.filters?.[0]).toMatchObject({ column: "Year", config: { values: ["2024"] } });
    useDesignerStore.getState().setProperties(id, { hidden: true });
    useDesignerStore.getState().addBookmark("Month view");
    useDesignerStore.getState().setProperties(id, { hidden: false });
    const bookmarkId = useDesignerStore.getState().report.bookmarks?.[0]?.id ?? "";
    useDesignerStore.getState().applyBookmark(bookmarkId);
    expect(useDesignerStore.getState().report.pages[0]?.visuals[0]?.properties?.hidden).toBe(true);
    useDesignerStore.getState().importThemeJson(JSON.stringify({ dataColors: ["#111111", "#222222"] }));
    expect(useDesignerStore.getState().report.theme?.colors).toEqual(["#111111", "#222222"]);
  });
});
