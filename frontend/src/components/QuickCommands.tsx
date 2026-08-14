import { useState } from "react";

import { sendCommand } from "../api/client";
import { useRobotStore } from "../store/robotStore";
import { useSceneStore } from "../store/sceneStore";
import { useUIStore } from "../store/uiStore";
import { Chip, Panel } from "./ui/Panel";

/**
 * Manual command surface. Phase 3 replaces this as the *primary* path with
 * natural-language chat, but it stays: on stage a chip you can hit is worth
 * more than a sentence the microphone might mishear.
 */
export function QuickCommands() {
  const graph = useSceneStore((s) => s.graph);
  const selected = useSceneStore((s) => s.selectedObjectId);
  const estopped = useUIStore((s) => s.estopped);
  const online = useRobotStore((s) => s.aria.online);
  const [busy, setBusy] = useState<string | null>(null);

  const target = selected ?? graph?.objects[0]?.id;

  async function run(action: string, withTarget = true) {
    setBusy(action);
    try {
      const r = await sendCommand(action, withTarget ? target : undefined);
      if (r.status === "rejected") {
        useUIStore.getState().pushAlert({
          level: "warn",
          message: `${action} rejected: ${r.reason ?? "unknown"}`,
        });
      }
    } catch (err) {
      useUIStore.getState().pushAlert({
        level: "error",
        message: `${action} failed: ${(err as Error).message}`,
      });
    } finally {
      setBusy(null);
    }
  }

  const disabled = estopped || !online || !target;

  return (
    <Panel title="Quick commands" className="w-64">
      <div className="px-3 py-2">
        <p className="mb-2 text-[11px] text-ink-muted">
          Target:{" "}
          <span className="font-mono text-ink">{target ?? "none"}</span>
          {!selected && (
            <span className="text-ink-muted/60"> (click an object)</span>
          )}
        </p>

        <div className="flex flex-wrap gap-1.5">
          <Chip onClick={() => run("navigate")} disabled={disabled || !!busy}>
            navigate
          </Chip>
          <Chip onClick={() => run("look_at")} disabled={disabled || !!busy}>
            look at
          </Chip>
          <Chip onClick={() => run("point_at")} disabled={disabled || !!busy}>
            point at
          </Chip>
          <Chip onClick={() => run("present")} disabled={disabled || !!busy}>
            present
          </Chip>
          <Chip onClick={() => run("dock", false)} disabled={disabled || !!busy}>
            dock
          </Chip>
          <Chip onClick={() => run("wave", false)} disabled={disabled || !!busy}>
            wave
          </Chip>
          <Chip onClick={() => run("nod", false)} disabled={disabled || !!busy}>
            nod
          </Chip>
          <Chip onClick={() => run("dance", false)} disabled={disabled || !!busy}>
            dance
          </Chip>
        </div>

        {estopped && (
          <p className="mt-2 text-[11px] text-danger">
            E-stopped — release before commanding.
          </p>
        )}
        {!online && !estopped && (
          <p className="mt-2 text-[11px] text-amber-400">
            ARIA offline — start the simulator.
          </p>
        )}
      </div>
    </Panel>
  );
}
