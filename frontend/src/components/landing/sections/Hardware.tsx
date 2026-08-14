import { revealDelay } from "../useReveal";
import { ContentSection, Hi } from "./Kit";

/**
 * The MQTT topic map, copied from the frozen contract
 * (backend/app/services/mqtt_service.py). These strings are shared verbatim by
 * the backend, the simulator and the MCU firmware, so they are worth showing
 * exactly as they are rather than prettified.
 */
const TOPICS: { topic: string; dir: "out" | "in"; note: string }[] = [
  { topic: "room/cmd/{robot_id}", dir: "out", note: "commands" },
  { topic: "room/cmd/{robot_id}/estop", dir: "out", note: "QoS 0, jumps the queue" },
  { topic: "room/path/{robot_id}", dir: "out", note: "planned route" },
  { topic: "room/telemetry/{robot_id}", dir: "in", note: "10 Hz pose + joints" },
  { topic: "room/status/{robot_id}", dir: "in", note: "state, battery, LWT" },
  { topic: "room/ack/{robot_id}", dir: "in", note: "command receipts" },
  { topic: "room/event/{robot_id}", dir: "in", note: "obstacles, arrivals" },
];

const CORES = [
  {
    tag: "MPU",
    chip: "Qualcomm Dragonwing",
    spec: "quad Cortex-A53 @ 2.0 GHz",
    role: "Runs Python: vision, the MQTT bridge, and obstacle avoidance.",
  },
  {
    tag: "MCU",
    chip: "STM32U585",
    spec: "Cortex-M33 @ 160 MHz, Zephyr RTOS",
    role: "Drives motors and servos under real-time PID, and clamps every joint to its limits.",
  },
];

export function Hardware() {
  return (
    <ContentSection
      id="hardware"
      eyebrow="Hardware architecture"
      title={<>Built on Arduino <Hi>UNO Q dual-brain</Hi></>}
      lede="A Linux core for anything that thinks and a microcontroller for anything that must not miss a deadline, bridged by shared-memory RPC. The MCU has the final say on joint limits — a bug in Python must never be able to drive a servo past its stop."
    >
      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <div className="grid gap-4 sm:grid-cols-2">
          {CORES.map((c, i) => (
            <div
              key={c.tag}
              {...revealDelay(i)}
              className="rounded-panel border border-white/10 bg-white/[0.03] p-5"
            >
              <span className="font-mono text-[10px] uppercase tracking-widest text-glow">
                {c.tag}
              </span>
              <h3 className="mt-1.5 font-display text-[15px] font-semibold">
                {c.chip}
              </h3>
              <p className="font-mono text-[11px] text-ink-muted">{c.spec}</p>
              <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
                {c.role}
              </p>
            </div>
          ))}
        </div>

        <div
          {...revealDelay(2)}
          className="overflow-hidden rounded-panel border border-white/10
                     bg-[#070B16]"
        >
          <div className="border-b border-white/8 px-5 py-3">
            <span className="font-mono text-[10px] uppercase tracking-widest text-ink-muted">
              MQTT topic map
            </span>
          </div>
          {/* Long topic strings must scroll inside this panel, never widen the
              page — a horizontally scrolling landing page is a bug. */}
          <div className="overflow-x-auto px-5 py-4">
            <table className="w-full min-w-[22rem] border-separate border-spacing-y-1.5">
              <tbody>
                {TOPICS.map(({ topic, dir, note }) => (
                  <tr key={topic}>
                    <td className="whitespace-nowrap pr-4 font-mono text-[11px] text-aria">
                      {topic}
                    </td>
                    <td className="whitespace-nowrap pr-3 font-mono text-[10px] text-ink-muted">
                      {dir === "out" ? "→ robot" : "← robot"}
                    </td>
                    <td className="text-[11px] text-ink-muted">{note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </ContentSection>
  );
}
