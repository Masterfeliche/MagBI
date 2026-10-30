import { useState } from "react";

import { useDesignerStore } from "./store";
import { VISUALS } from "./catalog";

type RibbonTab = "home" | "insert" | "modeling" | "view" | "format" | "help";

export function Ribbon({ onPublish, onToggleSelection }: { onPublish: () => void; onToggleSelection: () => void }) {
  const [active, setActive] = useState<RibbonTab>("home");
  const addVisual = useDesignerStore((s) => s.addVisual);

  return (
    <div className="ribbon">
      <div className="ribbon-tabs">
        {(["home", "insert", "modeling", "view", "format", "help"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`ribbon-tab${active === tab ? " active" : ""}`}
            onClick={() => setActive(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <div className={`ribbon-content${active === "home" ? " active" : ""}`}>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Paste</span></button>
            <button type="button" className="rb"><span>Copy</span></button>
            <button type="button" className="rb"><span>Cut</span></button>
          </div>
          <span className="ribbon-group-label">Clipboard</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            {VISUALS.slice(0, 6).map((v) => (
              <button key={v.type} type="button" className="rb" onClick={() => addVisual(v.type)}>
                <span>{v.displayName}</span>
              </button>
            ))}
          </div>
          <span className="ribbon-group-label">Visuals</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Measure</span></button>
            <button type="button" className="rb"><span>Get data</span></button>
            <button type="button" className="rb"><span>Refresh</span></button>
          </div>
          <span className="ribbon-group-label">Data</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb" onClick={onPublish}><span>Publish</span></button>
            <button type="button" className="rb"><span>Export</span></button>
          </div>
          <span className="ribbon-group-label">Share</span>
        </div>
      </div>

      <div className={`ribbon-content${active === "insert" ? " active" : ""}`}>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Text box</span></button>
            <button type="button" className="rb"><span>Image</span></button>
            <button type="button" className="rb"><span>Shape</span></button>
            <button type="button" className="rb"><span>Button</span></button>
          </div>
          <span className="ribbon-group-label">Elements</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            {VISUALS.map((v) => (
              <button key={v.type} type="button" className="rb" onClick={() => addVisual(v.type)}>
                <span>{v.displayName}</span>
              </button>
            ))}
          </div>
          <span className="ribbon-group-label">Visuals</span>
        </div>
      </div>

      <div className={`ribbon-content${active === "modeling" ? " active" : ""}`}>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Measure</span></button>
            <button type="button" className="rb"><span>Table</span></button>
            <button type="button" className="rb"><span>Column</span></button>
          </div>
          <span className="ribbon-group-label">Calculations</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Relationships</span></button>
            <button type="button" className="rb"><span>Security</span></button>
          </div>
          <span className="ribbon-group-label">Relationships</span>
        </div>
      </div>

      <div className={`ribbon-content${active === "view" ? " active" : ""}`}>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Reading</span></button>
            <button type="button" className="rb"><span>Mobile</span></button>
          </div>
          <span className="ribbon-group-label">Page views</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Gridlines</span></button>
            <button type="button" className="rb"><span>Snap</span></button>
            <button type="button" className="rb"><span>Bookmarks</span></button>
            <button type="button" className="rb" onClick={onToggleSelection}><span>Selection</span></button>
          </div>
          <span className="ribbon-group-label">Show</span>
        </div>
      </div>

      <div className={`ribbon-content${active === "format" ? " active" : ""}`}>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Cond fmt</span></button>
            <button type="button" className="rb"><span>Tooltips</span></button>
          </div>
          <span className="ribbon-group-label">Conditional</span>
        </div>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>Theme</span></button>
            <button type="button" className="rb"><span>Wallpaper</span></button>
          </div>
          <span className="ribbon-group-label">Theme</span>
        </div>
      </div>

      <div className={`ribbon-content${active === "help" ? " active" : ""}`}>
        <div className="ribbon-group">
          <div className="ribbon-btns">
            <button type="button" className="rb"><span>About</span></button>
            <button type="button" className="rb"><span>Docs</span></button>
            <button type="button" className="rb"><span>Help</span></button>
          </div>
          <span className="ribbon-group-label">Support</span>
        </div>
      </div>
    </div>
  );
}
