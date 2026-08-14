import { AlertTriangle, Check, Loader2, ScanLine, X } from "lucide-react";
import { useEffect, useState } from "react";

import { cancelScan } from "../api/client";
import { STAGE_LABELS, STAGE_ORDER, useScanStore } from "../store/scanStore";

/**
 * Live reconstruction progress (spec 10.1, 20/P5).
 *
 * Driven purely by scan.* WebSocket frames. A reconstruction runs for minutes
 * with long silent stretches -- pose estimation alone is a third of the wall
 * clock -- so this shows WHICH stage is running and what it is doing, not just
 * a bar. A bar that sits at 31% for forty seconds looks hung; "Solving camera
 * motion - odometry 22/38" looks like work.
 */
export function ScanProgress() {
  const {
    scanId, stage, progress, note, elapsed, objects, warnings, error, active,
    dismiss,
  } = useScanStore();

  // Tick a local clock between frames so the elapsed time keeps moving during
  // the quiet stretches instead of freezing on the last event.
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!active || stage === "completed" || stage === "failed") return;
    const t = setInterval(() => setNow((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [active, stage]);
  void now;

  if (!active) return null;

  const done = stage === "completed";
  const failed = stage === "failed" || stage === "cancelled";
  const currentIdx = STAGE_ORDER.indexOf(stage as never);
  const pct = Math.round(progress * 100);

  return (
    <div className="rm-glass pointer-events-auto w-80 p-3" data-scan-progress>
      <div className="mb-2 flex items-center gap-2">
        {done ? (
          <Check size={14} className="text-emerald-400" />
        ) : failed ? (
          <X size={14} className="text-danger" />
        ) : (
          <Loader2 size={14} className="animate-spin text-aria" />
        )}
        <span className="font-display text-xs font-semibold">
          {done ? "Room rebuilt" : failed ? "Scan failed" : "Building your twin"}
        </span>
        <span className="ml-auto font-mono text-[10px] text-ink-muted">
          {elapsed > 0 ? `${elapsed.toFixed(0)}s` : ""}
        </span>
      </div>

      {!failed && (
        <>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-aria transition-[width] duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-1.5 flex items-baseline justify-between">
            <span className="text-[11px] text-ink">
              {STAGE_LABELS[stage] ?? stage}
            </span>
            <span className="font-mono text-[10px] text-ink-muted">{pct}%</span>
          </div>
          {note && (
            <p className="mt-0.5 truncate font-mono text-[10px] text-ink-muted">
              {note}
            </p>
          )}
        </>
      )}

      {/* Stage rail. Ten dots is enough to see where you are without reading. */}
      {!failed && (
        <div className="mt-2.5 flex gap-1">
          {STAGE_ORDER.map((s, i) => (
            <div
              key={s}
              title={STAGE_LABELS[s]}
              className={`h-1 flex-1 rounded-full ${
                done || i < currentIdx
                  ? "bg-aria/70"
                  : i === currentIdx
                    ? "bg-aria animate-pulse"
                    : "bg-white/10"
              }`}
            />
          ))}
        </div>
      )}

      {done && objects !== null && (
        <p className="mt-2 text-[11px] text-ink-muted">
          Found <span className="text-ink">{objects}</span> object
          {objects === 1 ? "" : "s"}. Ask ARIA about them.
        </p>
      )}

      {error && <p className="mt-2 text-[11px] text-danger">{error}</p>}

      {/* Warnings are shown, not swallowed. A room reconstructed with guessed
          labels or a drifted camera still loads and still looks fine, so the
          only way anyone finds out is if we say so. */}
      {warnings.length > 0 && (
        <ul className="mt-2 space-y-1">
          {warnings.map((w) => (
            <li key={w} className="flex gap-1.5 text-[10px] text-amber-300/90">
              <AlertTriangle size={11} className="mt-px shrink-0" />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2.5 flex justify-end gap-2">
        {done || failed ? (
          <button
            type="button"
            onClick={dismiss}
            className="rounded px-2 py-1 text-[11px] text-ink-muted transition hover:text-ink"
          >
            Dismiss
          </button>
        ) : (
          <button
            type="button"
            onClick={() => scanId && void cancelScan(scanId)}
            className="rounded px-2 py-1 text-[11px] text-ink-muted transition hover:text-danger"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

/** Small launcher so the panel is reachable without a scan already running. */
export function ScanButton({ roomId }: { roomId: string }) {
  const active = useScanStore((s) => s.active);
  if (active) return null;
  return (
    <button
      type="button"
      title="Rebuild this room from a capture on disk"
      onClick={() => void startScanFromDisk(roomId)}
      className="rm-glass pointer-events-auto flex items-center gap-1.5 px-2.5 py-1.5
                 text-[11px] text-ink-muted transition hover:text-ink"
    >
      <ScanLine size={12} /> rescan
    </button>
  );
}

async function startScanFromDisk(roomId: string) {
  const { startScan } = await import("../api/client");
  await startScan({ roomId, scanDir: "./storage/scans/synth_demo" });
}
