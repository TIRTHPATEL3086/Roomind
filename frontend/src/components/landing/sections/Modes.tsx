import { GraduationCap, PartyPopper, PencilRuler, Zap } from "lucide-react";

import { revealDelay } from "../useReveal";
import { ContentSection, RoadmapTag } from "./Kit";

const MODES = [
  {
    icon: PencilRuler,
    name: "Design mode",
    body: "Rearrange furniture virtually before moving a single piece. Test clearances against the real navmesh, not a guess.",
  },
  {
    icon: GraduationCap,
    name: "Education mode",
    body: "Interactive spatial learning. Students explore the 3D twin while ARIA acts as a guided-tour assistant.",
  },
  {
    icon: Zap,
    name: "Productivity mode",
    body: "Ask where things are, track what moved, and send the robot on errands across the room.",
  },
  {
    icon: PartyPopper,
    name: "Entertainment mode",
    body: "Follow-me, obstacle courses and gesture demos — every capability, shown off deliberately.",
  },
];

export function Modes() {
  return (
    <ContentSection
      id="modes"
      tone="raised"
      eyebrow="Four operating modes"
      title={
        <>
          Work, life, and{" "}
          <span className="italic text-ink-muted">everything</span> in between
        </>
      }
      lede={
        <>
          One scene graph, four ways to use it. These are designed and specified
          but <span className="text-ink">not yet built</span> — they land in the
          final polish phase, and it would be dishonest to show them next to
          shipped features without saying so.
        </>
      }
    >
      <div className="mb-6" data-reveal>
        <RoadmapTag />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {MODES.map(({ icon: Icon, name, body }, i) => (
          <div
            key={name}
            {...revealDelay(i)}
            className="flex gap-4 rounded-panel border border-white/10
                       bg-white/[0.02] p-5"
          >
            <Icon size={18} className="mt-0.5 shrink-0 text-ink-muted" />
            <div>
              <h3 className="font-display text-[15px] font-semibold">{name}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">
                {body}
              </p>
            </div>
          </div>
        ))}
      </div>
    </ContentSection>
  );
}
