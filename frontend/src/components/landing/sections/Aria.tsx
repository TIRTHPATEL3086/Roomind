import { Eye, Hand, Navigation } from "lucide-react";

import { revealDelay } from "../useReveal";
import { Card, Chip, ContentSection, Hi } from "./Kit";

/**
 * ARIA — the one robot.
 *
 * This section replaces the three-avatar line-up (Scout / Simian / Gecko) that
 * earlier builds shipped. The project deliberately consolidated onto a single
 * humanoid: three chassis meant three kinematics models, three sets of joint
 * limits and three simulators to keep in sync with the firmware, and the
 * digital-twin illusion only survives while EVERY one of them agrees with the
 * hardware. One robot, one kinematics module, shared by the simulator and
 * mirrored in the MCU's C++.
 *
 * The joint limits below are the real ones, read from the same table the
 * solver and the firmware clamp against (backend/app/core/kinematics.py).
 */
const GROUPS = [
  {
    icon: Eye,
    name: "Head",
    dof: "2 DoF",
    joints: ["head_pan ±90°", "head_tilt ±35°"],
    line: "Turns toward whatever she just cited. Slewed at 90°/s on purpose — a head that whips round reads as mechanical; one that turns reads as attention.",
  },
  {
    icon: Hand,
    name: "Arms",
    dof: "6 DoF",
    joints: [
      "shoulder_pitch −20…150°",
      "shoulder_roll 0…90°",
      "elbow 0…120°",
      "×2",
    ],
    line: "Points at what you asked about. The solver picks the arm on the correct side, and a target out of reach fails the gesture rather than the answer.",
  },
  {
    icon: Navigation,
    name: "Base + waist",
    dof: "1 DoF + drive",
    joints: ["waist_yaw ±45°", "differential drive"],
    line: "Walks the route A* planned, at 0.45 m/s, stopping short of anything inside the clearance margin.",
  },
];

const ACTIONS = [
  "navigate", "look_at", "point_at", "wave", "nod",
  "scan_area", "dock", "stop",
];

export function Aria() {
  return (
    <ContentSection
      id="aria"
      eyebrow="The robot"
      title={<>One robot. <Hi>Nine joints.</Hi></>}
      lede={
        <>
          ARIA runs on an Arduino UNO Q and speaks one frozen MQTT contract.
          The avatar in your browser and the servo on your desk are driven by
          the <span className="text-ink">same</span> kinematics module — if they
          ever disagreed, the twin would be a cartoon.
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-3">
        {GROUPS.map(({ icon: Icon, name, dof, joints, line }, i) => (
          <Card key={name} {...revealDelay(i)}>
            <div className="flex items-center gap-2.5">
              <div
                className="flex h-9 w-9 items-center justify-center rounded-lg
                           border border-glow/25 bg-glow/10 text-glow"
              >
                <Icon size={16} />
              </div>
              <div>
                <h3 className="font-display text-[15px] font-semibold leading-tight">
                  {name}
                </h3>
                <span className="font-mono text-[10px] text-ink-muted">{dof}</span>
              </div>
            </div>

            <div className="mt-3.5 flex flex-wrap gap-1.5">
              {joints.map((j) => (
                <Chip key={j}>{j}</Chip>
              ))}
            </div>

            <p className="mt-3.5 text-[13px] leading-relaxed text-ink-muted">
              {line}
            </p>
          </Card>
        ))}
      </div>

      <div
        {...revealDelay(3)}
        className="mt-6 flex flex-wrap items-center gap-2 rounded-panel border
                   border-white/10 bg-white/[0.03] px-5 py-4"
      >
        <span className="mr-1 font-mono text-[10px] uppercase tracking-widest text-ink-muted">
          Commands
        </span>
        {ACTIONS.map((a) => (
          <Chip key={a} tone="accent">
            {a}
          </Chip>
        ))}
      </div>
    </ContentSection>
  );
}
