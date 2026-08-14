import { create } from "zustand";

import type { TelemetryJoints } from "../types";

export const REST_JOINTS: Required<TelemetryJoints> = {
  head_pan: 0,
  head_tilt: 0,
  waist_yaw: 0,
  l_shoulder_pitch: 0,
  l_shoulder_roll: 5,
  l_elbow: 15,
  r_shoulder_pitch: 0,
  r_shoulder_roll: 5,
  r_elbow: 15,
};

export type Emotion = "neutral" | "happy" | "curious" | "confused" | "alert";

export interface RobotState {
  id: string;
  display_name: string;
  accent_color: string;
  capabilities: string[];
  online: boolean;
  battery: number;
  pose: { x: number; y: number; z: number; yaw: number };
  joints: Required<TelemetryJoints>;
  emotion: Emotion;
  state: string;
  current_command_id: string | null;
  path?: [number, number][];
}

const initial: RobotState = {
  id: "aria",
  display_name: "ARIA",
  accent_color: "#3B82F6",
  capabilities: [],
  online: false,
  battery: 1,
  pose: { x: 0, y: 0, z: 0, yaw: 0 },
  joints: { ...REST_JOINTS },
  emotion: "neutral",
  state: "idle",
  current_command_id: null,
};

interface RobotStore {
  aria: RobotState;
  lastTelemetryAt: number | null;
  applyTelemetry: (t: Record<string, unknown>) => void;
  applyStatus: (s: Record<string, unknown>) => void;
  applyPath: (p: [number, number][]) => void;
  clearPath: () => void;
  hydrate: (r: Partial<RobotState>) => void;
  /** Place ARIA on the room's dock — only while she is offline. */
  parkAtDock: (dock: [number, number, number], floorY: number) => void;
}

export const useRobotStore = create<RobotStore>((set) => ({
  aria: initial,
  lastTelemetryAt: null,

  applyTelemetry: (t) =>
    set((s) => ({
      lastTelemetryAt: Date.now(),
      aria: {
        ...s.aria,
        online: true,
        pose: (t.pose as RobotState["pose"]) ?? s.aria.pose,
        // Merge, never replace: a partial joints block must not silently reset
        // the joints it omits back to zero.
        joints: { ...s.aria.joints, ...((t.joints as TelemetryJoints) ?? {}) },
        emotion: (t.emotion as Emotion) ?? s.aria.emotion,
        state: (t.state as string) ?? s.aria.state,
        battery: typeof t.battery === "number" ? t.battery : s.aria.battery,
        current_command_id: (t.current_command_id as string | null) ?? null,
      },
    })),

  applyStatus: (st) =>
    set((s) => ({
      aria: {
        ...s.aria,
        online: Boolean(st.online),
        battery: typeof st.battery === "number" ? st.battery : s.aria.battery,
        state: (st.state as string) ?? s.aria.state,
      },
    })),

  applyPath: (p) => set((s) => ({ aria: { ...s.aria, path: p } })),
  clearPath: () => set((s) => ({ aria: { ...s.aria, path: undefined } })),
  hydrate: (r) => set((s) => ({ aria: { ...s.aria, ...r } })),

  parkAtDock: (dock, floorY) =>
    set((s) => {
      // Telemetry is the truth whenever there is any. This is only for the
      // case where the simulator is not running: without it ARIA renders at
      // the world origin, which in the multi-instance room is open floor in
      // the middle of everything and in a scanned room can be inside a sofa.
      // Parking her on the dock the reconstruction chose is both correct and
      // the pose she would hold if the simulator did come up.
      if (s.aria.online) return s;
      const [x, , z] = dock;
      if (s.aria.pose.x === x && s.aria.pose.z === z) return s;
      return {
        aria: { ...s.aria, pose: { x, y: floorY, z, yaw: s.aria.pose.yaw } },
      };
    }),
}));
