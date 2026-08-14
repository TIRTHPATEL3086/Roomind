import { create } from "zustand";

import type { TargetOption } from "../api/client";

/** ARIA asking which object was meant, rather than guessing at one. */
export interface Clarification {
  question: string | null;
  options: TargetOption[];
  status: "clarify" | "confirm";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: string[];
  commands: { action: string; target?: string | null }[];
  /** Present only on turns where the target was ambiguous or low-confidence. */
  clarification?: Clarification | null;
  engine?: string;
  latencyMs?: number;
  ts: number;
}

let seq = 0;

interface ChatStore {
  messages: ChatMessage[];
  thinking: boolean;
  suggestions: string[];
  draft: string;

  setDraft: (s: string) => void;
  setThinking: (b: boolean) => void;
  setSuggestions: (s: string[]) => void;
  push: (m: Omit<ChatMessage, "id" | "ts">) => void;
  clear: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  thinking: false,
  suggestions: [],
  draft: "",

  setDraft: (s) => set({ draft: s }),
  setThinking: (b) => set({ thinking: b }),
  setSuggestions: (s) => set({ suggestions: s }),
  push: (m) =>
    set((s) => ({
      messages: [...s.messages, { ...m, id: `m${++seq}`, ts: Date.now() }],
    })),
  clear: () => set({ messages: [] }),
}));
