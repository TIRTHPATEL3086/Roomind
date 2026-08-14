import { create } from "zustand";

export interface LogEntry {
  id: number;
  ts: number;
  type: string;
  data: unknown;
}

export interface Alert {
  id: number;
  level: "info" | "warn" | "error";
  message: string;
  ts: number;
}

// The console is a debugging surface, not a database. Capping the buffer keeps
// 10 Hz telemetry from growing the heap without bound over a long demo.
const MAX_LOG = 300;
const MAX_ALERTS = 5;

let logSeq = 0;

interface UIStore {
  consoleOpen: boolean;
  hudOpen: boolean;
  chatOpen: boolean;
  wsConnected: boolean;
  estopped: boolean;
  log: LogEntry[];
  alerts: Alert[];
  logPaused: boolean;
  logFilter: string;

  toggleConsole: () => void;
  toggleChat: () => void;
  setWsConnected: (b: boolean) => void;
  setEstopped: (b: boolean) => void;
  logEvent: (type: string, data: unknown) => void;
  clearLog: () => void;
  setLogPaused: (b: boolean) => void;
  setLogFilter: (s: string) => void;
  pushAlert: (a: Omit<Alert, "id" | "ts">) => void;
  dismissAlert: (id: number) => void;
}

export const useUIStore = create<UIStore>((set) => ({
  consoleOpen: false,
  hudOpen: true,
  chatOpen: true,
  wsConnected: false,
  estopped: false,
  log: [],
  alerts: [],
  logPaused: false,
  logFilter: "",

  toggleConsole: () => set((s) => ({ consoleOpen: !s.consoleOpen })),
  toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })),
  setWsConnected: (b) => set({ wsConnected: b }),
  setEstopped: (b) => set({ estopped: b }),

  logEvent: (type, data) =>
    set((s) => {
      if (s.logPaused) return s;
      const entry: LogEntry = { id: ++logSeq, ts: Date.now(), type, data };
      const next = [entry, ...s.log];
      return { log: next.length > MAX_LOG ? next.slice(0, MAX_LOG) : next };
    }),

  clearLog: () => set({ log: [] }),
  setLogPaused: (b) => set({ logPaused: b }),
  setLogFilter: (s2) => set({ logFilter: s2 }),

  pushAlert: (a) =>
    set((s) => ({
      alerts: [{ ...a, id: ++logSeq, ts: Date.now() }, ...s.alerts].slice(0, MAX_ALERTS),
    })),

  dismissAlert: (id) => set((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) })),
}));
