import { useEffect } from "react";

import { clearEstop, estop } from "../api/client";
import { useUIStore } from "../store/uiStore";

/**
 * Global shortcuts.
 *
 * Esc -> e-stop is wired FIRST, before anything else in this file, and it is
 * checked before any other key (spec 13.7). It also ignores whether focus is in
 * a text input: if someone is typing in the chat box and the robot is heading
 * for a table edge, the stop must still fire.
 */
export function useKeyboardShortcuts() {
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      // ── E-STOP. Always first. No guards. ──
      if (e.key === "Escape") {
        e.preventDefault();
        useUIStore.getState().setEstopped(true);
        useUIStore.getState().pushAlert({
          level: "error",
          message: "Emergency stop (Esc)",
        });
        await estop();
        return;
      }

      const target = e.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (typing) return;

      // Backtick opens the CommandConsole - the credibility panel (spec 13.2).
      if (e.key === "`") {
        e.preventDefault();
        useUIStore.getState().toggleConsole();
        return;
      }

      if (e.key.toLowerCase() === "c") {
        useUIStore.getState().toggleChat();
        return;
      }

      // Shift+Esc would be ambiguous, so releasing the latch is its own key.
      if (e.key.toLowerCase() === "r" && useUIStore.getState().estopped) {
        await clearEstop();
        useUIStore.getState().setEstopped(false);
        useUIStore.getState().pushAlert({ level: "info", message: "E-stop released" });
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
