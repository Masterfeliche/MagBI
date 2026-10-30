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
});
