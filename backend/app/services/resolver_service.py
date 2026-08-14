"""Target resolution: which physical object did the user mean?

This is step C of the command pipeline, and the rule that shapes all of it is
that **a language model is never the final authority on which object ARIA
drives to**. The parser turns words into constraints; this filters the scene
graph by those constraints; what survives decides the answer. A model may
propose, and its proposal is re-checked here against real geometry before
anything moves.

The pipeline, in order:

    1. candidates  = every object of the requested class
    2. filter      by explicit id, then instance number, colour, size,
                    spatial relations, and finally viewpoint (left / right /
                    nearest)
    3. exactly one survivor  -> resolved
       none                  -> not_found, and say what IS there
       several               -> a question, never a guess

Step 3's last branch is the whole feature. With three chairs in the room and
nothing but "go to the chair" to go on, picking one is a coin flip the user
cannot see being tossed: ARIA looks confident, drives to the wrong chair, and
nothing in the system ever registers that it went wrong. Asking costs one turn
and is always right.

The one exception is a query that ASKS for a ranking — "the nearest chair" is
an instruction to pick, and picking is then the correct answer.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.core import spatial
from app.core.colors import matches as color_matches
from app.core.enrich import LOW_CONFIDENCE
from app.core.query_parse import TargetQuery, parse_target
from app.core.vocabulary import class_matches

log = logging.getLogger("roommind.resolver")

# A clarification the user never answered goes stale rather than lingering, so
# an unrelated command five minutes later is not read as a late reply.
PENDING_TTL_S = 180.0

# How much better the top candidate must score before a RANKING query (nearest,
# leftmost) is treated as decisive. Two chairs equidistant to within 12 cm are
# not meaningfully "the nearest one", and answering as if they were is the same
# coin flip the whole module exists to avoid.
RANK_MARGIN_M = 0.12


@dataclass
class Resolution:
    """What the resolver decided, and why."""

    status: str                       # resolved | clarify | not_found | confirm
    query: TargetQuery
    object_id: str | None = None
    object: dict | None = None
    options: list[dict] = field(default_factory=list)
    question: str | None = None
    message: str = ""
    frame: str | None = None          # which viewpoint left/right was measured from
    matched: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "resolved"

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "target": self.object_id,
            "message": self.message,
            "question": self.question,
            "options": self.options,
            "frame": self.frame,
            "matched": self.matched,
            "query": {
                "class": self.query.object_class,
                "colors": self.query.colors,
                "size": self.query.size,
                "ordinal": self.query.ordinal,
                "egocentric": self.query.egocentric,
                "relations": [
                    {"rel": r.rel, "class": r.other_class, "id": r.other_id}
                    for r in self.query.relations
                ],
            },
        }


@dataclass
class _Pending:
    query: TargetQuery
    candidate_ids: list[str]
    at: float
    # What the user was trying to DO when the question came up. Kept so the
    # answer can be carried out: a reply of "the red one" has no verb in it,
    # and without this the system would know which chair and have forgotten
    # that it was supposed to drive to it.
    action: str = "navigate"


class ResolverService:
    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    # ── public API ──

    def resolve(self, graph: dict, text: str, viewer: dict | None = None,
                room_id: str | None = None, remember: bool = True,
                action: str = "navigate") -> Resolution:
        """Resolve a phrase against a scene graph. Never picks at random.

        `remember=False` makes the call a pure lookup: it still reads a pending
        question but does not open a new one. Callers that merely want to know
        what a sentence refers to must use it, or every speculative lookup
        arms a clarification that the NEXT sentence is then read as a reply to.
        """
        room_id = room_id or graph.get("room_id", "")
        query = parse_target(text)
        objects = graph.get("objects") or []

        restrict: list[str] | None = None
        if (pending := self._take_pending(room_id)) is not None:
            if self._is_reply_to(query, pending):
                query = query.merged_with(pending.query)
                restrict = pending.candidate_ids
                log.info("treating %r as a reply to the pending question", text)
            else:
                # A different question entirely — drop the old one rather than
                # letting it colour an unrelated command.
                pass

        return self._resolve_query(graph, objects, query, viewer, room_id,
                                   restrict, remember, action)

    def clear_pending(self, room_id: str) -> None:
        self._pending.pop(room_id, None)

    def has_pending(self, room_id: str) -> bool:
        return self._take_pending(room_id) is not None

    def pending_action(self, room_id: str) -> str | None:
        """What the unanswered question was trying to do, if there is one."""
        pending = self._take_pending(room_id)
        return pending.action if pending else None

    def looks_like_a_reply(self, text: str, room_id: str) -> bool:
        """Would this message be read as an answer to the open question?

        Lets the caller decide to run the pending branch at all. A reply to
        "which chair?" carries no verb, so nothing else in the intent pipeline
        would give it a second look.
        """
        pending = self._take_pending(room_id)
        return bool(pending and self._is_reply_to(parse_target(text), pending))

    # ── the pipeline ──

    def _resolve_query(self, graph: dict, objects: list[dict], query: TargetQuery,
                       viewer: dict | None, room_id: str,
                       restrict: list[str] | None,
                       remember: bool = True,
                       action: str = "navigate") -> Resolution:
        by_id = {o["id"]: o for o in objects}

        # An explicit id short-circuits everything. It is either real or it is
        # not, and no amount of filtering makes an id that does not exist mean
        # something else.
        if query.explicit_id:
            obj = by_id.get(query.explicit_id)
            if obj is None:
                return Resolution(
                    status="not_found", query=query,
                    message=f"There is no {query.explicit_id} in this room.")
            return self._accept(obj, query, room_id, matched=1)

        if not query.object_class:
            return Resolution(
                status="not_found", query=query,
                message="I couldn't tell which object you meant. Name the thing "
                        "you want me to go to — a chair, the table, the TV.")

        candidates = [o for o in objects
                      if class_matches((o.get("attributes") or {}).get("class")
                                       or o["label"], query.object_class)]
        if restrict is not None:
            narrowed = [o for o in candidates if o["id"] in restrict]
            # Only honour the restriction if it leaves anything; a reply naming
            # a different class is a new question, not an empty answer.
            candidates = narrowed or candidates

        if not candidates:
            return Resolution(
                status="not_found", query=query,
                message=self._nothing_of_that_class(objects, query))

        total_of_class = len(candidates)

        # ── instance number ──
        if query.ordinal is not None:
            numbered = [o for o in candidates
                        if (o.get("attributes") or {}).get("instance_index")
                        == query.ordinal]
            if not numbered:
                names = ", ".join(sorted(o["id"] for o in candidates))
                return Resolution(
                    status="not_found", query=query, matched=0,
                    message=f"There is no {query.object_class.replace('_', ' ')} "
                            f"number {query.ordinal}. I have {names}.")
            candidates = numbered

        # ── colour ──
        if query.colors:
            wanted = query.colors
            kept = [o for o in candidates
                    if any(color_matches(c, (o.get("attributes") or {}).get("color"))
                           for c in wanted)]
            if not kept:
                return Resolution(
                    status="not_found", query=query, matched=0,
                    message=self._no_such_colour(candidates, query))
            candidates = kept

        # ── size ──
        if query.size:
            kept = [o for o in candidates
                    if (o.get("attributes") or {}).get("size_class") == query.size]
            if kept:
                candidates = kept
            elif len(candidates) > 1:
                # Size classes are only assigned when instances actually differ
                # in size, so an unmatched size word means "they are all the
                # same size" — fall back to raw volume rather than dropping
                # every candidate over a word we cannot honour precisely.
                candidates = self._extreme_by(
                    candidates, spatial.volume, largest=query.size == "large")

        # ── spatial relations ──
        for constraint in query.relations:
            targets = self._relation_targets(objects, constraint)
            if not targets:
                return Resolution(
                    status="not_found", query=query, matched=0,
                    message=f"I can't see a "
                            f"{(constraint.other_class or 'thing').replace('_', ' ')} "
                            f"in here to measure that against.")
            kept = [o for o in candidates
                    if spatial.has_relation(o, constraint.rel, targets)]
            if not kept:
                return Resolution(
                    status="not_found", query=query, matched=0,
                    message=self._no_such_relation(query, constraint))
            # Nearest first, so a later ranking step has something to order by.
            kept.sort(key=lambda o: spatial.relation_distance(
                o, constraint.rel, targets))
            candidates = kept

        # ── viewpoint ──
        frame = None
        if query.egocentric:
            candidates, frame, decisive = self._apply_viewpoint(
                candidates, query.egocentric, viewer, graph)
            if not candidates:
                return Resolution(
                    status="not_found", query=query, matched=0, frame=frame,
                    message=f"I don't see a "
                            f"{query.object_class.replace('_', ' ')} "
                            f"on the {query.egocentric}.")
            if decisive and len(candidates) >= 1:
                return self._accept(candidates[0], query, room_id,
                                    matched=total_of_class, frame=frame)

        if len(candidates) == 1:
            return self._accept(candidates[0], query, room_id,
                                matched=total_of_class, frame=frame)

        return self._ask(candidates, query, room_id, total_of_class, frame,
                         remember, action)

    # ── outcomes ──

    def _accept(self, obj: dict, query: TargetQuery, room_id: str,
                matched: int, frame: str | None = None) -> Resolution:
        """One survivor. Confirm first if the detection itself is shaky."""
        self.clear_pending(room_id)
        attrs = obj.get("attributes") or {}
        confidence = float(obj.get("confidence", 1.0))
        uncertain = bool(attrs.get("uncertain")) or confidence < LOW_CONFIDENCE

        if uncertain:
            # The object is on the map and A* will still avoid it, but acting on
            # it means trusting a detection the pipeline itself flagged. Ask.
            return Resolution(
                status="confirm", query=query, object_id=obj["id"], object=obj,
                matched=matched, frame=frame,
                options=[self._option(obj, [obj])],
                question=f"I think that's a "
                         f"{obj['label'].replace('_', ' ')} ({confidence:.0%} "
                         f"confident) — should I go to it?",
                message=f"Low confidence in {obj['id']}.")

        return Resolution(
            status="resolved", query=query, object_id=obj["id"], object=obj,
            matched=matched, frame=frame,
            message=f"{obj['id']} matched {query.describe()}.")

    def _ask(self, candidates: list[dict], query: TargetQuery, room_id: str,
             total: int, frame: str | None, remember: bool = True,
             action: str = "navigate") -> Resolution:
        """Several survivors and nothing to separate them. Ask, do not guess."""
        options = [self._option(o, candidates) for o in candidates]
        if remember:
            self._pending[room_id] = _Pending(
                query=query, candidate_ids=[o["id"] for o in candidates],
                at=time.monotonic(), action=action)

        noun = (query.object_class or "object").replace("_", " ")
        hints = [o["hint"] for o in options if o["hint"]]
        if len(hints) == len(options) and len(set(hints)) == len(hints):
            listed = ", ".join(hints[:-1]) + f", or {hints[-1]}"
            question = (f"I found {len(candidates)} {noun}s. Which one do you "
                        f"mean: {listed}?")
        else:
            listed = ", ".join(o["id"] for o in options)
            question = (f"I found {len(candidates)} {noun}s ({listed}). "
                        f"Which one do you mean?")

        return Resolution(
            status="clarify", query=query, options=options, question=question,
            matched=total, frame=frame,
            message=f"{len(candidates)} candidates for {query.describe()}.")

    # ── option hints ──

    def _option(self, obj: dict, siblings: list[dict]) -> dict:
        attrs = obj.get("attributes") or {}
        color = attrs.get("color") or {}
        return {
            "id": obj["id"],
            "label": obj["label"],
            "color": color.get("value"),
            "color_hex": obj.get("color"),
            "size_class": attrs.get("size_class"),
            "position": [round(float(v), 3) for v in obj["position"]],
            "confidence": obj.get("confidence"),
            "hint": self._hint(obj, siblings),
        }

    def _hint(self, obj: dict, siblings: list[dict]) -> str | None:
        """The shortest phrase that tells this candidate from the others.

        Tried in the order a person would: colour, then size, then what it is
        next to, then its number. A question that offers "chair_01, chair_02 or
        chair_03" is technically unambiguous and completely useless out loud;
        "the red one, the black one, or the blue one" is answerable.
        """
        attrs = obj.get("attributes") or {}

        colour = (attrs.get("color") or {}).get("value")
        if colour and colour != "unknown":
            others = {(s.get("attributes") or {}).get("color", {}).get("value")
                      for s in siblings if s["id"] != obj["id"]}
            if colour not in others:
                return f"the {colour} one"

        size = attrs.get("size_class")
        if size:
            others = {(s.get("attributes") or {}).get("size_class")
                      for s in siblings if s["id"] != obj["id"]}
            if size not in others:
                return f"the {size} one"

        for rel in attrs.get("relations", []):
            if rel.get("rel") != "near":
                continue
            neighbour = rel.get("to", "")
            neighbour_class = neighbour.rsplit("_", 1)[0].replace("_", " ")
            # only useful if no sibling is near the same kind of thing
            clash = any(
                any(r.get("rel") == "near"
                    and r.get("to", "").rsplit("_", 1)[0] == neighbour.rsplit("_", 1)[0]
                    for r in (s.get("attributes") or {}).get("relations", []))
                for s in siblings if s["id"] != obj["id"])
            if not clash:
                return f"the one near the {neighbour_class}"

        if (index := attrs.get("instance_index")) is not None:
            return f"number {index}"
        return None

    # ── helpers ──

    def _relation_targets(self, objects: list[dict], constraint) -> set[str]:
        if constraint.other_id:
            return {constraint.other_id}
        return {
            o["id"] for o in objects
            if class_matches((o.get("attributes") or {}).get("class") or o["label"],
                             constraint.other_class or "")
        }

    def _apply_viewpoint(self, candidates: list[dict], kind: str,
                         viewer: dict | None,
                         graph: dict) -> tuple[list[dict], str, bool]:
        """Filter or rank by where the candidates are from a point of view.

        WHOSE left is the question, and the honest answer is ARIA's — she is
        the one being told to go there, and a robot that interprets "on your
        left" as "on the left of the room" is wrong in the way that gets a
        demo laughed at. Her live pose is used when telemetry has given us one.

        With no pose there is no egocentric frame at all, and rather than
        inventing one the fall-back is the ROOM frame from spec 8.1: facing +Z,
        where +X is right. That convention is stated in the return value so the
        answer can say which frame it used instead of leaving it ambiguous.
        """
        if viewer and viewer.get("known"):
            origin = (float(viewer["x"]), float(viewer["z"]))
            yaw = float(viewer.get("yaw", 0.0))
            frame = "robot"
        else:
            origin = (0.0, 0.0)
            yaw = 0.0
            frame = "room"

        views = [(o, spatial.egocentric(o, origin, yaw)) for o in candidates]

        if kind in ("left", "right"):
            # RELATIVE, not a half-plane test. Two chairs at x = 0.2 and x = 1.5
            # are both strictly to the right of a robot at the origin, but a
            # person looking at them and saying "the one on the left" means the
            # nearer-to-left of the two, and a half-plane filter answers that
            # with "I don't see a chair on the left" — technically true and
            # useless. So among several candidates the side word RANKS them.
            ordered = sorted(views, key=lambda pair: pair[1]["right"],
                             reverse=kind == "right")

            if len(ordered) == 1:
                # With nothing to be leftmost OF, the word is a claim about
                # where the object actually is, and it can simply be wrong.
                obj, view = ordered[0]
                return ([obj] if view["side"] == kind else []), frame, True

            lateral = [v["right"] for _, v in ordered]
            decisive = abs(lateral[1] - lateral[0]) >= RANK_MARGIN_M
            return [o for o, _ in ordered], frame, decisive

        if kind in ("nearest", "farthest"):
            ranked = sorted(views, key=lambda pair: pair[1]["distance"],
                            reverse=kind == "farthest")
            ordered = [o for o, _ in ranked]
            decisive = self._separated([v["distance"] for _, v in ranked])
            return ordered, frame, decisive

        if kind in ("front", "behind"):
            want = "front" if kind == "front" else "behind"
            kept = [o for o, v in views if v["depth"] == want]
            return kept, frame, False

        return candidates, frame, False

    @staticmethod
    def _separated(values: list[float]) -> bool:
        """Is the best value clearly the best, rather than a tie?"""
        if len(values) <= 1:
            return True
        ordered = sorted(values)
        return abs(ordered[1] - ordered[0]) >= RANK_MARGIN_M

    @staticmethod
    def _extreme_by(candidates: list[dict], key, largest: bool) -> list[dict]:
        ranked = sorted(candidates, key=key, reverse=largest)
        if len(ranked) > 1 and abs(key(ranked[0]) - key(ranked[1])) < 1e-6:
            return candidates          # a genuine tie is still ambiguous
        return [ranked[0]]

    def _nothing_of_that_class(self, objects: list[dict],
                               query: TargetQuery) -> str:
        noun = (query.object_class or "object").replace("_", " ")
        labels = sorted({o["label"].replace("_", " ") for o in objects})
        if not labels:
            return f"I haven't scanned this room yet, so I can't find a {noun}."
        return (f"I don't see a {noun} in here. I can see: "
                f"{', '.join(labels)}.")

    def _no_such_colour(self, candidates: list[dict], query: TargetQuery) -> str:
        noun = (query.object_class or "object").replace("_", " ")
        wanted = " or ".join(query.colors)
        seen = [(o.get("attributes") or {}).get("color", {}).get("value")
                for o in candidates]
        seen = sorted({s for s in seen if s and s != "unknown"})
        if not seen:
            return (f"I don't know what colour the {noun}s are — nothing "
                    f"measured a colour for them.")
        return (f"None of the {len(candidates)} {noun}s look {wanted} to me. "
                f"I see {', '.join(seen)}.")

    def _no_such_relation(self, query: TargetQuery, constraint) -> str:
        noun = (query.object_class or "object").replace("_", " ")
        return (f"I can't find a {noun} {constraint.describe()}.")

    def _take_pending(self, room_id: str) -> _Pending | None:
        pending = self._pending.get(room_id)
        if pending is None:
            return None
        if time.monotonic() - pending.at > PENDING_TTL_S:
            self._pending.pop(room_id, None)
            return None
        return pending

    @staticmethod
    def _is_reply_to(query: TargetQuery, pending: _Pending) -> bool:
        """Is this message answering the question, or starting a new one?

        A reply narrows: it adds a discriminator and either names no class at
        all ("the red one") or names the same class again ("the red chair").
        Naming a different class is a new command and the old question is
        dropped — otherwise "actually, go to the sofa" would be answered with a
        chair.
        """
        if query.discriminators == 0:
            return False
        if query.object_class is None:
            return True
        return bool(pending.query.object_class
                    and class_matches(query.object_class,
                                      pending.query.object_class))


resolver_service = ResolverService()
