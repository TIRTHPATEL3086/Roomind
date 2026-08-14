import { AnimatePresence, motion } from "framer-motion";
import { CornerDownLeft, Loader2, Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";

import { api } from "../api/client";
import {
  useChatStore,
  type ChatMessage,
  type Clarification,
} from "../store/chatStore";
import { useSceneStore } from "../store/sceneStore";
import { useUIStore } from "../store/uiStore";
import { Chip, Panel } from "./ui/Panel";

/** A cited object id. Hovering highlights it in 3D; clicking selects it —
 *  the link between what ARIA says and what you can see (spec 13.6). */
function Citation({ id }: { id: string }) {
  const hover = useSceneStore((s) => s.hover);
  const select = useSceneStore((s) => s.select);
  const exists = useSceneStore((s) => Boolean(s.objectById(id)));

  return (
    <button
      type="button"
      onMouseEnter={() => hover(id)}
      onMouseLeave={() => hover(null)}
      onClick={() => select(id)}
      disabled={!exists}
      className="mx-0.5 rounded border border-glow/40 bg-glow/10 px-1 font-mono
                 text-[10px] text-glow transition hover:bg-glow/25
                 disabled:opacity-40"
    >
      {id}
    </button>
  );
}

/** Render `[table_01]` inline as interactive chips. */
function withCitations(text: string) {
  const parts = text.split(/(\[[a-z_]+_\d{2}\])/g);
  return parts.map((p, i) => {
    const m = p.match(/^\[([a-z_]+_\d{2})\]$/);
    return m ? <Citation key={i} id={m[1]} /> : <span key={i}>{p}</span>;
  });
}

/**
 * The candidates ARIA is choosing between, as one-tap answers.
 *
 * Hovering highlights the object in 3D, so "the red one" stops being a guess
 * about which red one — you can see it light up before you commit. Tapping
 * sends the hint back as an ordinary chat turn, which is exactly what typing
 * it would do: the resolver treats the next message as a reply to its open
 * question either way.
 */
function ClarifyChips({
  c,
  onPick,
}: {
  c: Clarification;
  onPick: (text: string) => void;
}) {
  const hover = useSceneStore((s) => s.hover);
  const select = useSceneStore((s) => s.select);

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {c.options.map((o) => (
        <button
          key={o.id}
          type="button"
          onMouseEnter={() => hover(o.id)}
          onMouseLeave={() => hover(null)}
          onFocus={() => hover(o.id)}
          onBlur={() => hover(null)}
          onClick={() => {
            select(o.id);
            onPick(o.hint ?? o.id);
          }}
          title={`${o.id} — at x ${o.position[0].toFixed(1)}, z ${o.position[2].toFixed(1)}`}
          className="flex items-center gap-1.5 rounded-full border border-glow/30
                     bg-glow/10 px-2.5 py-1 text-[11px] text-ink transition
                     hover:border-glow/70 hover:bg-glow/20"
        >
          {o.color_hex && (
            <span
              className="h-2.5 w-2.5 rounded-full border border-white/25"
              style={{ backgroundColor: o.color_hex }}
            />
          )}
          {o.hint ?? o.id}
        </button>
      ))}
    </div>
  );
}

function Bubble({ m, onPick }: { m: ChatMessage; onPick: (t: string) => void }) {
  const mine = m.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className={`flex ${mine ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed ${
          mine
            ? "bg-aria/25 text-ink"
            : "border border-white/[0.06] bg-white/[0.04] text-ink"
        }`}
      >
        {withCitations(m.content)}
        {!mine && m.clarification && m.clarification.options.length > 0 && (
          <ClarifyChips c={m.clarification} onPick={onPick} />
        )}
        {!mine && m.commands.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {m.commands.map((c, i) => (
              <span
                key={i}
                className="rounded bg-black/40 px-1.5 py-0.5 font-mono text-[10px] text-generated"
              >
                {c.action}
                {c.target ? ` → ${c.target}` : ""}
              </span>
            ))}
          </div>
        )}
        {!mine && m.engine && (
          <div className="mt-1 font-mono text-[9px] text-ink-muted/50">
            {m.engine}
            {m.latencyMs != null && ` · ${Math.round(m.latencyMs)}ms`}
          </div>
        )}
      </div>
    </motion.div>
  );
}

export function ChatPanel() {
  const open = useUIStore((s) => s.chatOpen);
  const roomId = useSceneStore((s) => s.roomId);
  const { messages, thinking, suggestions, draft } = useChatStore();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .get<string[]>(`/chat/${roomId}/suggestions`)
      .then((r) => useChatStore.getState().setSuggestions(r.data))
      .catch(() => {});
  }, [roomId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || thinking) return;

    const store = useChatStore.getState();
    store.setDraft("");
    store.push({ role: "user", content: msg, citations: [], commands: [] });
    store.setThinking(true);

    try {
      const { data } = await api.post("/chat", { room_id: roomId, message: msg });
      store.push({
        role: "assistant",
        content: data.reply,
        citations: data.citations ?? [],
        commands: data.commands ?? [],
        clarification: data.clarification ?? null,
        engine: data.engine,
        latencyMs: data.latency_ms,
      });
    } catch (e) {
      useUIStore.getState().pushAlert({
        level: "error",
        message: `Chat failed: ${(e as Error).message}`,
      });
    } finally {
      useChatStore.getState().setThinking(false);
    }
  }

  if (!open) return null;

  return (
    <Panel
      title="ARIA"
      className="flex h-[26rem] w-80 flex-col overflow-hidden"
      right={
        <button
          type="button"
          onClick={() => useUIStore.getState().toggleChat()}
          className="text-[11px] text-ink-muted hover:text-ink"
        >
          hide <kbd className="rounded bg-white/10 px-1">C</kbd>
        </button>
      }
    >
      <div className="rm-scroll flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {messages.length === 0 && (
          <div className="py-4 text-center text-[11px] text-ink-muted">
            <Sparkles size={14} className="mx-auto mb-1 text-glow" />
            Ask about the room. ARIA looks at what she mentions.
          </div>
        )}
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <Bubble key={m.id} m={m} onPick={(t) => void send(t)} />
          ))}
        </AnimatePresence>
        {thinking && (
          <div className="flex items-center gap-1.5 text-[11px] text-ink-muted">
            <Loader2 size={12} className="animate-spin" /> thinking…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length === 0 && suggestions.length > 0 && (
        <div className="flex flex-wrap gap-1 border-t border-white/[0.06] px-3 py-2">
          {suggestions.slice(0, 3).map((s) => (
            <Chip key={s} onClick={() => send(s)}>
              {s}
            </Chip>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
        className="flex items-center gap-2 border-t border-white/[0.06] p-2"
      >
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => useChatStore.getState().setDraft(e.target.value)}
          placeholder="Ask ARIA…"
          className="flex-1 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5
                     text-xs outline-none placeholder:text-ink-muted/60
                     focus:border-aria/60"
        />
        <button
          type="submit"
          disabled={!draft.trim() || thinking}
          className="rounded-lg bg-aria/80 p-1.5 text-white transition hover:bg-aria
                     disabled:cursor-not-allowed disabled:opacity-40"
        >
          <CornerDownLeft size={14} />
        </button>
      </form>
    </Panel>
  );
}
