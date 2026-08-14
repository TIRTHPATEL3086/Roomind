/**
 * Reusable GSAP effects (spec 13.8.5).
 *
 * Registered once with `extendTimeline: true`, so they chain directly on a
 * timeline: `tl.splitReveal("h2").maskWipe(".panel")`.
 *
 * Importing this module has the side effect of registering them. Import it
 * once, at the landing root — importing from several places is harmless
 * (registerEffect overwrites by name) but pointless.
 */
import { gsap, SplitText } from "../gsap";
import { DUR, EASE, STAGGER } from "../motionTokens";

/** Headline reveal: lines wipe up from behind a mask. */
gsap.registerEffect({
  name: "splitReveal",
  extendTimeline: true,
  defaults: { type: "lines", stagger: STAGGER.text, duration: DUR.base },
  effect: (targets: object, cfg: Record<string, unknown>) => {
    const split = new SplitText(targets as gsap.DOMTarget, {
      type: cfg.type as string,
      linesClass: "rm-line",
    });
    const nodes = split.lines?.length ? split.lines : split.chars;
    return gsap.from(nodes, {
      yPercent: 110,
      opacity: 0,
      duration: cfg.duration as number,
      ease: EASE.expo,
      stagger: cfg.stagger as number,
    });
  },
});

/** Glass panel entering behind a directional wipe. */
gsap.registerEffect({
  name: "maskWipe",
  extendTimeline: true,
  defaults: { dir: "up", duration: DUR.base },
  effect: (targets: object, cfg: Record<string, unknown>) => {
    const from: Record<string, string> = {
      up: "inset(100% 0% 0% 0%)",
      down: "inset(0% 0% 100% 0%)",
      left: "inset(0% 100% 0% 0%)",
      right: "inset(0% 0% 0% 100%)",
    };
    return gsap.from(targets as gsap.TweenTarget, {
      clipPath: from[cfg.dir as string] ?? from.up,
      opacity: 0,
      duration: cfg.duration as number,
      ease: EASE.expo,
    });
  },
});

/** Count a number up. Used for the "objects detected" stat. */
gsap.registerEffect({
  name: "counterUp",
  extendTimeline: true,
  defaults: { to: 0, duration: DUR.cine },
  effect: (targets: object, cfg: Record<string, unknown>) => {
    const box = { v: 0 };
    const els = gsap.utils.toArray<HTMLElement>(targets as gsap.DOMTarget);
    return gsap.to(box, {
      v: cfg.to as number,
      duration: cfg.duration as number,
      ease: EASE.out,
      onUpdate: () => {
        const text = String(Math.round(box.v));
        els.forEach((el) => (el.textContent = text));
      },
    });
  },
});

/** HUD power-on: elements snap in, tight stagger, like a system booting. */
gsap.registerEffect({
  name: "hudBoot",
  extendTimeline: true,
  defaults: { stagger: STAGGER.tight },
  effect: (targets: object, cfg: Record<string, unknown>) =>
    gsap.from(targets as gsap.TweenTarget, {
      opacity: 0,
      scaleY: 0.4,
      transformOrigin: "50% 100%",
      duration: DUR.quick,
      ease: EASE.snap,
      stagger: cfg.stagger as number,
    }),
});

export const EFFECTS_REGISTERED = true;
