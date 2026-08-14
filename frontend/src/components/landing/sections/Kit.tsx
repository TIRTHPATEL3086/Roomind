import type { ReactNode } from "react";

/**
 * Shared furniture for the long-form content region below the cinematic beats.
 *
 * The beats float over a live 3D canvas and are deliberately sparse. Everything
 * here sits on an OPAQUE surface instead: a wall of body copy over a moving
 * render is unreadable, and it makes the GPU work for pixels nobody can see.
 */

export function ContentSection({
  id,
  eyebrow,
  title,
  lede,
  children,
  tone = "base",
}: {
  id: string;
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  children?: ReactNode;
  /** `raised` gives alternating bands so sections separate without borders. */
  tone?: "base" | "raised";
}) {
  return (
    <section
      id={id}
      className={`relative scroll-mt-16 px-6 py-20 md:px-16 md:py-28 ${
        tone === "raised" ? "bg-[#0E1526]" : "bg-night"
      }`}
    >
      <div className="mx-auto max-w-6xl">
        <p
          data-reveal
          className="mb-3 font-mono text-[11px] uppercase tracking-[0.22em] text-glow"
        >
          {eyebrow}
        </p>
        <div className="grid gap-6 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] md:items-end">
          <h2
            data-reveal
            data-reveal-delay="60"
            className="font-display text-3xl font-bold leading-[1.12] md:text-5xl"
          >
            {title}
          </h2>
          {lede && (
            <p
              data-reveal
              data-reveal-delay="120"
              className="max-w-xl text-sm leading-relaxed text-ink-muted md:text-[15px]"
            >
              {lede}
            </p>
          )}
        </div>
        {children && <div className="mt-12 md:mt-16">{children}</div>}
      </div>
    </section>
  );
}

/** Accent word inside a heading. */
export function Hi({ children }: { children: ReactNode }) {
  return <span className="text-aria">{children}</span>;
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-panel border border-white/10 bg-white/[0.03] p-5
                  transition-colors duration-300 hover:border-aria/40
                  hover:bg-white/[0.055] ${className}`}
    >
      {children}
    </div>
  );
}

/** Small monospace pill — capability names, joint names, object ids. */
export function Chip({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "accent";
}) {
  const styles =
    tone === "accent"
      ? "border-glow/40 bg-glow/10 text-glow"
      : "border-white/12 bg-white/[0.05] text-ink-muted";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5
                  font-mono text-[10px] ${styles}`}
    >
      {children}
    </span>
  );
}

/**
 * Marks a section as intent rather than shipped capability.
 *
 * Worth the pixels: everything else on this page describes code that exists
 * and is tested, and quietly mixing a roadmap in with it would make the
 * honest claims harder to trust, not easier.
 */
export function RoadmapTag() {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border
                 border-amber-400/30 bg-amber-400/10 px-2.5 py-1
                 font-mono text-[10px] uppercase tracking-wider text-amber-300"
    >
      Roadmap
    </span>
  );
}
