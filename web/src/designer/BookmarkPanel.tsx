import { useState } from "react";

import { useDesignerStore } from "./store";

export function BookmarkPanel({ onClose }: { onClose: () => void }) {
  const bookmarks = useDesignerStore((state) => state.report.bookmarks ?? []);
  const addBookmark = useDesignerStore((state) => state.addBookmark);
  const applyBookmark = useDesignerStore((state) => state.applyBookmark);
  const [name, setName] = useState("Bookmark");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>Bookmarks</h3>
        <div className="form-row">
          <input className="ws-input" value={name} onChange={(event) => setName(event.target.value)} />
          <button type="button" className="ws-btn primary" onClick={() => addBookmark(name.trim() || "Bookmark")}>
            Capture
          </button>
        </div>
        {bookmarks.map((bookmark) => (
          <button
            key={bookmark.id}
            type="button"
            className="ws-btn"
            onClick={() => {
              applyBookmark(bookmark.id);
              onClose();
            }}
          >
            {bookmark.name}
          </button>
        ))}
        <div className="form-actions">
          <button type="button" className="ws-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
