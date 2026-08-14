/**
 * The ONLY place GSAP is registered (spec 13.8.1).
 *
 * Every other file imports gsap FROM HERE, never from the package directly.
 * That single rule prevents double-registration, plugin-not-found errors, and
 * SSR crashes — and it means adding a plugin touches exactly one file.
 *
 * All of these plugins are free (GSAP 3.13+, see public/CREDITS.md). No licence
 * key, no auth token, no `.npmrc`.
 */
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(ScrollTrigger, SplitText, useGSAP);

// Global defaults ARE the brand. Change them here, never per-tween.
gsap.defaults({ ease: "power3.out", duration: 0.8 });
gsap.config({ nullTargetWarn: false });

// One ticker for everything. Never call requestAnimationFrame yourself —
// competing loops cause the camera and the DOM to drift apart under load.
gsap.ticker.lagSmoothing(500, 33);

export { gsap, ScrollTrigger, SplitText, useGSAP };
