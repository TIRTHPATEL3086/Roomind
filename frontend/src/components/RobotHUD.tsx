import { Battery, Eye, Hand, OctagonX, Wifi, WifiOff } from "lucide-react";

import { useRobotStore } from "../store/robotStore";
import { useUIStore } from "../store/uiStore";
import { clearEstop, estop } from "../api/client";
import { Panel } from "./ui/Panel";

const EMOTION_COLOR: Record<string, string> = {
  neutral: "#3B82F6",
  happy: "#22D3EE",
  curious: "#A78BFA",
  confused: "#F59E0B",
  alert: "#EF4444",
};

function BatteryRing({ level }: { level: number }) {
  const r = 15;
  const c = 2 * Math.PI * r;
  const hue = level > 0.4 ? "#22C55E" : level > 0.18 ? "#F59E0B" : "#EF4444";
  return (
    <svg width="38" height="38" viewBox="0 0 38 38" className="-rotate-90">
      <circle cx="19" cy="19" r={r} fill="none" stroke="#ffffff18" strokeWidth="3" />
      <circle
        cx="19"
        cy="19"
        r={r}
        fill="none"
        stroke={hue}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - level)}
      />
    </svg>
  );
}

/** A live read-out of every joint. This is the panel that proves the twin is
 *  actually mirroring the robot rather than playing an animation. */
function JointReadout() {
  const j = useRobotStore((s) => s.aria.joints);
  const rows: [string, number][] = [
    ["head pan", j.head_pan],
    ["head tilt", j.head_tilt],
    ["L sh.pitch", j.l_shoulder_pitch],
    ["L sh.roll", j.l_shoulder_roll],
    ["L elbow", j.l_elbow],
    ["R sh.pitch", j.r_shoulder_pitch],
    ["R sh.roll", j.r_shoulder_roll],
    ["R elbow", j.r_elbow],
  ];
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 px-3 pb-2 font-mono text-[10px]">
      {rows.map(([label, v]) => (
        <div key={label} className="flex justify-between">
          <span className="text-ink-muted">{label}</span>
          <span
            className={Math.abs(v) > 0.5 ? "text-glow" : "text-ink-muted/60"}
          >
            {v >= 0 ? "+" : ""}
            {v.toFixed(1)}&deg;
          </span>
        </div>
      ))}
    </div>
  );
}

export function RobotHUD() {
  const aria = useRobotStore((s) => s.aria);
  const wsConnected = useUIStore((s) => s.wsConnected);
  const estopped = useUIStore((s) => s.estopped) || aria.state === "estop";

  const emotionColor = EMOTION_COLOR[aria.emotion] ?? aria.accent_color;

  return (
    <Panel className="w-64">
      <div className="flex items-center gap-3 px-3 pt-3">
        <div className="relative">
          <BatteryRing level={aria.battery} />
          <Battery
            size={14}
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-ink-muted"
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className="font-display text-sm font-semibold"
              style={{ color: aria.accent_color }}
            >
              {aria.display_name}
            </span>
            {wsConnected ? (
              <Wifi size={12} className="text-emerald-400" />
            ) : (
              <WifiOff size={12} className="text-danger" />
            )}
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-ink-muted">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: emotionColor }}
              title={`emotion: ${aria.emotion}`}
            />
            <span className="truncate">
              {estopped ? "emergency stopped" : aria.state}
            </span>
          </div>
        </div>

        <div className="text-right font-mono text-[11px] text-ink-muted">
          {Math.round(aria.battery * 100)}%
        </div>
      </div>

      <div className="mt-2 flex items-center gap-3 px-3 font-mono text-[10px] text-ink-muted">
        <span className="flex items-center gap-1">
          <Eye size={11} /> {aria.joints.head_pan.toFixed(0)}&deg;
        </span>
        <span className="flex items-center gap-1">
          <Hand size={11} />
          {Math.max(
            Math.abs(aria.joints.l_shoulder_pitch),
            Math.abs(aria.joints.r_shoulder_pitch),
          ).toFixed(0)}
          &deg;
        </span>
        <span className="ml-auto">
          x{aria.pose.x.toFixed(2)} z{aria.pose.z.toFixed(2)}
        </span>
      </div>

      <div className="mt-2 border-t border-white/[0.06] pt-2">
        <JointReadout />
      </div>

      <div className="border-t border-white/[0.06] p-2">
        {estopped ? (
          <button
            type="button"
            onClick={async () => {
              await clearEstop();
              useUIStore.getState().setEstopped(false);
            }}
            className="w-full rounded-lg bg-emerald-600/90 py-1.5 text-xs font-semibold
                       text-white transition hover:bg-emerald-500"
          >
            Release e-stop <span className="opacity-60">(R)</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={async () => {
              useUIStore.getState().setEstopped(true);
              await estop();
            }}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg
                       bg-danger/90 py-1.5 text-xs font-semibold text-white
                       transition hover:bg-danger"
          >
            <OctagonX size={13} /> Emergency stop <span className="opacity-60">(Esc)</span>
          </button>
        )}
      </div>
    </Panel>
  );
}
