import { AnimatePresence, motion } from "framer-motion";
import { Bot, CornerDownLeft, Loader2, Mic, Sparkles, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { api } from "../api/client";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import {
  useChatStore,
  type ChatMessage,
  type Clarification,
} from "../store/chatStore";
import { useSceneStore } from "../store/sceneStore";
import { useUIStore } from "../store/uiStore";
import { Chip } from "./ui/Panel";

/** ARIA's avatar: a gradient badge with a live-status dot, reused in the
 *  header, the launcher bubble, and beside every assistant message so her
 *  presence reads the same everywhere she "speaks". */
function AriaAvatar({ size = 30 }: { size?: number }) {
  return (
    <span
      className="relative inline-flex flex-shrink-0 items-center justify-center rounded-full
                 bg-gradient-to-br from-aria to-glow shadow-glowAria"
      style={{ width: size, height: size }}
    >
      <Bot size={size * 0.58} className="text-night" strokeWidth={2.4} />
      <span
        className="absolute -bottom-0.5 -right-0.5 rounded-full border-2 border-night bg-emerald-400"
        style={{ width: size * 0.32, height: size * 0.32 }}
      />
    </span>
  );
}

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
      className={`flex items-end gap-1.5 ${mine ? "justify-end" : "justify-start"}`}
    >
      {!mine && <AriaAvatar size={20} />}
      <div
        className={`max-w-[80%] rounded-2xl px-3 py-2 text-xs leading-relaxed shadow-sm ${
          mine
            ? "rounded-br-md bg-gradient-to-br from-aria to-aria/80 text-white"
            : "rounded-bl-md border border-white/[0.06] bg-white/[0.05] text-ink"
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

  // Speaking a command sends it the moment recognition finalises the
  // utterance - a voice command that just sits typed in the box until
  // someone also clicks send isn't hands-free at all.
  const speech = useSpeechRecognition((text) => void send(text));

  useEffect(() => {
    if (speech.error) {
      useUIStore.getState().pushAlert({
        level: "error",
        message: `Voice input: ${speech.error}`,
      });
    }
  }, [speech.error]);

  // Collapsed: a floating launcher bubble, not nothing - so ARIA is always
  // one click away instead of vanishing until someone remembers "C".
  if (!open) {
    return (
      <motion.button
        type="button"
        initial={{ opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        whileHover={{ scale: 1.04 }}
        whileTap={{ scale: 0.97 }}
        onClick={() => useUIStore.getState().toggleChat()}
        title="Open ARIA (C)"
        className="flex items-center gap-2 rounded-full border border-white/10 bg-night/80
                   py-1.5 pl-1.5 pr-4 shadow-glass backdrop-blur-glass transition
                   hover:border-aria/50"
      >
        <AriaAvatar size={34} />
        <span className="font-display text-xs font-semibold text-ink">Ask ARIA</span>
      </motion.button>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.18 }}
      className="rm-glass flex h-[26rem] w-80 flex-col overflow-hidden
                 shadow-glowAria ring-1 ring-aria/15"
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] px-3 py-2.5">
        <div className="flex items-center gap-2.5">
          <AriaAvatar size={30} />
          <div className="leading-tight">
            <div className="font-display text-xs font-semibold text-ink">ARIA</div>
            <div className="text-[10px] text-ink-muted">Room companion</div>
          </div>
        </div>
        <button
          type="button"
          onClick={() => useUIStore.getState().toggleChat()}
          title="Hide (C)"
          className="rounded-md p-1.5 text-ink-muted transition hover:bg-white/[0.08] hover:text-ink"
        >
          <X size={14} />
        </button>
      </div>

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
          <div className="flex items-center gap-1.5 pl-6 text-[11px] text-ink-muted">
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
        {speech.supported && (
          <button
            type="button"
            onClick={speech.toggle}
            title={speech.listening ? "Stop listening" : "Speak a command"}
            className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full
                       transition ${
                         speech.listening
                           ? "animate-pulse bg-danger text-white"
                           : "bg-white/[0.06] text-ink-muted hover:bg-white/[0.12] hover:text-ink"
                       }`}
          >
            <Mic size={13} />
          </button>
        )}
        <input
          ref={inputRef}
          value={speech.listening ? speech.transcript : draft}
          onChange={(e) => useChatStore.getState().setDraft(e.target.value)}
          readOnly={speech.listening}
          placeholder={speech.listening ? "Listening…" : "Ask ARIA…"}
          className="flex-1 rounded-full border border-white/10 bg-black/30 px-3.5 py-1.5
                     text-xs outline-none transition placeholder:text-ink-muted/60
                     focus:border-aria/60 focus:ring-2 focus:ring-aria/20"
        />
        <button
          type="submit"
          disabled={!draft.trim() || thinking || speech.listening}
          className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full
                     bg-gradient-to-br from-aria to-glow text-night transition
                     hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40
                     disabled:hover:brightness-100"
        >
          <CornerDownLeft size={13} strokeWidth={2.5} />
        </button>
      </form>
    </motion.div>
  );
}
