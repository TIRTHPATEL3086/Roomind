import type { ReactNode } from "react";
import { useRef } from "react";

import { gsap, useGSAP } from "../../motion/gsap";
import { DUR, EASE } from "../../motion/motionTokens";
import { motionDisabled } from "../../motion/reducedMotion";

/**
 * One landing beat.
 *
 * Every section owns EXACTLY ONE ScrollTrigger (spec 13.9). The budget is 8:
 * five of these (S1-S5), S2's standalone counter, and the camera rig = 7, one
 * spare. S0 is a raw <section> with a plain delayed timeline and no trigger.
 * Nothing here pins, because pin conflicts are the single largest source of
 * scroll jank. scripts/accept_phase4.py enforces the count.
 */
export function Section({
  id,
  align = "left",
  scrub = false,
  children,
}: {
  id: string;
  align?: "left" | "right" | "center";
  /** Scrub ties the reveal to wheel position. Only S1/S2/S4 use it. */
  scrub?: boolean;
  children: ReactNode;
}) {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const items = ".rm-reveal";

      if (motionDisabled()) {
        // Everything visible immediately, no scrub, no transform. The story
        // still reads top to bottom — it just doesn't move.
        gsap.set(items, { opacity: 1, y: 0, clearProps: "transform" });
        return;
      }

      gsap.timeline({
        scrollTrigger: {
          trigger: root.current,
          start: "top 72%",
          end: scrub ? "bottom 45%" : "top 45%",
          scrub: scrub ? 0.6 : false,
          toggleActions: scrub ? undefined : "play none none reverse",
        },
      }).from(items, {
        y: 26,
        opacity: 0,
        duration: DUR.base,
        ease: EASE.expo,
        stagger: 0.08,
      });
    },
    { scope: root }, // scope is required: selectors resolve inside this section
  );

  const justify =
    align === "right" ? "justify-end" : align === "center" ? "justify-center" : "justify-start";

  return (
    <section
      id={id}
      ref={root}
      className={`rm-section relative flex min-h-screen items-center px-6 md:px-16 ${justify}`}
    >
      <div className="max-w-lg">{children}</div>
    </section>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="rm-reveal mb-3 font-mono text-[11px] uppercase tracking-[0.2em] text-glow">
      {children}
    </p>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return (
    <h2 className="rm-reveal font-display text-3xl font-bold leading-tight md:text-5xl">
      {children}
    </h2>
  );
}

export function Body({ children }: { children: ReactNode }) {
  return (
    <p className="rm-reveal mt-4 max-w-md text-sm leading-relaxed text-ink-muted md:text-[15px]">
      {children}
    </p>
  );
}
