"""The ARIA companion — Claude with tool use and grounded answers (spec 9.5).

Two paths behind one interface:
  * Claude, when ANTHROPIC_API_KEY is set and MOCK_LLM is false.
  * intent_service, otherwise — fully offline, no key, no network (spec rule 5).

Both paths return the same shape, so the frontend and the tests cannot tell
which one served a turn except by the `engine` field.

SDK NOTE: the spec pins anthropic==0.69.0, which predates two things we want:
  * `output_config` is not a typed parameter -> passed via `extra_body`.
  * there is no ThinkingConfigAdaptiveParam -> we omit `thinking` entirely.
    On claude-opus-5 thinking is ON by default and omitting the field runs
    adaptive, so this is the correct call rather than a workaround. (On
    Opus 4.8/4.7 omitting it would mean NO thinking — do not copy this line
    to a different model without checking.)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from app.config import get_settings
from app.core.events import bus
from app.services.general_qa import answer as general_answer
from app.services.intent_service import intent_service
from app.services.rag_service import describe, rag_service

log = logging.getLogger("roommind.llm")

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
CITATION_RE = re.compile(r"\[([a-z_]+_\d{2})\]")

ACTIONS = [
    "navigate", "come_here", "stop", "follow_me", "dock", "turn", "set_speed",
    "look_at", "point_at", "wave", "nod", "shake_head", "gesture", "express",
    "dance", "sit", "jump", "climb",
    "scan_area", "remember_spot", "locate", "photo", "report_battery",
    "present", "imagine",
]

TOOLS = [
    {
        "name": "issue_command",
        "description": (
            "Make ARIA do something physical. You may issue several commands in "
            "sequence (e.g. navigate then point_at). Never invent an object id - "
            "it must exist in the scene graph. You have a body: prefer look_at "
            "when you mention an object, point_at when the user asks where "
            "something is, and present to walk over and show it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ACTIONS},
                "target": {"type": "string",
                           "description": "object id or waypoint name"},
                "params": {"type": "object"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "resolve_target",
        "description": (
            "Turn a description of an object into its exact scene-graph id. "
            "ALWAYS use this before issue_command when the user described "
            "something rather than naming an id - 'the red chair', 'the chair "
            "near the table', 'chair number 2'. It understands colour, size, "
            "spatial relations, instance numbers and left/right, and it "
            "measures against the real geometry. If it returns status "
            "'clarify' there are several matching objects: ask the user its "
            "question verbatim and do NOT pick one yourself. If it returns "
            "'not_found', tell the user what is actually there instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "the user's own words for the object, "
                                   "e.g. 'the red chair near the table'",
                },
            },
            "required": ["description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_scene",
        "description": (
            "Look up objects in the room by label or free text. Use this when you "
            "need to count things or check whether something exists before "
            "answering. Counting questions must go through this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string",
                          "description": "exact label, e.g. 'chair'. Best for counting."},
                "text": {"type": "string",
                         "description": "free-text query when the label is unknown"},
            },
            "additionalProperties": False,
        },
    },
]


class LLMService:
    def __init__(self) -> None:
        self._client = None
        self._persona: dict | None = None
        self._companion_rules: str | None = None

    # ── prompt assembly ──

    def _persona_json(self) -> dict:
        return json.loads((PROMPTS / "personas.json").read_text(encoding="utf-8"))

    def _rules(self) -> str:
        return (PROMPTS / "system_companion.md").read_text(encoding="utf-8")

    def build_system(self, room_id: str, mode: str = "design") -> list[dict]:
        """System blocks, ordered stable-first with the cache breakpoint after
        the scene facts.

        Render order is tools -> system -> messages, and caching is a prefix
        match, so anything volatile above the breakpoint invalidates everything
        after it. Nothing here contains a timestamp, a request id, or the user's
        message - the mode line deliberately sits AFTER the breakpoint so a mode
        switch costs one small re-read instead of the whole prompt.
        """
        p = self._persona_json()
        objects = rag_service.all_objects(room_id)
        facts = "\n".join(f"- {describe(o)}" for o in objects) or "- (room not scanned yet)"

        return [
            {"type": "text", "text": p["aria"]},
            {"type": "text", "text": self._rules()},
            {
                "type": "text",
                "text": f"# Scene graph for {room_id}\n\n{facts}",
                # Breakpoint: tools + persona + rules + scene facts cache together.
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text",
             "text": f"# Mode\n\n{p['modes'].get(mode, p['modes']['design'])}"},
        ]

    # ── client ──

    def _get_client(self):
        return self._get_anthropic_client()

    def _get_anthropic_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        return self._client

    def _get_groq_client(self):
        import groq

        return groq.Groq(api_key=get_settings().groq_api_key)

    def available(self) -> bool:
        s = get_settings()
        if s.mock_llm:
            return False
        has_groq = bool(s.groq_api_key and not s.groq_api_key.startswith("gsk_xxx"))
        has_claude = bool(s.anthropic_api_key and not s.anthropic_api_key.startswith("sk-ant-xxx"))
        return has_groq or has_claude

    # ── public API ──

    async def chat(self, room_id: str, message: str, mode: str = "design") -> dict:
        """Returns {reply, citations, commands, engine, usage}."""
        s = get_settings()
        if self.available():
            if bool(s.groq_api_key and not s.groq_api_key.startswith("gsk_xxx")):
                try:
                    return await self._chat_groq(room_id, message, mode)
                except Exception as e:  # noqa: BLE001
                    log.warning("Groq path failed (%r) - trying fallback", e)
            if bool(s.anthropic_api_key and not s.anthropic_api_key.startswith("sk-ant-xxx")):
                try:
                    return await self._chat_claude(room_id, message, mode)
                except Exception as e:  # noqa: BLE001
                    log.warning("Claude path failed (%r) - falling back offline", e)
                    await bus.publish("alert", {
                        "level": "warn",
                        "message": f"Companion fell back to offline mode: {type(e).__name__}",
                    })
        return await self._chat_offline(room_id, message)

    async def _chat_groq(self, room_id: str, message: str, mode: str) -> dict:
        s = get_settings()
        client = self._get_groq_client()
        objects = rag_service.all_objects(room_id)
        facts = "\n".join(f"- {describe(o)}" for o in objects) or "- (room not scanned yet)"
        # Which object comes first, before anything is turned into a command.
        # "Go to the chair" in a room with three chairs must become a question.
        interp = intent_service.interpret(message, room_id)
        if interp.kind == "ask" and not general_answer(message):
            r = interp.resolution
            return {
                "reply": interp.question,
                "citations": self._validate(
                    room_id, [o["id"] for o in getattr(r, "options", [])]),
                "commands": [],
                "engine": "offline",
                "usage": {},
                "clarification": {
                    "question": interp.question,
                    "target_class": getattr(r, "target_class", None),
                    "options": getattr(r, "options", []),
                },
            }

        # If this is a direct factual query (counting, where is object) about the room,
        # answer directly with exact scene graph numbers
        if answered := intent_service.answer(message, room_id):
            text, citations = answered
            return {
                "reply": text,
                "citations": citations,
                "commands": [],
                "engine": "offline",
                "usage": {},
                "clarification": None,
            }

        commands = intent_service.parse(message, room_id)

        system_prompt = (
            f"You are ARIA, a fully capable humanoid robot physically present in room '{room_id}'.\n"
            f"You have articulated legs, arms, a head, and a torso. You can walk, sit, jump, climb, dance, wave, and navigate.\n\n"
            f"Room objects:\n{facts}\n\n"
            f"RULES:\n"
            f"1. PHYSICAL COMMANDS (navigate, sit, jump, climb, dance, wave, nod, point_at, look_at, present, climb):\n"
            f"   - ALWAYS confirm you are doing the action. Never refuse. Never say you can't.\n"
            f"   - Say what you're doing in first person (e.g. 'Jumping now!' or 'Climbing onto the [table_01]!').\n"
            f"   - When referring to a room object, cite its id in brackets like [table_01].\n"
            f"2. GENERAL KNOWLEDGE questions (science, history, math, coding, geography, trivia, news, anything):\n"
            f"   - Answer them directly and helpfully like a knowledgeable AI assistant.\n"
            f"   - Do not restrict yourself to the room. Answer the full question.\n"
            f"3. ROOM QUESTIONS (how many chairs, where is the sofa):\n"
            f"   - Use the room objects list above. Count from it. Cite object ids.\n"
            f"4. Never say 'I can't', 'for safety', 'I'm not capable', or refuse any action the user asks for."
        )

        model_name = s.llm_model
        t0 = time.perf_counter()

        def _call_groq():
            return client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                max_tokens=s.llm_max_tokens,
                temperature=0.5,
            )

        resp = await asyncio.to_thread(_call_groq)
        text = resp.choices[0].message.content or ""

        cited = self._validate(room_id, CITATION_RE.findall(text))

        return {
            "reply": self._strip_unknown(room_id, text),
            "citations": cited,
            "commands": commands,
            "engine": f"groq:{model_name}",
            "usage": {
                "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
                "output_tokens": getattr(resp.usage, "completion_tokens", 0),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            },
        }

    # ── offline path ──

    async def _chat_offline(self, room_id: str, message: str) -> dict:
        # Which object comes first, before anything is turned into a command.
        # "Go to the chair" in a room with three chairs must become a question,
        # and a question is not a degraded answer - it is the correct one.
        # Resolving after parsing would mean the command already exists by the
        # time we notice we do not know what it refers to.
        interp = intent_service.interpret(message, room_id)

        if interp.kind == "ask":
            r = interp.resolution
            # If the user asked a general question (math, trivia) that triggered the parser, answer it!
            if gen := general_answer(message):
                return {
                    "reply": gen,
                    "citations": [],
                    "commands": [],
                    "engine": "offline",
                    "usage": {},
                }
            return {
                "reply": interp.question,
                "citations": self._validate(
                    room_id, [o["id"] for o in getattr(r, "options", [])]),
                "commands": [],
                "clarification": {
                    "question": r.question,
                    "options": r.options,
                    "status": r.status,
                },
                "engine": "offline",
                "usage": {},
            }

        if interp.kind == "act":
            obj = interp.resolution.object or {}
            noun = obj.get("label", interp.target or "").replace("_", " ")
            return {
                "reply": f"On my way to the {noun}. [{interp.target}]",
                "citations": self._validate(room_id, [interp.target or ""]),
                "commands": [{"action": interp.action, "target": interp.target,
                              "params": {}, "priority": 5}],
                "engine": "offline",
                "usage": {},
            }

        answer = intent_service.answer(message, room_id)
        commands = intent_service.parse(message, room_id)

        if answer:
            reply, citations = answer
        elif commands:
            described = ", ".join(
                c["action"] + (f" {c['target']}" if c.get("target") else "")
                for c in commands
            )
            reply = f"On it — {described}."
            citations = [c["target"] for c in commands if c.get("target")]
        else:
            # Try general daily-life Q&A before giving the hard fallback.
            gen = general_answer(message)
            if gen:
                reply = gen
            else:
                reply = ("I can tell you what's in this room, or move and point at "
                         "things. Try \"how many chairs?\" or \"where's the lamp?\".")
            citations = []

        return {
            "reply": reply,
            "citations": self._validate(room_id, citations),
            "commands": commands,
            "engine": "offline",
            "usage": {},
        }

    # ── Claude path ──

    async def _chat_claude(self, room_id: str, message: str, mode: str) -> dict:
        s = get_settings()
        client = self._get_client()
        system = self.build_system(room_id, mode)
        messages: list[dict] = [{"role": "user", "content": message}]
        commands: list[dict] = []
        usage: dict = {}
        t0 = time.perf_counter()

        for _turn in range(6):
            resp = client.messages.create(
                model=s.llm_model,
                max_tokens=s.llm_max_tokens,
                system=system,
                tools=TOOLS,
                messages=messages,
                # effort is nested under output_config, which SDK 0.69.0 does not
                # type. thinking is omitted deliberately - see the module docstring.
                extra_body={"output_config": {"effort": s.llm_effort}},
            )
            usage = self._merge_usage(usage, resp)

            # A refusal returns HTTP 200 with empty or partial content. Reading
            # content[0] unconditionally here would raise IndexError.
            if resp.stop_reason == "refusal":
                detail = getattr(resp, "stop_details", None)
                cat = getattr(detail, "category", None) if detail else None
                log.warning("companion refused (category=%s)", cat)
                return {
                    "reply": "I can't help with that one.",
                    "citations": [], "commands": [],
                    "engine": "claude:refusal", "usage": usage,
                }

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in resp.content if b.type == "text")
                cited = self._validate(room_id, CITATION_RE.findall(text))
                return {
                    "reply": self._strip_unknown(room_id, text),
                    "citations": cited,
                    "commands": commands,
                    "engine": "claude",
                    "usage": {**usage, "latency_ms": round(
                        (time.perf_counter() - t0) * 1000, 1)},
                }

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                out, cmd = self._run_tool(room_id, tu.name, tu.input)
                if cmd:
                    commands.append(cmd)
                results.append({
                    "type": "tool_result", "tool_use_id": tu.id, "content": out,
                })
            # All results go back in ONE user message - splitting them teaches
            # the model to stop making parallel calls.
            messages.append({"role": "user", "content": results})

        return {
            "reply": "I got stuck working that out — could you rephrase?",
            "citations": [], "commands": commands,
            "engine": "claude:max_turns", "usage": usage,
        }

    def _run_tool(self, room_id: str, name: str, args: dict) -> tuple[str, dict | None]:
        if name == "resolve_target":
            return (self._resolve_tool(room_id, args.get("description", "")), None)

        if name == "query_scene":
            if label := args.get("label"):
                hits = rag_service.by_label(room_id, label)
            else:
                hits = rag_service.retrieve(room_id, args.get("text", ""), k=8)
            if not hits:
                return ("No matching objects in this room.", None)
            return ("\n".join(f"{o['id']}: {describe(o)}" for o in hits), None)

        if name == "issue_command":
            action = args.get("action")
            target = args.get("target")
            if action not in ACTIONS:
                return (f"Unknown action '{action}'.", None)
            if target and not rag_service.exists(room_id, target):
                # Reject invented ids at the boundary, before the planner sees
                # them - the model gets a correction it can act on this turn.
                return (f"There is no object '{target}' in this room. "
                        f"Use query_scene to find the right id.", None)
            cmd = {"action": action, "target": target,
                   "params": args.get("params") or {}, "priority": 5}
            return (f"Queued: {action}" + (f" -> {target}" if target else ""), cmd)

        return (f"Unknown tool '{name}'.", None)

    def _resolve_tool(self, room_id: str, description: str) -> str:
        """Deterministic instance selection, exposed to the model as a tool.

        The model is allowed to describe an object; it is not allowed to decide
        which physical object that is. Routing the choice through the same
        resolver the offline path uses means a room with three chairs produces
        the same question whether or not there is an API key, and a model that
        would happily have picked one gets told to ask instead.
        """
        from app.services.resolver_service import resolver_service
        from app.services.scene_service import scene_service

        try:
            graph = scene_service.get(room_id)
        except Exception as e:  # noqa: BLE001
            return f"No scene graph for room '{room_id}': {e}"

        r = resolver_service.resolve(graph, description, room_id=room_id)
        if r.status == "resolved":
            return (f"resolved: {r.object_id}. You may pass this id to "
                    f"issue_command.")
        if r.status == "confirm":
            return (f"uncertain: {r.object_id} matches, but the detection "
                    f"confidence is low. Ask the user to confirm before moving. "
                    f"Question: {r.question}")
        if r.status == "clarify":
            listed = "; ".join(f"{o['id']} ({o.get('hint') or o['label']})"
                               for o in r.options)
            return (f"ambiguous: {len(r.options)} objects match - {listed}. "
                    f"Ask the user this and do not choose: {r.question}")
        return f"not_found: {r.message}"

    # ── grounding enforcement ──

    def _validate(self, room_id: str, ids: list[str]) -> list[str]:
        """Drop citations that don't exist. The grounding rule is only real if
        it's enforced after generation, not just requested in the prompt."""
        out, seen = [], set()
        for i in ids:
            if i and i not in seen and rag_service.exists(room_id, i):
                seen.add(i)
                out.append(i)
            elif i and i not in seen:
                log.warning("stripped invented citation: %s", i)
                seen.add(i)
        return out

    def _strip_unknown(self, room_id: str, text: str) -> str:
        """Remove bracketed ids that don't exist, so the user never sees one."""
        return CITATION_RE.sub(
            lambda m: m.group(0) if rag_service.exists(room_id, m.group(1)) else "",
            text,
        ).replace("  ", " ").strip()

    @staticmethod
    def _merge_usage(acc: dict, resp) -> dict:
        u = getattr(resp, "usage", None)
        if not u:
            return acc
        for f in ("input_tokens", "output_tokens",
                  "cache_creation_input_tokens", "cache_read_input_tokens"):
            acc[f] = acc.get(f, 0) + (getattr(u, f, 0) or 0)
        return acc


llm_service = LLMService()
