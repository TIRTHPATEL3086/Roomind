"""Offline NL -> Command JSON (spec 9.7).

This is the path that runs with MOCK_LLM=true and the network unplugged
(spec rule 5). It is rule-based on purpose: no model download, no API key,
fully deterministic, and testable without a fixture server.

It also answers simple grounded questions ("how many chairs?", "where's the
lamp?") from the scene graph, so the offline demo still shows the companion
answering rather than only executing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.query_parse import parse_target
from app.services.rag_service import SYNONYMS, rag_service
from app.services.resolver_service import resolver_service
from app.services.scene_service import scene_service

# Ordered: the first match wins, so specific patterns precede general ones.
# "point at the lamp" must beat the bare "look" verb.
VERB_MAP: list[tuple[str, str]] = [
    (r"\b(stop|halt|freeze|abort|emergency)\b", "stop"),
    (r"\b(point (at|to)|show me where)\b", "point_at"),
    (r"\b(take me to|walk me to|present|show me the)\b", "present"),
    (r"\b(look at|face|turn to|watch)\b", "look_at"),
    (r"\b(go|drive|move|navigate|head)\b.*\bto\b", "navigate"),
    (r"\bcome (here|to me|over)\b", "come_here"),
    (r"\bfollow me\b", "follow_me"),
    (r"\b(go home|dock|charge|go to your dock)\b", "dock"),
    (r"\b(take|snap) a (photo|picture|pic)\b", "photo"),
    (r"\b(wave|say hi|say hello)\b", "wave"),
    (r"\b(nod|say yes)\b", "nod"),
    (r"\b(shake your head|say no)\b", "shake_head"),
    (r"\b(shrug|celebrate)\b", "gesture"),
    (r"\bdance\b", "dance"),
    (r"\b(battery|charge level|how much power)\b", "report_battery"),
    (r"\bscan\b", "scan_area"),
    (r"\bremember this (spot|place|position)\b", "remember_spot"),
    (r"\bturn (left|right|around)\b", "turn"),
    (r"\b(imagine|add|create|generate|put) (a|an|this)\b", "imagine"),
    (r"\bwhere('s| is| are)\b", "locate"),
]

TARGETED = {"navigate", "look_at", "point_at", "present", "locate", "imagine"}

# The subset that MOVES or AIMS ARIA at one specific object, and therefore has
# to know exactly which one. `locate` is excluded on purpose: "where's the
# lamp?" is a question, and `answer()` gives it a better reply than the
# resolver's clarification machinery would.
MOVEMENT_VERBS = {"navigate", "present", "point_at", "look_at"}


@dataclass
class Interpretation:
    """What to do with a message: act on it, ask about it, or neither."""

    kind: str                       # "act" | "ask" | "none"
    resolution: object | None = None
    action: str | None = None
    target: str | None = None

    @property
    def question(self) -> str:
        r = self.resolution
        return (getattr(r, "question", None) or getattr(r, "message", "")) if r else ""

COUNT_RE = re.compile(r"\bhow many\s+([a-z_ ]+?)(?:\s+are|\s+do|\s+is|\?|$)")
WHERE_RE = re.compile(r"\bwhere('s| is| are)\s+(?:the\s+|my\s+|a\s+)?([a-z_ ]+?)(?:\?|$)")


class IntentService:
    # ── command parsing ──

    def parse(self, text: str, room_id: str) -> list[dict]:
        """NL -> zero or more Command dicts (spec 8.3).

        Targets for the actions that need one go through the resolver, so
        "the red chair near the table" picks the same object here as it does
        through /commands/nl. When the resolver cannot pick one it returns
        nothing rather than something: `clarify(...)` reports the question, and
        the caller asks it instead of moving. Guessing here would be worse than
        anywhere else in the system, because this is the offline path that runs
        when there is no model to catch the mistake.
        """
        t = text.lower().strip()

        # Stop wins outright, before any other parsing, and is priority 10.
        if re.search(r"\b(stop|halt|freeze|abort)\b", t):
            return [{"action": "stop", "target": None, "params": {}, "priority": 10}]

        actions = [a for pat, a in VERB_MAP if re.search(pat, t)]
        if not actions:
            return []

        # Preserve the order the verbs appear in the sentence: "go to the table
        # and point at the lamp" must navigate first.
        actions = sorted(
            dict.fromkeys(actions),
            key=lambda a: min(
                (m.start() for pat, a2 in VERB_MAP if a2 == a
                 for m in [re.search(pat, t)] if m),
                default=999,
            ),
        )

        targets = self._resolve_targets(t, room_id)
        cmds: list[dict] = []
        for i, action in enumerate(actions):
            params: dict = {}
            if action == "turn":
                m = re.search(r"(\d+)\s*(deg|degrees|°)?", t)
                deg = int(m.group(1)) if m else (180 if "around" in t else 90)
                params["degrees"] = -deg if "left" in t else deg
            if action == "gesture":
                params["name"] = "celebrate" if "celebrate" in t else "shrug"
            # Multiple targets in one sentence pair positionally with the verbs.
            target = None
            if action in TARGETED and targets:
                target = targets[min(i, len(targets) - 1)]
            cmds.append({"action": action, "target": target,
                         "params": params, "priority": 5})
        return cmds

    def interpret(self, text: str, room_id: str,
                  viewer: dict | None = None) -> Interpretation:
        """Decide whether this message moves ARIA, asks a question, or neither.

        Two entry points into the same resolver:

        * a REPLY to an open clarification — "the red one", "number 2". These
          carry no verb at all, so nothing else in the intent pipeline would
          look twice at them; the pending question supplies both the class and
          the action the user originally asked for.
        * a fresh movement command — "go to the chair near the table".

        Questions about the room are left alone. "How many chairs are there?"
        is answered by `answer()`, and replying "I found three chairs, which
        one do you mean?" to someone who just asked how many there were would
        be absurd.
        """
        t = (text or "").lower().strip()
        try:
            graph = scene_service.get(room_id)
        except Exception:  # noqa: BLE001
            return Interpretation("none")

        if resolver_service.looks_like_a_reply(text, room_id):
            action = resolver_service.pending_action(room_id) or "navigate"
            r = resolver_service.resolve(graph, text, viewer=viewer,
                                         room_id=room_id, action=action)
            if r.status == "resolved":
                return Interpretation("act", resolution=r, action=action,
                                      target=r.object_id)
            # Still ambiguous, still uncertain, or the reply ruled everything
            # out ("the purple one" when none are purple). All three are worth
            # saying out loud rather than falling through to a generic reply.
            return Interpretation("ask", resolution=r)

        verbs = [a for pat, a in VERB_MAP
                 if a in MOVEMENT_VERBS and re.search(pat, t)]
        if not verbs:
            return Interpretation("none")
        if len(verbs) > 1:
            # "Go to the table and point at the lamp" is a SEQUENCE, and this
            # step resolves one target for one action. Handing back a single
            # command would silently drop the second half of the sentence, so
            # the multi-verb case goes to `parse()`, which pairs verbs with
            # targets positionally. `_resolve_targets` still runs each of those
            # through the resolver, so the extra understanding is not lost.
            return Interpretation("none")

        query = parse_target(text)
        if query.object_class is None and not query.explicit_id:
            return Interpretation("none")

        action = verbs[0]
        r = resolver_service.resolve(graph, text, viewer=viewer,
                                     room_id=room_id, action=action)
        if r.status == "resolved":
            return Interpretation("act", resolution=r, action=action,
                                  target=r.object_id)
        return Interpretation("ask", resolution=r)

    def _resolve_targets(self, t: str, room_id: str) -> list[str]:
        """Object ids mentioned, in the order they appear in the sentence.

        The positional scan runs FIRST, because it is the only thing that can
        see that a sentence mentions two different objects. The resolver
        answers "which chair", not "how many things were named", so letting it
        answer first would collapse "go to the table and point at the lamp"
        into a single target and quietly drop half the sentence.

        So: scan positionally, and only upgrade to the resolver when the
        sentence names at most one thing. Then a single-target sentence gets
        colour, spatial relations and instance numbers, and a multi-target one
        keeps its ordering.
        """
        found: list[tuple[int, str]] = []
        for obj in rag_service.all_objects(room_id):
            oid = obj["id"]
            if (pos := t.find(oid)) >= 0:
                found.append((pos, oid))
                continue
            label = obj["label"].replace("_", " ")
            if (pos := t.find(label)) >= 0:
                found.append((pos, oid))
        # user words -> labels ("couch" -> sofa_01)
        for word, label in SYNONYMS.items():
            if (pos := t.find(word)) >= 0:
                for obj in rag_service.by_label(room_id, label):
                    found.append((pos, obj["id"]))
        seen: set[str] = set()
        out: list[str] = []
        for _, oid in sorted(found):
            if oid not in seen:
                seen.add(oid)
                out.append(oid)

        # One thing named -> let the resolver say WHICH one. The positional
        # scan matches on the label alone, so it happily returns the first of
        # three chairs for "the red chair"; the resolver reads the colour.
        distinct_labels = {oid.rsplit("_", 1)[0] for oid in out}
        if len(distinct_labels) <= 1:
            try:
                graph = scene_service.get(room_id)
            except Exception:  # noqa: BLE001
                return out
            resolution = resolver_service.resolve(graph, t, room_id=room_id,
                                                  remember=False)
            if resolution.ok and resolution.object_id:
                return [resolution.object_id]
        return out

    # ── offline grounded answers ──

    def answer(self, text: str, room_id: str) -> tuple[str, list[str]] | None:
        """Answer a simple factual question from the graph. Returns
        (reply, citations) or None if this isn't a question we can answer.

        Every branch cites real ids, exactly like the LLM path - so the offline
        demo shows grounded answers, not a degraded 'I can't do that'.
        """
        t = text.lower().strip()

        if m := COUNT_RE.search(t):
            label = m.group(1).strip().rstrip("s") or m.group(1).strip()
            hits = rag_service.by_label(room_id, label) or rag_service.by_label(
                room_id, m.group(1).strip()
            )
            if not hits:
                return (f"I don't see any {m.group(1).strip()} in here.", [])
            noun = hits[0]["label"].replace("_", " ")
            plural = noun if len(hits) == 1 else f"{noun}s"
            cites = " ".join(f"[{o['id']}]" for o in hits)
            return (f"{self._count_word(len(hits))} {plural}. {cites}",
                    [o["id"] for o in hits])

        if m := WHERE_RE.search(t):
            hits = rag_service.by_label(room_id, m.group(2).strip())
            if not hits:
                hits = rag_service.retrieve(room_id, m.group(2).strip(), k=1)
            if not hits:
                return (f"I don't see a {m.group(2).strip()} in here.", [])

            if len(hits) > 1:
                # "Where's the chair?" in a room with three of them has three
                # answers, and picking one to point at is the same silent coin
                # flip the resolver refuses to make for navigation. Report them
                # all, cite them all, and let the user narrow it down.
                noun = hits[0]["label"].replace("_", " ")
                listed = ", ".join(
                    f"{o['id'].rsplit('_', 1)[1].lstrip('0') or '0'} at x "
                    f"{o['position'][0]:.1f}, z {o['position'][2]:.1f} [{o['id']}]"
                    for o in hits)
                return (f"There are {len(hits)} {noun}s: {listed}. "
                        f"Which one did you mean?",
                        [o["id"] for o in hits])

            o = hits[0]
            x, _, z = o["position"]
            return (
                f"The {o['label'].replace('_', ' ')} is at x {x:.1f}, z {z:.1f} "
                f"— I'm pointing at it now. [{o['id']}]",
                [o["id"]],
            )

        if re.search(r"\bwhat('s| is)? (in|around) (the |this )?room\b|"
                     r"\bwhat (can you |do you )?see\b", t):
            objs = rag_service.all_objects(room_id)
            if not objs:
                return ("I haven't scanned this room yet.", [])
            labels = sorted({o["label"].replace("_", " ") for o in objs})
            cites = " ".join(f"[{o['id']}]" for o in objs[:6])
            return (f"I can see {len(objs)} things: {', '.join(labels)}. {cites}",
                    [o["id"] for o in objs])

        return None

    @staticmethod
    def _count_word(n: int) -> str:
        words = {0: "No", 1: "One", 2: "Two", 3: "Three", 4: "Four",
                 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}
        return words.get(n, str(n))


intent_service = IntentService()
