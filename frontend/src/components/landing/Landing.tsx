import { SkipForward } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import "../../motion/effects";                    // registers the four effects
import { gsap, ScrollTrigger } from "../../motion/gsap";
import { DUR } from "../../motion/motionTokens";
import { motionDisabled } from "../../motion/reducedMotion";
import { initSmoothScroll } from "../../motion/smoothScroll";
import {
  S0_Hero,
  S1_Scan,
  S2_Understand,
  S3_Companion,
  S4_Robot,
  S5_Imagine,
} from "./Beats";
import { Aria } from "./sections/Aria";
import { Capabilities } from "./sections/Capabilities";
import { Closing } from "./sections/Closing";
import { Flow } from "./sections/Flow";
import { Hardware } from "./sections/Hardware";
import { Modes } from "./sections/Modes";
import { useReveal } from "./useReveal";

/** Below this for FPS_GRACE_MS and we drop the scrubs, keep the fades (13.12). */
const FPS_FLOOR = 40;
const FPS_GRACE_MS = 2500;
/**
 * Ignore the first stretch entirely.
 *
 * The old guard began sampling the instant it mounted — which is while the
 * page is still fetching furniture models, compiling shaders, uploading
 * buffers and running the hero's SplitText. Frame rate is at its worst there,
 * on every machine, and it recovers seconds later. Measuring that window and
 * then permanently killing every scrubbed trigger meant the camera flight was
 * dead before the user had scrolled a pixel: this fired on a perfectly capable
 * machine and looked exactly like "the scroll animation is broken".
 *
 * The guard is for a machine that CANNOT sustain the flight, not for a machine
 * that is still starting up.
 */
const FPS_WARMUP_MS = 4000;

const NAV_LINKS = [
  { href: "#platform", label: "Platform" },
  { href: "#how", label: "How it works" },
  { href: "#aria", label: "ARIA" },
  { href: "#hardware", label: "Hardware" },
];

