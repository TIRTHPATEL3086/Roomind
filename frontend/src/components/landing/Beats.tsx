import { ArrowDown, Hand, ImagePlus, Play, ScanLine, Sparkles } from "lucide-react";
import { useRef } from "react";

import { gsap, useGSAP } from "../../motion/gsap";
import { DUR, EASE } from "../../motion/motionTokens";
import { motionDisabled } from "../../motion/reducedMotion";
import { useSceneStore } from "../../store/sceneStore";
import { Body, Eyebrow, Section, Title } from "./Section";

/* All copy below is original to RoomMind. See public/CREDITS.md — the visual
   TECHNIQUE is inspired by expeditione.fun; none of its wording is used. */

/** Headline numbers. Every one of these is measured, not aspirational. */
const HERO_STATS = [
  { value: "9", label: "Joints ARIA drives" },
  { value: "60", label: "FPS digital twin" },
  { value: "<3 min", label: "Room scan time" },
  { value: "2 ms", label: "E-stop, measured" },
];

export function S0_Hero({ onEnter }: { onEnter: () => void }) {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (motionDisabled()) {
        gsap.set(".rm-hero-line, .rm-hero-sub, .rm-hero-hint", { opacity: 1, y: 0 });
        return;
      }
      gsap
        .timeline({ delay: 0.25 })
        .splitReveal(".rm-hero-line", { type: "lines" })
        .from(".rm-hero-sub", { y: 18, opacity: 0, duration: DUR.base, ease: EASE.expo }, "-=0.45")
        .from(".rm-hero-hint", { opacity: 0, duration: DUR.base }, "-=0.3");
    },
    { scope: root },
  );

  return (
    <section
      id="s0"
      className="rm-section relative flex min-h-screen items-center px-6 md:px-16"
    >
      <div ref={root} className="max-w-2xl">
        <p className="rm-hero-sub mb-5">
          <span
            className="inline-flex items-center gap-1.5 rounded-full border
                       border-glow/30 bg-glow/10 px-3 py-1 font-mono text-[10px]
                       uppercase tracking-[0.18em] text-glow"
          >
            <Sparkles size={11} /> New — hand ARIA a photo, get a 3D object
          </span>
        </p>
        <h1 className="rm-hero-line font-display text-4xl font-bold leading-[1.05] md:text-7xl">
          Turn any room into an intelligent 3D world.
        </h1>
        <p className="rm-hero-sub mt-6 max-w-md text-sm leading-relaxed text-ink-muted md:text-[15px]">
          Scan it once. Then talk to a robot that actually knows what&apos;s in it —
          and can walk over and point.
        </p>

        <div className="rm-hero-sub mt-8 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onEnter}
            className="flex items-center gap-2 rounded-full bg-aria px-6 py-3
                       font-display text-sm font-semibold text-white shadow-glowAria
                       transition hover:scale-[1.03] hover:bg-aria/90 active:scale-100"
          >
            <Play size={14} /> Launch demo world
          </button>
          <a
            href="#how"
            className="flex items-center gap-2 rounded-full border border-white/15
                       px-6 py-3 font-display text-sm font-semibold text-ink
                       transition hover:border-white/35"
          >
            <ScanLine size={14} /> How it works
          </a>
        </div>

        {/* Stat strip. Four numbers is the most a reader absorbs at a glance,
            and each one is a claim the rest of the page has to back up. */}
        <dl className="rm-hero-sub mt-10 grid max-w-lg grid-cols-2 gap-x-8 gap-y-5
                       border-t border-white/10 pt-6 sm:grid-cols-4">
          {HERO_STATS.map((s) => (
            <div key={s.label}>
              <dt className="font-display text-2xl font-bold text-aria">
                {s.value}
              </dt>
              <dd className="mt-0.5 text-[11px] leading-tight text-ink-muted">
                {s.label}
              </dd>
            </div>
          ))}
        </dl>

        <div className="rm-hero-hint mt-10 flex items-center gap-2 text-[11px] text-ink-muted">
          <ArrowDown size={13} className="animate-bounce" />
          scroll
        </div>
      </div>
    </section>
  );
}

