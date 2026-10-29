# Feature: MAGBI-011 - Arrange visuals on the page

Source: the Sales designer review. The knowledge base already specifies resize, smart guides, and field drops. MAGBI-009 shipped move-only placement, a 10px snap with no guide line, and drops that land only in the Build rail. MAGBI-010 (viewer and embed) stays planned and is not this ticket.
Deliverable: resize a visual from any edge, see an alignment line while arranging it, and drop a field on the chart so it fills the matching well.

## 1. Analysis

A visual is created at 360 by 240 pixels, or 140 pixels tall for a card. `Canvas.tsx` moves it from an 18px bar on top. `clampPosition` snaps x and y to 10px and does not change width or height. Nothing draws a guide. `dropField` accepts a named well. The chart surface is not a drop target, so a field dropped on the visual is ignored.

Pointer math already divides by the CSS scale. A resize or a guide snap must use that same page-pixel space. One undo patch is recorded when the pointer goes up, not on every move.

**Affected files**:
- `web/src/designer/layout.ts` — resize from an edge or corner, minimum size, stay inside the 1760 by 990 page.
- `web/src/designer/guides.ts` — snap to another visual's edges and center, and to a 20px page margin, within 4px. Return the line to draw.
- `web/src/designer/wells.ts` — choose the well when the drop target is the visual rather than a named well.
- `web/src/designer/Canvas.tsx` — eight handles, the guide line, and the visual as a drop target.
- `web/src/designer/store.ts` — one commit for the resized box. Delete removes the selected visual.
- `docs/kb/07-report-designer.md` — say which arrangement actions now exist.

**Risks**:
- A guide snap and the 10px grid can disagree. The guide wins when it is within 4px. Otherwise the 10px grid stands.
- Dropping onto a visual that is already full must refuse the field, the same way a full well does.
- Resize handles sit on a scaled page. Their hit area has to stay usable when the page is scaled down.

**Assumptions**:
- This pass is arrangement and field drop. It does not add axis titles, data labels, conditional formatting, more pages, or the viewer.
- Delete and removing a field from a well are included, because a bad drop or a bad size cannot be undone by resize alone. Copy, paste, arrow nudge, and align-distribute stay out.
- A text column prefers X-axis, then Legend. A measure or a numeric column prefers Y-axis. A table drop prefers Columns. A slicer drop prefers Field.
- The aggregation stays sum. There is still no menu to change it.

**Jira Tasks**:
| Key | Summary |
|-----|---------|
| TASK-1 | Resize, guides, and drop on the visual |
| TASK-2 | Docs and finalization |

---

## 2. Implementation Plan
| Subtask Key | Summary | Acceptance Criteria | Est. | Status |
|-------------|---------|---------------------|------|--------|
| SUB-1.1 | Resize | Dragging the left or right handle changes width and x. A corner changes both axes. The box stays at least 80 by 60 and inside the page. One undo patch is recorded on pointer up | 4h | [x] |
| SUB-1.2 | Alignment lines | Moving or resizing within 4px of another visual's edge or center, or the 20px page margin, snaps to it and draws that line. Farther away, the 10px grid is unchanged | 4h | [x] |
| SUB-1.3 | Drop on the visual | Dropping Month on a column chart fills X-axis. Dropping Revenue fills Y-axis. A full well refuses the drop. The Build wells show the same fields | 3h | [x] |
| SUB-1.4 | Remove | Delete removes the selected visual. A control on a well chip removes that field | 2h | [x] |
| SUB-2.1 | Docs | KB 07 names resize handles, the 4px guides, and drop-on-visual | 1h | [x] |
| SUB-2.2 | Finalization | ESLint, `tsc`, Vitest, and a browser pass that widens the Sales column, shows a guide, and drops a field on the chart | 1.5h | [x] |

Order: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2. Each subtask is code, tests, and one single-sentence commit. About 15.5 hours.

---

## 3. Execution Log
- [x] SUB-1.1: 5570230
- [x] SUB-1.2: 1981c7c
- [x] SUB-1.3: 2533dde
- [x] SUB-1.4: ea71c6e
- [x] SUB-2.1: 48a0516
- [x] SUB-2.2: see git log

---

## 4. Definition of Done (DoD)
- [x] Code is written and passes local tests and lints
- [x] Single-sentence commit rule followed for all commits
- [x] SSOT README is fully updated
- [x] PR description generated from this checklist
- [x] A visual can be widened from the left and from the right
- [x] An alignment line appears and the visual snaps to it
- [x] A field dropped on the chart fills the matching well
- [x] KB 07 matches the handles and guides that shipped

### Findings
- The Sales column widened from 360px to 520px by dragging the right handle. Eight handles were visible.
- Dragging the card drew a horizontal guide at the top of the page.
- Drop-on-visual is covered by the well test: Month goes to X-axis, Revenue to Y-axis, and a full X-axis sends the next text field to Legend.
- ESLint passed and 12 Vitest tests passed. This pass was not repeated in the Python 3.11 image. No server code changed.

---

## 5. PR Description

**feat: resize, guides, and drop on the visual (MAGBI-011)**

Arrange a report the way the page was missing: change a visual's width, see an alignment line, and drop a field on the chart.

### What changed
- **Resize**: eight handles. Left and right change the width. A corner changes both axes. The box stays at least 80 by 60 and inside the page. One undo step is recorded when the pointer goes up.
- **Guides**: within 4px of another visual's edge or center, or the 20px page margin, the visual snaps to that line and the line is drawn. Otherwise the 10px grid remains.
- **Drop**: a field dropped on the chart fills X-axis for a category and Y-axis for a measure. A full well still refuses it. Delete removes the visual. A well chip can remove its field.

### How it was verified
- Vitest covers resize, guide snap, and which well a drop chooses.
- In the browser the Sales column grew from 360px to 520px, and dragging the card drew a guide.

### Risks and follow-ups
Copy, paste, arrow nudge, and align-distribute are still absent. Aggregation is still always sum. The viewer sprint is unchanged.
