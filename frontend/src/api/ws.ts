import type { SceneGraph } from "../types";
import { useRobotStore } from "../store/robotStore";
import { useScanStore } from "../store/scanStore";
import { useSceneStore } from "../store/sceneStore";
import { useUIStore } from "../store/uiStore";

/** Every frame is {type, ts, data} - spec 8.7, no other shape is permitted. */
interface Envelope {
  type: string;
  ts: number;
  data: Record<string, unknown>;
}

const PING_MS = 15_000;
const RECONNECT_MS = 1_500;

let socket: WebSocket | null = null;
let pingTimer: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let closedByUs = false;

function handle({ type, data }: Envelope): void {
  const robot = useRobotStore.getState();
  const scene = useSceneStore.getState();
  const ui = useUIStore.getState();

  switch (type) {
    case "robot.telemetry":
      robot.applyTelemetry(data);
      break;
    case "robot.joints":
      robot.applyTelemetry({ joints: data.joints, emotion: data.emotion });
      break;
    case "robot.status":
      robot.applyStatus(data);
      if (data.state === "estop") ui.setEstopped(true);
      break;
    case "command.planned":
      robot.applyPath(data.path as [number, number][]);
      break;
    case "command.status":
      if (["succeeded", "failed", "cancelled", "rejected"].includes(String(data.status))) {
        robot.clearPath();
      }
      break;
    case "scene.updated":
      scene.setGraph(data as unknown as SceneGraph);
      break;
    case "scan.started":
      useScanStore.getState().start(String(data.scan_id), String(data.room_id));
      break;
    case "scan.progress":
      useScanStore.getState().onProgress(data);
      break;
    case "scan.completed":
      useScanStore.getState().onCompleted(data);
      break;
    case "scan.failed":
      useScanStore.getState().onFailed(data);
      break;
    case "alert":
      ui.pushAlert({
        level: (data.level as "info" | "warn" | "error") ?? "info",
        message: String(data.message ?? ""),
      });
      break;
    default:
      break;
  }

  // Everything reaches the CommandConsole, including types we don't handle yet -
  // that panel is the credibility surface for technical judges (spec 13.2).
  ui.logEvent(type, data);
}

export function connectWS(roomId: string): WebSocket {
  closedByUs = false;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws?room_id=${roomId}`);
  socket = ws;

  ws.onopen = () => {
    useUIStore.getState().setWsConnected(true);
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, PING_MS);
  };

  ws.onmessage = (e) => {
    try {
      handle(JSON.parse(e.data) as Envelope);
    } catch {
      // A malformed frame must not kill the socket - drop it and keep going.
    }
  };

  ws.onclose = () => {
    useUIStore.getState().setWsConnected(false);
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = null;
    if (!closedByUs) {
      reconnectTimer = setTimeout(() => connectWS(roomId), RECONNECT_MS);
    }
  };

  ws.onerror = () => ws.close();
  return ws;
}

export function disconnectWS(): void {
  closedByUs = true;
  if (pingTimer) clearInterval(pingTimer);
  if (reconnectTimer) clearTimeout(reconnectTimer);
  pingTimer = null;
  reconnectTimer = null;
  socket?.close();
  socket = null;
}
