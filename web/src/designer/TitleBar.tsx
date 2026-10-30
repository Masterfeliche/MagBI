import { useDesignerStore } from "./store";

export function TitleBar() {
  const report = useDesignerStore((s) => s.report);
  const undo = useDesignerStore((s) => s.undo);
  const redo = useDesignerStore((s) => s.redo);
  const history = useDesignerStore((s) => s.history);

  return (
    <div className="titlebar">
      <span className="logo">MagBI</span>
      <span className="file-name">{report.name}</span>
      <div className="tb-actions">
        <button type="button" disabled={history.past.length === 0} onClick={undo} title="Undo (Ctrl+Z)">
          Undo
        </button>
        <button type="button" disabled={history.future.length === 0} onClick={redo} title="Redo (Ctrl+Y)">
          Redo
        </button>
      </div>
    </div>
  );
}
