/**
 * Accessibility + demo-insurance gate (spec 13.8.3, 13.12).
 *
 * Motion is disabled when EITHER is true:
 *   - the OS reports prefers-reduced-motion: reduce
 *   - the URL carries ?nomotion=1
 *
 * The second is not a debug flag, it is demo insurance: if the cinematic
 * misbehaves five minutes before a pitch, appending one query parameter gets
 * you a working page without a rebuild.
 */
import { gsap } from "./gsap";

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function motionDisabled(): boolean {
  if (typeof window === "undefined") return true;
  const flag = new URLSearchParams(window.location.search).get("nomotion");
  return prefersReducedMotion() || flag === "1" || flag === "true";
}

/**
 * Build a timeline under a motion-preference gate.
 *
 * `build(reduced)` is called with the current preference and re-called if the
 * user changes it mid-session. Returns a cleanup that reverts every tween and
 * ScrollTrigger created inside — which is what stops triggers leaking across
 * the route change into /app.
 */
export function withMotionPrefs(build: (reduced: boolean) => void): () => void {
  const mm = gsap.matchMedia();
  mm.add(
    {
      reduced: "(prefers-reduced-motion: reduce)",
      full: "(prefers-reduced-motion: no-preference)",
    },
    (ctx) => {
      // The URL flag forces the reduced branch even when the OS says otherwise.
      build(Boolean(ctx.conditions?.reduced) || motionDisabled());
    },
  );
  return () => mm.revert();
}
