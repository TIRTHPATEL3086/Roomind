import type { ReactNode } from "react";

/** The glass surface from spec 13.1. One definition, used everywhere. */
export function Panel({
  children,
  className = "",
  title,
  right,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  right?: ReactNode;
}) {
  return (
    <div className={`rm-glass ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2">
          {title && (
            <h2 className="font-display text-xs font-semibold uppercase tracking-wider text-ink-muted">
              {title}
            </h2>
          )}
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Chip({
  children,
  color,
  onClick,
  title,
  disabled,
}: {
  children: ReactNode;
  color?: string;
  onClick?: () => void;
  title?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
      className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs
                 transition hover:border-white/25 hover:bg-white/[0.09]
                 disabled:cursor-not-allowed disabled:opacity-40"
      style={color ? { color } : undefined}
    >
      {children}
    </button>
  );
}

export function StatDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
      <span
        className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-danger"}`}
      />
      {label}
    </span>
  );
}
