import { create } from "zustand";

/**
 * Live state of a reconstruction (spec 8.7, 10.1).
 *
 * Driven entirely by scan.* WebSocket frames. The component never polls: a
 * three-minute job that reports ten stages over a socket does not need HTTP
 * polling on top, and polling would make the bar stutter between updates.
 */
export type ScanStage =
  | "queued" | "ingest" | "pose" | "depth" | "fuse" | "mesh" | "texture"
  | "detect" | "lift3d" | "floorplan" | "scenegraph" | "completed" | "failed"
  | "cancelled";

/** Human labels. The stage ids come straight from the pipeline's JSONL. */
export const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  ingest: "Reading keyframes",
  pose: "Solving camera motion",
  depth: "Estimating depth",
  fuse: "Fusing the volume",
  mesh: "Building the mesh",
  texture: "Baking texture",
  detect: "Finding objects",
  lift3d: "Lifting to 3D",
  floorplan: "Floor plan and navmesh",
  scenegraph: "Writing the scene graph",
  completed: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Display order, matching the pipeline's own stage order. */
export const STAGE_ORDER: ScanStage[] = [
  "ingest", "pose", "depth", "fuse", "mesh", "texture",
  "detect", "lift3d", "floorplan", "scenegraph",
];

export interface ScanState {
  scanId: string | null;
  roomId: string | null;
  stage: ScanStage;
  progress: number;
  note: string;
  elapsed: number;
  objects: number | null;
  warnings: string[];
  error: string | null;
  active: boolean;

  start: (scanId: string, roomId: string) => void;
  onProgress: (d: Record<string, unknown>) => void;
  onCompleted: (d: Record<string, unknown>) => void;
  onFailed: (d: Record<string, unknown>) => void;
  dismiss: () => void;
}

const IDLE = {
  scanId: null, roomId: null, stage: "queued" as ScanStage, progress: 0,
  note: "", elapsed: 0, objects: null, warnings: [] as string[],
  error: null, active: false,
};

export const useScanStore = create<ScanState>((set, get) => ({
  ...IDLE,

  start: (scanId, roomId) =>
    set({ ...IDLE, scanId, roomId, active: true, stage: "queued" }),

  onProgress: (d) => {
    // Ignore frames from a different scan: starting a second reconstruction
    // while the first is finishing would otherwise make the bar jump between
    // two jobs.
    const id = String(d.scan_id ?? "");
    const cur = get().scanId;
    if (cur && id && id !== cur) return;
    set({
      scanId: cur ?? id,
      active: true,
      stage: (d.stage as ScanStage) ?? get().stage,
      // Never let the bar run backwards - it reads as a crash.
      progress: Math.max(get().progress, Number(d.progress ?? 0)),
      note: String(d.note ?? ""),
      elapsed: Number(d.elapsed_s ?? get().elapsed),
    });
  },

  onCompleted: (d) =>
    set({
      stage: "completed", progress: 1, active: true,
      objects: Number(d.objects ?? 0),
      warnings: (d.warnings as string[]) ?? [],
      elapsed: Number(d.elapsed_s ?? get().elapsed),
      note: "",
    }),

  onFailed: (d) =>
    set({
      stage: String(d.reason) === "cancelled" ? "cancelled" : "failed",
      active: true,
      error: String(d.reason ?? "reconstruction failed"),
    }),

  dismiss: () => set({ ...IDLE }),
}));