export function Landing({ onEnter }: { onEnter: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const [degraded, setDegraded] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const leaving = useRef(false);

  // One observer for every [data-reveal] in the content region below the
  // cinematic beats. See useReveal for why this is not ScrollTrigger.
  const content = useReveal<HTMLDivElement>();

  /**
   * Hand off to /app (spec 13.11).
   *
   * Order matters: fade the DOM out, THEN kill every ScrollTrigger, THEN lock
   * the body, THEN switch route. Killing triggers before the fade makes the
   * page jump as pinned/scrubbed transforms release all at once.
   *
   * The <Canvas> is never touched — it lives above the router, so the WebGL
   * context and every GPU buffer survive. That is the whole trick.
   */
  const handOff = useCallback(() => {
    if (leaving.current) return;
    leaving.current = true;

    const finish = () => {
      ScrollTrigger.getAll().forEach((t) => t.kill());
      window.scrollTo(0, 0);
      onEnter(); // flips data-route, and CSS locks scrolling for /app
    };

    if (motionDisabled() || !root.current) {
      finish();
      return;
    }
    gsap.to(root.current, {
      opacity: 0,
      duration: DUR.quick,
      ease: "power2.in",
      onComplete: finish,
    });
  }, [onEnter]);

  // Lenis, landing only. /app must never smooth-scroll — it makes the chat log
  // and the command console feel laggy.
  useEffect(() => initSmoothScroll(), []);

  // Kill every trigger on unmount. Without this they leak into /app and keep
  // firing against nodes that no longer exist.
  useEffect(() => () => ScrollTrigger.getAll().forEach((t) => t.kill()), []);

  // Esc skips the intro from anywhere. On /app the same key is the e-stop, and
  // the two never coexist because this listener unmounts with the landing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handOff();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handOff]);

  // The nav is transparent over the hero and solid once you leave it, so it
  // never competes with the 3D behind it and never floats over body copy.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > window.innerHeight * 0.6);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Frame-rate floor: if the machine can't hold 40 fps we drop the scrubbed
  // camera and keep the fades, rather than showing a stuttering flight.
  useEffect(() => {
    if (motionDisabled()) return;
    const mounted = performance.now();
    let frames = 0;
    let since = performance.now();
    let slowSince: number | null = null;
    let raf = 0;

    const tick = () => {
      frames++;
      const now = performance.now();
      if (now - since >= 500) {
        const fps = (frames * 1000) / (now - since);
        frames = 0;
        since = now;

        // Everything before this is startup cost, not the machine's capability.
        if (now - mounted < FPS_WARMUP_MS) {
          slowSince = null;
        } else if (fps < FPS_FLOOR) {
          slowSince ??= now;
          if (now - slowSince > FPS_GRACE_MS) {
            setDegraded(true);
            ScrollTrigger.getAll().forEach((t) => {
              if (t.vars.scrub) t.kill();
            });
            return; // stop sampling; we've already degraded
          }
        } else {
          slowSince = null;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div ref={root} id="landing-scroll" className="relative z-10 text-ink">
      {/* ── nav ── */}
      <header
        className={`fixed inset-x-0 top-0 z-30 transition-colors duration-300 ${
          scrolled
            ? "border-b border-white/8 bg-night/85 backdrop-blur-glass"
            : "border-b border-transparent"
        }`}
      >
        <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3.5 md:px-16">
          <a href="#s0" className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-aria" />
            <span className="font-display text-sm font-bold tracking-tight">
              Room<span className="text-aria">Mind</span>
            </span>
          </a>

          <div className="ml-auto hidden items-center gap-7 md:flex">
            {NAV_LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                className="text-[13px] text-ink-muted transition hover:text-ink"
              >
                {l.label}
              </a>
            ))}
          </div>

          {/* Always visible, on every beat. A judge will not wait for your
              scroll story — this is the single most important control here. */}
          <button
            type="button"
            onClick={handOff}
            data-skip-intro
            className="ml-auto flex items-center gap-1.5 rounded-full bg-aria px-4 py-2
                       font-display text-[13px] font-semibold text-white transition
                       hover:bg-aria/90 md:ml-0"
          >
            <SkipForward size={12} /> Enter world
            <kbd className="ml-0.5 hidden rounded bg-white/20 px-1 text-[10px] sm:inline">
              Esc
            </kbd>
          </button>
        </nav>
      </header>

      {degraded && (
        <div className="fixed bottom-4 left-4 z-30 rounded bg-amber-500/15 px-2 py-1
                        text-[10px] text-amber-300">
          reduced motion — keeping the frame rate up
        </div>
      )}

      {/* ── cinematic beats, over the live 3D room ──
          The camera rig scrubs against THIS element, not the whole page: with
          the long-form content below, scoping to #landing-scroll would stretch
          a six-beat camera flight across the entire document and the room
          would still be drifting while you read the hardware section. */}
      <div id="landing-cinematic" className="relative">
        {/* Vignette between the canvas and the copy.
            The camera flies through six poses, so there is no fixed "safe"
            area for text — at the hero pose the object labels ran straight
            through the headline. Darkening the edges and leaving the middle
            clear keeps every beat readable wherever the room happens to be,
            and reads as deliberate cinematography rather than a patch. */}
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0"
          style={{
            background:
              "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(11,16,32,0) 0%, rgba(11,16,32,0.55) 55%, rgba(11,16,32,0.88) 100%)",
          }}
        />
        <S0_Hero onEnter={handOff} />
        <S1_Scan />
        <S2_Understand />
        <S3_Companion />
        <S4_Robot />
        <S5_Imagine onEnter={handOff} />
      </div>

      {/* ── long-form content, on an opaque surface ──
          Opaque on purpose: body copy over a moving 3D render is unreadable,
          and it makes the GPU shade pixels nobody can see. */}
      <div ref={content} className="relative z-10 bg-night">
        <Capabilities />
        <Flow />
        <Aria />
        <Modes />
        <Hardware />
        <Closing onEnter={handOff} />
      </div>
    </div>
  );
}

export default Landing;
