/**
 * Lenis <-> ScrollTrigger bridge (spec 13.8.4).
 *
 * Landing route ONLY. Smooth scroll on the operator dashboard makes the chat
 * log and the command console feel laggy and unresponsive — /app must never
 * mount this.
 */
import Lenis from "lenis";

import { gsap, ScrollTrigger } from "./gsap";
import { motionDisabled } from "./reducedMotion";

export function initSmoothScroll(): () => void {
  if (motionDisabled()) return () => {};

  const lenis = new Lenis({ duration: 1.1, smoothWheel: true, syncTouch: false });
  lenis.on("scroll", ScrollTrigger.update);

  // Drive Lenis from GSAP's ticker so there is exactly one rAF loop in the
  // page. Two loops means the camera and the DOM tick at different times and
  // visibly desync under load. gsap's ticker is in seconds; Lenis wants ms.
  const tick = (t: number) => lenis.raf(t * 1000);
  gsap.ticker.add(tick);
  gsap.ticker.lagSmoothing(0);

  return () => {
    gsap.ticker.remove(tick);
    gsap.ticker.lagSmoothing(500, 33); // restore the global default
    lenis.destroy();
  };
}
