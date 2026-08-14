import { useEffect, useState } from "react";

/**
 * Resolve a DOM element that may not exist yet, across a lazy boundary.
 *
 * The camera rig lives inside the persistent <Canvas> and scrubs against an
 * element rendered by the landing route — and the two are SEPARATE lazy
 * chunks. CameraRig is about 1 kB and Landing about 34 kB, so the rig
 * essentially always resolves first, runs its effect, finds no
 * `#landing-cinematic`, and builds a ScrollTrigger against nothing. GSAP does
 * not warn about a selector that matches nothing, the effect never re-runs
 * because its dependencies did not change, and the result is a camera that
 * silently never moves.
 *
 * Polling on rAF rather than a MutationObserver: the wait is a frame or two in
 * practice, this needs no subtree configuration, and it stops on its own.
 */
export function useElement<T extends Element = HTMLElement>(
  selector: string,
  { timeoutMs = 10_000 }: { timeoutMs?: number } = {},
): T | null {
  const [el, setEl] = useState<T | null>(
    () => document.querySelector<T>(selector),
  );

  useEffect(() => {
    if (el && el.isConnected) return;

    let raf = 0;
    const started = performance.now();
    const look = () => {
      const found = document.querySelector<T>(selector);
      if (found) {
        setEl(found);
        return;
      }
      if (performance.now() - started > timeoutMs) return; // give up quietly
      raf = requestAnimationFrame(look);
    };
    raf = requestAnimationFrame(look);
    return () => cancelAnimationFrame(raf);
  }, [selector, el, timeoutMs]);

  return el;
}
