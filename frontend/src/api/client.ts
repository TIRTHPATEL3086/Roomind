import axios from "axios";

import type { SceneGraph } from "../types";

// Vite proxies /api to the backend (see vite.config.ts), so the app is
// same-origin in dev: no CORS preflight, and the WS upgrade just works.
export const api = axios.create({ baseURL: "/api/v1", timeout: 15000 });

export interface CommandResult {
  command_id: string;
  status: string;
  reason: string | null;
  path: [number, number][] | null;
}

export interface RobotDTO {
  id: string;
  display_name: string;
  accent_color: string;
  capabilities: string[];
  online: boolean;
  battery: number;
  pose: { x: number; y: number; z: number; yaw: number };
  joints: Record<string, number>;
  emotion: string;
  state: string;
  current_command_id: string | null;
}

export async function getRoom(roomId: string): Promise<SceneGraph> {
  const { data } = await api.get<SceneGraph>(`/rooms/${roomId}`);
  return data;
}

export async function listRooms() {
  const { data } = await api.get<
    { id: string; name: string; object_count: number }[]
  >("/rooms");
  return data;
}

export async function getRobot(id = "aria"): Promise<RobotDTO> {
  const { data } = await api.get<RobotDTO>(`/robots/${id}`);
  return data;
}

export async function sendCommand(
  action: string,
  target?: string,
  params: Record<string, unknown> = {},
): Promise<CommandResult> {
  const { data } = await api.post<CommandResult>("/commands", {
    action,
    target,
    params,
  });
  return data;
}

/**
 * Emergency stop. Deliberately bypasses the shared axios instance and its 15 s
 * timeout: this must go out immediately with the smallest possible stack in the
 * way, and `keepalive` lets it survive a page teardown.
 */
export async function estop(): Promise<void> {
  await fetch("/api/v1/estop", { method: "POST", keepalive: true });
}

export async function clearEstop(): Promise<void> {
  await fetch("/api/v1/estop/clear", { method: "POST" });
}

/**
 * Start a reconstruction (spec 10.1).
 *
 * Either upload a video or point at a capture already on disk. Progress does
 * NOT come back through this call - it arrives as scan.* WebSocket frames,
 * because the job runs for minutes and an HTTP response that waits for it
 * would time out long before the room is built.
 */
export async function startScan(opts: {
  roomId: string;
  video?: File;
  scanDir?: string;
  name?: string;
  quality?: "fast" | "medium" | "high";
  detector?: "auto" | "fusion" | "yolo" | "geometric";
  poseBackend?: "auto" | "known" | "rgbd" | "colmap";
}): Promise<{ scan_id: string; status: string }> {
  const form = new FormData();
  form.append("room_id", opts.roomId);
  if (opts.video) form.append("video", opts.video);
  if (opts.scanDir) form.append("scan_dir", opts.scanDir);
  if (opts.name) form.append("name", opts.name);
  if (opts.quality) form.append("quality", opts.quality);
  if (opts.detector) form.append("detector", opts.detector);
  if (opts.poseBackend) form.append("pose_backend", opts.poseBackend);

  // No axios timeout here: submission is fast, but the default 15 s instance
  // timeout would abort a large video upload mid-flight.
  const { data } = await api.post("/scan", form, { timeout: 0 });
  return data;
}

/** One candidate ARIA is asking the user to choose between. */
export interface TargetOption {
  id: string;
  label: string;
  color: string | null;
  color_hex?: string | null;
  size_class?: string | null;
  position: [number, number, number];
  confidence?: number | null;
  hint: string | null;
}

export interface Resolution {
  status: "resolved" | "clarify" | "not_found" | "confirm";
  target: string | null;
  message: string;
  question: string | null;
  options: TargetOption[];
  /** which viewpoint "left"/"right" was measured from: the robot, or the room */
  frame: "robot" | "room" | null;
  matched: number;
}

/**
 * Resolve a phrase to one object WITHOUT moving anything.
 *
 * Used to preview what a command would target before committing to it, which
 * is the only way to see the interesting half of this feature — once ARIA is
 * driving, the decision has already been made.
 */
export async function resolveTarget(
  roomId: string,
  text: string,
): Promise<Resolution> {
  const { data } = await api.post<Resolution>("/resolve", {
    room_id: roomId,
    text,
  });
  return data;
}

/** Natural language -> resolved target -> planned, dispatched move. */
export async function nlCommand(
  roomId: string,
  text: string,
): Promise<Resolution & { path?: [number, number][]; reply?: string }> {
  const { data } = await api.post("/commands/nl", { room_id: roomId, text });
  return data;
}

export interface DetectorInfo {
  backend: string;
  weights: string;
  trained_for_furniture: boolean;
  recognised: string[];
  size_prior_only: string[];
  note: string;
}

export async function getDetector(): Promise<DetectorInfo> {
  const { data } = await api.get<DetectorInfo>("/detector");
  return data;
}

export async function getScan(scanId: string) {
  const { data } = await api.get(`/scan/${scanId}`);
  return data;
}

export async function cancelScan(scanId: string): Promise<void> {
  await api.post(`/scan/${scanId}/cancel`);
}

export async function getHealth() {
  const { data } = await api.get<{
    status: string;
    version: string;
    services: Record<string, string>;
  }>("/health");
  return data;
}
