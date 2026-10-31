import { PAGE_HEIGHT, PAGE_WIDTH } from "./layout";
import { useDesignerStore } from "./store";

export function StatusBar({
  datasetId,
  zoom,
  onZoomIn,
  onZoomOut,
  onFitToPage,
  refreshMessage,
  onDiscardDraft,
}: {
  datasetId: string;
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitToPage: () => void;
  refreshMessage?: string;
  onDiscardDraft?: () => void;
}) {
  const report = useDesignerStore((s) => s.report);
  const saveStatus = useDesignerStore((s) => s.saveStatus);
  const hasDraft = useDesignerStore((s) => s.hasDraft);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const page = report.pages[activePageIndex];
  const visualCount = page?.visuals.length ?? 0;

  return (
    <div className="statusbar">
      <div className={`sb-dot ${saveStatus}`} />
      <span>{report.name || "Report"}</span>
      <span className="sb-sep">|</span>
      <span>
        {saveStatus === "saving"
          ? "Saving draft..."
          : saveStatus === "dirty"
            ? "Unsaved changes"
            : hasDraft
              ? "Draft saved, not published: viewers still see the published report"
              : "Published"}
      </span>
      {hasDraft && onDiscardDraft && (
        <button type="button" className="sb-link" onClick={onDiscardDraft}>
          Discard draft
        </button>
      )}
      <span className="sb-sep">|</span>
      <span>Connected to {datasetId || "—"}</span>
      {refreshMessage && <span className="sb-sep">|</span>}
      {refreshMessage && <span>{refreshMessage}</span>}
      <span className="sb-sep">|</span>
      <span>{visualCount} visual{visualCount !== 1 ? "s" : ""}</span>
      <div className="sb-right">
        <div className="sb-zoom">
          <button type="button" className="sb-zoom-btn" onClick={onZoomOut} title="Zoom out">−</button>
          <span className="sb-zoom-pct">{Math.round(zoom * 100)}%</span>
          <button type="button" className="sb-zoom-btn" onClick={onZoomIn} title="Zoom in">+</button>
          <button type="button" className="sb-zoom-btn sb-fit" onClick={onFitToPage} title="Fit to page">⊡</button>
        </div>
        <span className="sb-sep">|</span>
        <span>{PAGE_WIDTH} × {PAGE_HEIGHT}</span>
        <span className="sb-sep">|</span>
        <span>Page {activePageIndex + 1} of {report.pages.length}</span>
      </div>
    </div>
  );
}
