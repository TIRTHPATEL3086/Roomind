import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Info, OctagonX, X } from "lucide-react";
import { useEffect } from "react";

import { useUIStore } from "../store/uiStore";

const ICON = { info: Info, warn: AlertTriangle, error: OctagonX };
const COLOR = {
  info: "text-glow",
  warn: "text-amber-400",
  error: "text-danger",
};

export function Alerts() {
  const alerts = useUIStore((s) => s.alerts);
  const dismiss = useUIStore((s) => s.dismissAlert);

  // Auto-dismiss info toasts (command success, "added to room", etc.); leave
  // warnings and errors for the user to clear themselves.
  useEffect(() => {
    const timers = alerts
      .filter((a) => a.level === "info")
      .map((a) => setTimeout(() => dismiss(a.id), 2000));
    return () => timers.forEach(clearTimeout);
  }, [alerts, dismiss]);

  return (
    <div className="pointer-events-none flex flex-col gap-2">
      <AnimatePresence initial={false}>
        {alerts.map((a) => {
          const Icon = ICON[a.level];
          return (
            <motion.div
              key={a.id}
              layout
              initial={{ opacity: 0, y: -8, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.18 }}
              className="rm-glass pointer-events-auto flex items-start gap-2 px-3 py-2"
            >
              <Icon size={14} className={`mt-0.5 shrink-0 ${COLOR[a.level]}`} />
              <span className="max-w-[18rem] text-xs">{a.message}</span>
              <button
                type="button"
                onClick={() => dismiss(a.id)}
                className="ml-auto rounded p-0.5 text-ink-muted hover:bg-white/10"
              >
                <X size={12} />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
