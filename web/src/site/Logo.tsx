export function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      <rect width="36" height="36" rx="8" fill="#FFFFFF" />
      <rect x="8" y="19" width="5" height="9" rx="1" fill="#3F6FB0" />
      <rect x="15.5" y="13" width="5" height="15" rx="1" fill="#3F6FB0" />
      <rect x="23" y="8" width="5" height="20" rx="1" fill="#E8913A" />
    </svg>
  );
}
