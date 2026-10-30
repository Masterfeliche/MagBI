import { useEffect, useRef } from "react";

export interface ContextMenuAction {
  label: string;
  icon?: string;
  danger?: boolean;
  disabled?: boolean;
  divider?: boolean;
  onClick: () => void;
}

export function ContextMenu({
  x,
  y,
  actions,
  onClose,
}: {
  x: number;
  y: number;
  actions: ContextMenuAction[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);

  return (
    <div ref={ref} className="context-menu" style={{ left: x, top: y }}>
      {actions.map((action, i) => (
        <div key={i}>
          {action.divider && <div className="cm-divider" />}
          <button
            type="button"
            className={`cm-item${action.danger ? " danger" : ""}${action.disabled ? " disabled" : ""}`}
            disabled={action.disabled}
            onClick={() => { action.onClick(); onClose(); }}
          >
            {action.icon && <span className="cm-icon">{action.icon}</span>}
            {action.label}
          </button>
        </div>
      ))}
    </div>
  );
}
