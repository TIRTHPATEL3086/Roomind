/**
 * Motion design tokens (spec 13.8.2).
 *
 * Motion is part of the design system, exactly like colour. A hard-coded
 * duration is a bug for the same reason a hard-coded hex is.
 */

export const DUR = {
  instant: 0.15, // hover, chip, toggle
  quick: 0.35, // panel slide, tab change
  base: 0.8, // section reveal
  cine: 1.6, // camera move between diorama beats
  epic: 2.4, // hero entrance, world hand-off
} as const;

export const EASE = {
  out: "power3.out", // default: things arriving
  inOut: "power2.inOut", // camera rails - must feel weighted, never bouncy
  snap: "back.out(1.7)", // chips, badges, "pop" affordances
  expo: "expo.out", // big reveals
  /**
   * Scrub-linked tweens ONLY.
   *
   * A non-linear ease on a scrubbed tween fights the user's scroll: they move
   * the wheel a constant amount and the scene accelerates unevenly, which
   * reads as jank rather than style.
   */
  linear: "none",
} as const;

export const STAGGER = { tight: 0.03, text: 0.045, cards: 0.09 } as const;

/**
 * Camera scrub smoothing, in seconds of catch-up.
 *
 * A number (not `true`) gives the camera inertia — it trails the scroll
 * slightly and settles, which is what makes the movement feel like a camera
 * rather than a scrollbar. `scrub: true` is 1:1 and feels twitchy.
 */
export const CAMERA_SCRUB = 1.2;
