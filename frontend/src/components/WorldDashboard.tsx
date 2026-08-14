import { Terminal } from "lucide-react";

import { useKeyboardShortcuts } from "../hooks/useKeyboardShortcuts";
import { useSceneStore } from "../store/sceneStore";
import { useUIStore } from "../store/uiStore";
import { Alerts } from "./Alerts";
import { ChatPanel } from "./ChatPanel";
import { CommandConsole } from "./CommandConsole";
import { ImaginePanel } from "./ImaginePanel";
import { QuickCommands } from "./QuickCommands";
import { RobotHUD } from "./RobotHUD";
import { RoomSwitcher } from "./RoomSwitcher";
import { ScanButton, ScanProgress } from "./ScanProgress";
import { ScanUploadPanel } from "./ScanUploadPanel";
import { StatDot } from "./ui/Panel";

/**
 * The /app overlay layer.
 *
 * It does NOT own the <Canvas> or load the scene — both live in App.tsx, above
 * the router, so they survive the landing -> /app hand-off untouched. This
 * component renders only the UI that floats on top of the world.
 */
export function WorldDashboard() {
  useKeyboardShortcuts();

  const graph = useSceneStore((s) => s.graph);
  const error = useSceneStore((s) => s.error);
  const wsConnected = useUIStore((s) => s.wsConnected);

  return (
    // pointer-events-none so drags fall through to the OrbitControls canvas
    // underneath; each panel re-enables them for itself.
    <div className="pointer-events-none relative h-full w-full overflow-hidden">

      {/* top bar */}
      <header className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-4">
        <div className="rm-glass pointer-events-auto flex items-center gap-3 px-3 py-2">
          <span className="font-display text-sm font-bold tracking-tight">
            Room<span className="text-aria">Mind</span>
          </span>
          <span className="h-4 w-px bg-white/10" />
          <StatDot ok={wsConnected} label={wsConnected ? "live" : "reconnecting"} />
          <RoomSwitcher />
          {graph && (
            <span className="text-[11px] text-ink-muted">
              {graph.objects.length} objects
            </span>
          )}
          <ScanButton roomId={graph?.room_id ?? "demo_room"} />
        </div>

        <div className="pointer-events-auto flex items-start gap-3">
          {/* Uploading a capture and watching it reconstruct are two halves of
              the same job, so they sit next to each other. */}
          <ScanUploadPanel roomId={graph?.room_id ?? "demo_room"} />
          {/* Reconstruction is a minutes-long job, so its progress lives in the
              top bar where it stays visible rather than in a modal. */}
          <ScanProgress />
          <Alerts />
        </div>
      </header>

      {/* left rail */}
      <aside className="pointer-events-none absolute left-4 top-20 flex flex-col gap-3">
        <div className="pointer-events-auto">
          <RobotHUD />
        </div>
        <div className="pointer-events-auto">
          <QuickCommands />
        </div>
        <div className="pointer-events-auto">
          <ImaginePanel />
        </div>
      </aside>

      {/* right rail - the companion */}
      <aside className="pointer-events-auto absolute right-4 top-20">
        <ChatPanel />
      </aside>

      {/* bottom console */}
      <div className="pointer-events-none absolute inset-x-4 bottom-4">
        <CommandConsole />
      </div>

      {/* console hint */}
      <button
        type="button"
        onClick={() => useUIStore.getState().toggleConsole()}
        className="rm-glass pointer-events-auto absolute bottom-4 right-4 flex items-center
                   gap-1.5 px-2.5 py-1.5 text-[11px] text-ink-muted transition
                   hover:text-ink"
      >
        <Terminal size={12} />
        console <kbd className="rounded bg-white/10 px-1">`</kbd>
      </button>

      {error && (
        <div className="pointer-events-auto absolute left-1/2 top-1/2 w-96 -translate-x-1/2 -translate-y-1/2">
          <div className="rm-glass border-danger/40 p-4 text-sm">
            <p className="mb-1 font-display font-semibold text-danger">
              Scene unavailable
            </p>
            <p className="text-ink-muted">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}

