import {
  Boxes, MessageSquareQuote, Route, Radio, ImagePlus, ShieldAlert,
} from "lucide-react";

import { revealDelay } from "../useReveal";
import { Card, ContentSection, Hi } from "./Kit";

/**
 * What the platform actually does.
 *
 * Every card describes shipped, tested code. Where a number appears it is a
 * measured one — the e-stop figure especially: 2 ms is what came back on the
 * wire with a reused client, not the 200 ms budget the spec allows.
 */
const CAPABILITIES = [
  {
    icon: Boxes,
    title: "3D reconstruction",
    body: "Walk the room with a phone. Pose graph plus TSDF fusion builds a textured, gravity-aligned twin — objects land within 3% of their real size.",
  },
  {
    icon: MessageSquareQuote,
    title: "Grounded companion",
    body: "Every answer cites the object it came from. ARIA cannot invent furniture: ids that aren't in the scene graph are stripped before you ever see them.",
  },
  {
    icon: Route,
    title: "A* path planning",
    body: "Octile A* over an inflated occupancy grid, line-of-sight smoothed so the route reads as a walk rather than a staircase.",
  },
  {
    icon: Radio,
    title: "Real-time digital twin",
    body: "10 Hz telemetry over MQTT, interpolated frame-rate-independently. The robot on screen and the robot on the floor move joint for joint.",
  },
  {
    icon: ImagePlus,
    title: "Imagine: image → 3D",
    body: "Hand ARIA a photo. She builds it in 3D, scales it to metres, finds it a spot that fits, and can then walk over and point at it.",
  },
  {
    icon: ShieldAlert,
    title: "Safety first",
    body: "E-stop publishes at QoS 0 before any database write — measured at 2 ms on the wire. Geofencing and obstacle clearance sit under every command.",
  },
];

export function Capabilities() {
  return (
    <ContentSection
      id="platform"
      eyebrow="Platform capabilities"
      title={<>Everything you need for <Hi>intelligent spaces</Hi></>}
      lede="Six subsystems, one frozen contract between them. Change the shape of a message in one place and the generated types stop compiling everywhere else."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CAPABILITIES.map(({ icon: Icon, title, body }, i) => (
          <Card key={title} {...revealDelay(i)}>
            <div
              className="mb-3.5 flex h-9 w-9 items-center justify-center rounded-lg
                         border border-aria/25 bg-aria/10 text-aria"
            >
              <Icon size={16} />
            </div>
            <h3 className="font-display text-[15px] font-semibold">{title}</h3>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">{body}</p>
          </Card>
        ))}
      </div>
    </ContentSection>
  );
}
