import { useDesignerStore } from "./store";

export function PageTabs({ readOnly = false }: { readOnly?: boolean }) {
  const report = useDesignerStore((s) => s.report);
  const activePageIndex = useDesignerStore((s) => s.activePageIndex);
  const switchPage = useDesignerStore((s) => s.switchPage);
  const addPage = useDesignerStore((s) => s.addPage);

  return (
    <div className="page-tabs">
      {report.pages.map((page, index) => (
        <button
          key={page.name}
          type="button"
          className={`page-tab${index === activePageIndex ? " active" : ""}`}
          onClick={() => switchPage(index)}
        >
          {page.displayName}
        </button>
      ))}
      {!readOnly && (
        <button type="button" className="page-tab-add" onClick={addPage} title="Add page">
          +
        </button>
      )}
    </div>
  );
}
