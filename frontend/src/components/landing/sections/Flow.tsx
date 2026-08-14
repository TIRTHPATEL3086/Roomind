import { revealDelay } from "../useReveal";
import { ContentSection, Hi } from "./Kit";

/** The real pipeline, in the order it runs. */
const STEPS = [
  {
    n: "01",
    title: "Scan the room",
    body: "RGB and depth keyframes stream from a phone. Blurry frames are rejected on the way in — one blurred frame breaks the pose chain for every frame after it.",
  },
  {
    n: "02",
    title: "Reconstruct",
    body: "Camera motion is solved, the reconstruction is aligned to gravity, and TSDF fusion extracts a mesh capped at 150k triangles.",
  },
  {
    n: "03",
    title: "Detect objects",
    body: "The fused cloud is segmented in 3D, then projected back to per-frame masks — so a chair in front of a table stays a chair.",
  },
  {
    n: "04",
    title: "Build the scene graph",
    body: "Boxes are merged across views, snapped to the floor, and written as a schema-validated room.json with a 5 cm navmesh beside it.",
  },
  {
    n: "05",
    title: "Ask ARIA",
    body: "Retrieval pulls the objects your question is about; the answer comes back with their ids attached, and she looks at what she cites.",
  },
  {
    n: "06",
    title: "Command the robot",
    body: "Natural language becomes a tool call, then an A* path, then MQTT, then firmware. The same kinematics run in the sim and on the board.",
  },
];

export function Flow() {
  return (
    <ContentSection
      id="how"
      tone="raised"
      eyebrow="End-to-end flow"
      title={<>How <Hi>RoomMind</Hi> works</>}
      lede="From a phone walking a room to a robot pointing at your keys — six stages, no manual step in between."
    >
      <ol className="grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
        {STEPS.map((s, i) => (
          <li
            key={s.n}
            {...revealDelay(i)}
            className="relative border-t border-white/10 pt-5"
          >
            {/* A short accent rule per step: it gives the grid a rhythm without
                the vertical dividers, which break badly when the columns
                reflow from three to two to one. */}
            <span className="absolute -top-px left-0 h-px w-10 bg-aria" />
            <span className="font-display text-3xl font-bold text-white/12">
              {s.n}
            </span>
            <h3 className="mt-1.5 font-display text-[15px] font-semibold">
              {s.title}
            </h3>
            <p className="mt-2 max-w-sm text-[13px] leading-relaxed text-ink-muted">
              {s.body}
            </p>
          </li>
        ))}
      </ol>
    </ContentSection>
  );
}