export function S1_Scan() {
  return (
    <Section id="s1" scrub>
      <Eyebrow>
        <ScanLine size={11} className="mr-1 inline" /> Step one
      </Eyebrow>
      <Title>Walk your room. That&apos;s the whole setup.</Title>
      <Body>
        No markers, no rig, no calibration. A phone camera and a slow lap of the
        room is enough to reconstruct it as a textured 3D twin.
      </Body>
    </Section>
  );
}

export function S2_Understand() {
  const root = useRef<HTMLDivElement>(null);
  const count = useSceneStore((s) => s.graph?.objects.length ?? 9);

  useGSAP(
    () => {
      if (motionDisabled()) {
        gsap.set(".rm-count", { textContent: String(count) });
        return;
      }
      gsap.timeline({
        scrollTrigger: { trigger: root.current, start: "top 65%", once: true },
      }).counterUp(".rm-count", { to: count });
    },
    { scope: root, dependencies: [count] },
  );

  return (
    <Section id="s2" align="right" scrub>
      <div ref={root}>
        <Eyebrow>Step two</Eyebrow>
        <Title>It doesn&apos;t just see shapes. It knows a chair from a table.</Title>
        <Body>
          Every object gets an identity, a size in metres and a place in a
          semantic scene graph — so a question about the room has a real answer.
        </Body>
        <p className="rm-reveal mt-6 font-display text-5xl font-bold text-glow">
          <span className="rm-count">0</span>
          <span className="ml-2 text-sm font-normal text-ink-muted">
            objects in this room
          </span>
        </p>
      </div>
    </Section>
  );
}

export function S3_Companion() {
  return (
    <Section id="s3">
      <Eyebrow>
        <Sparkles size={11} className="mr-1 inline" /> The companion
      </Eyebrow>
      <Title>Ask it anything about your room. It answers with receipts.</Title>
      <Body>
        Every claim cites the object it came from. If something isn&apos;t there,
        ARIA says so — she can&apos;t invent furniture, because invented ids are
        stripped before you ever see them.
      </Body>
      <div className="rm-reveal mt-6 rm-glass max-w-sm px-3 py-2 text-xs">
        <p className="text-ink-muted">how many chairs are there?</p>
        <p className="mt-1.5">
          Two chairs.{" "}
          <span className="rounded border border-glow/40 bg-glow/10 px-1 font-mono text-[10px] text-glow">
            chair_01
          </span>{" "}
          <span className="rounded border border-glow/40 bg-glow/10 px-1 font-mono text-[10px] text-glow">
            chair_02
          </span>
        </p>
      </div>
    </Section>
  );
}

export function S4_Robot() {
  return (
    <Section id="s4" align="right" scrub>
      <Eyebrow>
        <Hand size={11} className="mr-1 inline" /> The body
      </Eyebrow>
      <Title>Then tell it to go there. A real robot goes.</Title>
      <Body>
        ARIA plans a path, drives it, turns her head toward what she&apos;s
        describing and raises an arm to point. The robot on screen and the robot
        on the floor move joint for joint.
      </Body>
    </Section>
  );
}

export function S5_Imagine({ onEnter }: { onEnter: () => void }) {
  return (
    <Section id="s5" align="center">
      <div className="text-center">
        <Eyebrow>
          <ImagePlus size={11} className="mr-1 inline" /> And one more thing
        </Eyebrow>
        <Title>Show it a photo. Watch it appear in your room.</Title>
        <Body>
          Hand ARIA an image and she builds it in 3D, sizes it to scale, and
          finds it a spot that fits. From that moment she can walk to it and
          point at it like anything she scanned.
        </Body>
        <button
          type="button"
          onClick={onEnter}
          data-enter-world
          className="rm-reveal mt-10 rounded-full bg-aria px-7 py-3 font-display text-sm
                     font-semibold text-white shadow-glowAria transition
                     hover:scale-[1.03] hover:bg-aria/90 active:scale-100"
        >
          Enter your world
        </button>
        <p className="rm-reveal mt-3 text-[11px] text-ink-muted">
          No sign-up. It&apos;s already running.
        </p>
      </div>
    </Section>
  );
}
