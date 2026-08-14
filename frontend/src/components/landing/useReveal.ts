import { useEffect, useLayoutEffect, useRef } from "react";

import { motionDisabled } from "../../motion/reducedMotion";

/**
 * Reveal `[data-reveal]` descendants as they scroll into view.
 *
 * ONE IntersectionObserver for the whole content region, not one ScrollTrigger
 * per section. Two reasons:
 *
 *  1. Budget. The landing is allowed 8 ScrollTriggers (spec 13.9) and the
 *     cinematic beats already use 7. A dozen content sections would need a
 *     dozen more.
 *  2. Fit. ScrollTrigger exists to tie animation to scroll POSITION. These are
 *     one-shot fades that only need to know "is it on screen yet" — which is
 *     the one question IntersectionObserver answers, off the main thread.
 *
 * Elements unobserve themselves once shown, so scrolling back up does not
 * re-animate text the reader has already read.
 */
export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  // Arm the hidden state in a layout effect, BEFORE paint. Doing it in a
  // passive effect lets one frame render at full opacity, which shows up as a
  // flash of the whole page before everything drops out and fades back in.
  useLayoutEffect(() => {
    if (ref.current && !motionDisabled()) {
      ref.current.setAttribute("data-reveal-armed", "");
    }
  }, []);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;

    const items = Array.from(root.querySelectorAll<HTMLElement>("[data-reveal]"));

    if (motionDisabled()) {
      items.forEach((el) => el.classList.add("is-visible"));
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target as HTMLElement;
          // Stagger within a group so a row of cards arrives in sequence
          // rather than as one block.
          const delay = Number(el.dataset.revealDelay ?? 0);
          el.style.transitionDelay = `${delay}ms`;
          el.classList.add("is-visible");
          io.unobserve(el);
        });
      },
      // Fire a little before the element is fully on screen, so the motion
      // finishes about when the reader's eye arrives.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.15 },
    );

    items.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return ref;
}

/** Stagger helper: `{...revealDelay(i)}` on each item in a mapped list. */
export function revealDelay(index: number, step = 70) {
  return { "data-reveal": "", "data-reveal-delay": String(index * step) };
}
