import { ArrowRight, Play } from "lucide-react";

import { revealDelay } from "../useReveal";
import { Hi } from "./Kit";

const FOOTER_LINKS: { heading: string; items: string[] }[] = [
  {
    heading: "Platform",
    items: ["3D reconstruction", "AI companion", "Imagine: image → 3D", "Digital twin API"],
  },
  { heading: "ARIA", items: ["Kinematics", "Path planning", "Safety & e-stop", "Hardware specs"] },
  { heading: "Developers", items: ["Build spec", "REST API", "WebSocket events", "MQTT contract"] },
];

/** Final call to action plus the footer — one dark slab to close the page. */
export function Closing({ onEnter }: { onEnter: () => void }) {
  return (
    <section id="start" className="relative bg-[#070B16] px-6 md:px-16">
      <div className="mx-auto max-w-6xl border-b border-white/8 py-20 md:py-28">
        <div className="grid gap-10 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
          <div>
            <h2
              data-reveal
              className="font-display text-3xl font-bold leading-[1.12] md:text-5xl"
            >
              Ready to build your
              <br />
              <Hi>intelligent 3D world?</Hi>
            </h2>
            <p
              {...revealDelay(1)}
              className="mt-5 max-w-md text-sm leading-relaxed text-ink-muted"
            >
              The demo room is already loaded and ARIA is already docked in it.
              No sign-up, no install — the scene you have been scrolling through
              is the one you are about to walk into.
            </p>
          </div>

          <div {...revealDelay(2)} className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={onEnter}
              className="flex items-center gap-2 rounded-full bg-aria px-6 py-3
                         font-display text-sm font-semibold text-white
                         shadow-glowAria transition hover:scale-[1.03]
                         hover:bg-aria/90 active:scale-100"
            >
              <Play size={14} /> Launch demo world
            </button>
            <a
              href="#how"
              className="flex items-center gap-2 rounded-full border border-white/15
                         px-6 py-3 font-display text-sm font-semibold text-ink
                         transition hover:border-white/35"
            >
              How it works <ArrowRight size={14} />
            </a>
          </div>
        </div>
      </div>

      <footer className="mx-auto max-w-6xl py-12">
        <div className="grid gap-10 md:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,1fr))]">
          <div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-aria" />
              <span className="font-display text-sm font-bold tracking-tight">
                Room<span className="text-aria">Mind</span>
              </span>
            </div>
            <p className="mt-3 max-w-xs text-[13px] leading-relaxed text-ink-muted">
              An AI companion that sees, understands, and speaks from your room.
            </p>
            <span
              className="mt-4 inline-flex items-center gap-1.5 rounded-full border
                         border-aria/30 bg-aria/10 px-2.5 py-1 font-mono text-[10px]
                         text-aria"
            >
              ARIA · 9-joint humanoid
            </span>
          </div>

          {FOOTER_LINKS.map((col) => (
            <div key={col.heading}>
              <p className="font-mono text-[10px] uppercase tracking-widest text-ink-muted">
                {col.heading}
              </p>
              <ul className="mt-3 space-y-2">
                {col.items.map((item) => (
                  <li key={item} className="text-[13px] text-ink-muted">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div
          className="mt-10 flex flex-col gap-2 border-t border-white/8 pt-6
                     text-[11px] text-ink-muted sm:flex-row sm:justify-between"
        >
          <span>© 2026 RoomMind — “Turn any room into an intelligent 3D world”</span>
          <span>Arduino UNO Q · FastAPI · React Three Fiber</span>
        </div>
      </footer>
    </section>
  );
}
