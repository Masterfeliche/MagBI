import { visualSpec } from "./catalog";

export function VisualTypeIcon({ type, size = 32 }: { type: string; size?: number }) {
  const spec = visualSpec(type);
  return (
    <svg
      className="visual-type-icon"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
    >
      <path d={spec.icon} fill="currentColor" />
    </svg>
  );
}

export function VisualTypeButton({
  type,
  label,
  onClick,
}: {
  type: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className="visual-type-btn" title={label} onClick={onClick}>
      <VisualTypeIcon type={type} />
      <span className="visual-type-label">{label}</span>
    </button>
  );
}
