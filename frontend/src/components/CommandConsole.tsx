import { Pause, Play, Trash2, X } from "lucide-react";
import { useMemo } from "react";

import { useUIStore } from "../store/uiStore";

const TYPE_COLOR: Record<string, string> = {
  "robot.telemetry": "text-ink-muted/50",
  "robot.joints": "text-glow/70",
  "robot.status": "text-emerald-400",
  "command.created": "text-aria",
  "command.planned": "text-generated",
  "command.status": "text-amber-400",
  "scene.updated": "text-emerald-300",
  alert: "text-danger",
};

/**
 * Raw event stream, toggled with backtick.
 *
 * This is the credibility panel for technical judges (spec 13.2): it shows the
 * literal WebSocket envelopes, so the 3D scene is visibly driven by real data
 * rather than an animation.
 */
export function CommandConsole() {
  const open = useUIStore((s) => s.consoleOpen);
  const log = useUIStore((s) => s.log);
  const paused = useUIStore((s) => s.logPaused);
  const filter = useUIStore((s) => s.logFilter);

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const list = f
      ? log.filter(
          (e) =>
            e.type.toLowerCase().includes(f) ||
            JSON.stringify(e.data).toLowerCase().includes(f),
        )
      : log;
    return list.slice(0, 120);
  }, [log, filter]);

  if (!open) return null;

  return (
    <div className="rm-glass pointer-events-auto flex h-64 flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-white/[0.06] px-3 py-1.5">
        <span className="font-display text-xs font-semibold uppercase tracking-wider text-ink-muted">
          Command console
        </span>
        <input
          value={filter}
          onChange={(e) => useUIStore.getState().setLogFilter(e.target.value)}
          placeholder="filter…"
          className="ml-2 w-40 rounded border border-white/10 bg-black/30 px-2 py-0.5
                     font-mono text-[11px] outline-none placeholder:text-ink-muted/50
                     focus:border-aria/60"
        />
        <span className="font-mono text-[10px] text-ink-muted">
          {rows.length}/{log.length}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            title={paused ? "resume" : "pause"}
            onClick={() => useUIStore.getState().setLogPaused(!paused)}
            className="rounded p-1 text-ink-muted hover:bg-white/10 hover:text-ink"
          >
            {paused ? <Play size={13} /> : <Pause size={13} />}
          </button>
          <button
            type="button"
            title="clear"
            onClick={() => useUIStore.getState().clearLog()}
            className="rounded p-1 text-ink-muted hover:bg-white/10 hover:text-ink"
          >
            <Trash2 size={13} />
          </button>
          <button
            type="button"
            title="close (`)"
            onClick={() => useUIStore.getState().toggleConsole()}
            className="rounded p-1 text-ink-muted hover:bg-white/10 hover:text-ink"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      <div className="rm-scroll flex-1 overflow-y-auto px-3 py-1.5 font-mono text-[11px] leading-relaxed">
        {rows.length === 0 && (
          <p className="py-6 text-center text-ink-muted">
            No events yet. Send a command to see the raw stream.
          </p>
        )}
        {rows.map((e) => (
          <div key={e.id} className="flex gap-2 border-b border-white/[0.03] py-0.5">
            <span className="shrink-0 text-ink-muted/50">
              {new Date(e.ts).toLocaleTimeString("en-GB", { hour12: false })}
            </span>
            <span className={`w-36 shrink-0 ${TYPE_COLOR[e.type] ?? "text-ink"}`}>
              {e.type}
            </span>
            <span className="truncate text-ink-muted">{JSON.stringify(e.data)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
