"""Natural language -> a structured target query. No scene, no I/O, no model.

This is step B of the command pipeline: intent detection has already decided
the user wants to GO somewhere, and this decides what they want to go *to* —
as a set of constraints, not as an answer. Turning those constraints into one
physical object is the resolver's job, against the actual scene graph.

Splitting it this way is the whole point of the design. Parsing is a language
problem with fuzzy edges; selecting a physical object is a filtering problem
with exact answers. Keeping them apart means the selection step can be tested
without any language at all, and the language step can be tested without a
room — and neither one can quietly become "ask a model and hope".

Deliberately rule-based. A regex that fails to parse "the reddish chair"
returns no colour constraint and the resolver asks which chair; a model that
guesses "red" sends the robot across the room. Under-parsing degrades into a
question, which is the failure mode this feature is supposed to have.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.colors import canonical as canonical_color
from app.core.vocabulary import PHRASES, canonical_label

# A literal scene-graph id the user (or the UI) typed verbatim.
ID_RE = re.compile(r"\b([a-z_]+_[0-9]{2})\b")

# "chair number 3", "chair no. 3", "chair #3", "chair 3"
NUMBERED_RE = re.compile(
    r"\b([a-z_]+(?:\s+[a-z]+)?)\s*(?:number|no\.?|#)\s*([0-9]{1,2})\b")
BARE_NUMBER_RE = re.compile(r"\b([a-z_]+)\s+([0-9]{1,2})\b")
# "number 3" on its own — a reply to a clarification question.
LONE_NUMBER_RE = re.compile(r"^(?:the\s+)?(?:number|no\.?|#)\s*([0-9]{1,2})$")

ORDINAL_WORDS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
}

SIZE_WORDS = {
    "large": "large", "big": "large", "biggest": "large", "largest": "large",
    "huge": "large", "tall": "large", "tallest": "large",
    "small": "small", "little": "small", "smallest": "small", "tiny": "small",
    "short": "small", "shortest": "small",
}

# Phrases that pick one candidate out of several by where it is, relative to
# whoever is looking. Ordered longest-first so "on the far left" does not match
# the bare "far" rule first.
EGOCENTRIC_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:on|to|at)\s+(?:the\s+|my\s+|your\s+)?far\s+left\b", "left"),
    (r"\b(?:on|to|at)\s+(?:the\s+|my\s+|your\s+)?far\s+right\b", "right"),
    (r"\bleft\s*most\b", "left"),
    (r"\bright\s*most\b", "right"),
    (r"\b(?:on|to|at)\s+(?:the\s+|my\s+|your\s+)?left\b", "left"),
    (r"\b(?:on|to|at)\s+(?:the\s+|my\s+|your\s+)?right\b", "right"),
    (r"\bnearest\b|\bclosest\b|\bnear(?:est)?\s+one\b", "nearest"),
    (r"\bfurthest\b|\bfarthest\b|\bfar(?:thest)?\s+one\b", "farthest"),
    (r"\bin\s+front\s+of\s+(?:you|me)\b|\bahead\s+of\s+(?:you|me)\b", "front"),
    (r"\bbehind\s+(?:you|me)\b", "behind"),
)

# Relation phrases: (regex, canonical relation). The captured group is the
# other object's noun. Longest / most specific first — "to the left of the
# table" is a relation between two objects and must not be read as the
# egocentric "on the left".
RELATION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:to\s+the\s+)?left\s+of\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "left_of"),
    (r"\b(?:to\s+the\s+)?right\s+of\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "right_of"),
    (r"\bin\s+front\s+of\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "in_front_of"),
    (r"\bbehind\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "behind"),
    (r"\bnext\s+to\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "next_to"),
    (r"\bbeside\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "beside"),
    (r"\bnear(?:est)?\s+(?:to\s+)?(?:the\s+|a\s+|an\s+|my\s+)([a-z_ ]+)", "near"),
    (r"\bclose\s+to\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "near"),
    (r"\bby\s+the\s+([a-z_ ]+)", "near"),
    (r"\bon\s+top\s+of\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "on"),
    (r"\bunder(?:neath)?\s+(?:the\s+|a\s+|an\s+|my\s+)?([a-z_ ]+)", "under"),
)

# Words that can never be the object the user means. Without this, "go to the
# one near the table" resolves a class called "one".
NOT_A_CLASS = {
    "the", "a", "an", "one", "it", "that", "this", "there", "here", "me",
    "you", "your", "my", "please", "go", "to", "move", "walk", "drive",
    "navigate", "head", "over", "near", "next", "beside", "close", "by",
    "left", "right", "front", "behind", "back", "side", "of", "and", "or",
    "with", "in", "on", "at", "for", "aria", "robot", "room", "number", "no",
    "thing", "object", "stuff", "towards", "toward", "up", "down", "then",
    "under", "underneath", "second", "first", "third", "far", "nearest",
    "closest", "furthest", "farthest", "leftmost", "rightmost", "is", "are",
    "climb", "climbed", "climbing", "jump", "jumped", "sit", "sat", "sitting",
}

# Trailing words the class noun regex may pick up but that are never part of
# the noun itself.
_TRAILING_JUNK = re.compile(
    r"\b(please|now|instead|first|then|and|but|so|thanks|thank you)\b.*$")

# A pronoun standing in for a class named earlier — the signature of an answer
# to a clarification question rather than a fresh command.
PRO_FORM_RE = re.compile(r"\b(one|ones|it|that one|this one|them)\b")


@dataclass
class RelationConstraint:
    """'... near the table' — a relation to another object, by class or by id."""

    rel: str
    other_class: str | None = None
    other_id: str | None = None

    def describe(self) -> str:
        target = self.other_id or (self.other_class or "").replace("_", " ")
        return f"{self.rel.replace('_', ' ')} the {target}"


@dataclass
class TargetQuery:
    """Everything the user said about WHICH object, and nothing about what to do."""

    raw: str = ""
    object_class: str | None = None
    explicit_id: str | None = None
    colors: list[str] = field(default_factory=list)
    size: str | None = None
    ordinal: int | None = None
    relations: list[RelationConstraint] = field(default_factory=list)
    egocentric: str | None = None

    @property
    def discriminators(self) -> int:
        """How many things the user said to narrow the class down.

        Zero means "go to the chair" with nothing else — which is a question,
        not a command, the moment the room holds more than one chair.
        """
        return (len(self.colors) + len(self.relations)
                + (1 if self.size else 0)
                + (1 if self.ordinal else 0)
                + (1 if self.egocentric else 0)
                + (1 if self.explicit_id else 0))

    @property
    def is_bare(self) -> bool:
        return self.discriminators == 0

    def merged_with(self, older: TargetQuery) -> TargetQuery:
        """Fold this query onto an earlier one — how a clarification is answered.

        The user replies "the one near the table" and means "...of the chairs
        you just asked me about". The reply carries the new constraints; the
        original carries the class. Newer constraints win where both have one,
        because the reply is the user correcting themselves.
        """
        return TargetQuery(
            raw=f"{older.raw} | {self.raw}".strip(" |"),
            object_class=self.object_class or older.object_class,
            explicit_id=self.explicit_id or older.explicit_id,
            colors=self.colors or older.colors,
            size=self.size or older.size,
            ordinal=self.ordinal if self.ordinal is not None else older.ordinal,
            relations=self.relations or older.relations,
            egocentric=self.egocentric or older.egocentric,
        )

    def describe(self) -> str:
        """Human summary of the constraints, for reasons and log lines."""
        bits: list[str] = []
        if self.explicit_id:
            return self.explicit_id
        for c in self.colors:
            bits.append(c)
        if self.size:
            bits.append(self.size)
        bits.append((self.object_class or "object").replace("_", " "))
        if self.ordinal:
            bits.append(f"number {self.ordinal}")
        for r in self.relations:
            bits.append(r.describe())
        if self.egocentric:
            bits.append(f"({self.egocentric})")
        return " ".join(bits)


def _strip_relation_clauses(text: str) -> tuple[str, list[RelationConstraint]]:
    """Pull relation clauses out, and return the text with them removed.

    Removing them matters as much as capturing them: "the chair near the table"
    contains two nouns, and whichever survives into the class search decides
    what the user is understood to want. The relation clause names the
    LANDMARK, so it has to be taken out before the head noun is looked for, or
    "table" wins on position and ARIA drives to the table.
    """
    found: list[RelationConstraint] = []
    remaining = text
    for pattern, rel in RELATION_PATTERNS:
        spans: list[tuple[int, int]] = []
        for m in re.finditer(pattern, remaining):
            noun = _head_noun(m.group(1))
            if noun is None:
                # No landmark, so this was not a relation clause at all —
                # "on the left" matches the `on <noun>` shape but names a
                # direction, not an object. Leaving the span in place is what
                # lets the egocentric pass downstream still see it; blanking it
                # unconditionally is what made "the chair on the left" parse as
                # a bare "chair" with no side at all.
                continue
            found.append(RelationConstraint(rel=rel, other_class=noun))
            spans.append(m.span())
        for start, end in reversed(spans):
            remaining = remaining[:start] + " " + remaining[end:]
    # de-duplicate while keeping order
    seen: set[tuple[str, str | None]] = set()
    unique: list[RelationConstraint] = []
    for r in found:
        key = (r.rel, r.other_class)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return remaining, unique


def _head_noun(fragment: str) -> str | None:
    """Last meaningful noun in a fragment -> a canonical class label."""
    fragment = _TRAILING_JUNK.sub(" ", (fragment or "").lower())
    for phrase, label in PHRASES:
        if phrase in fragment:
            return label
    words = [w.strip("_") for w in re.findall(r"[a-z_]+", fragment)]
    words = [w for w in words if w and w not in NOT_A_CLASS]
    # Colour and size words describe the noun, they are not the noun. If
    # stripping them leaves nothing then the fragment never held a noun —
    # "the red one" is a pure modifier phrase, and returning "red" as if it
    # were a class of furniture invents a class the room can never contain.
    words = [w for w in words
             if canonical_color(w) is None and w not in SIZE_WORDS]
    if not words:
        return None
    return canonical_label(words[-1])


def parse_target(text: str) -> TargetQuery:
    """The whole of step B: a sentence -> the constraints it places on a target."""
    raw = (text or "").strip()
    lowered = raw.lower()
    q = TargetQuery(raw=raw)

    if m := ID_RE.search(lowered):
        q.explicit_id = m.group(1)

    # "chair number 3" / "chair #3". Checked before the relation clauses,
    # because the number is attached to the class noun, not to a landmark.
    if m := NUMBERED_RE.search(lowered):
        q.ordinal = int(m.group(2))
        q.object_class = _head_noun(m.group(1))
    elif m := LONE_NUMBER_RE.match(lowered):
        q.ordinal = int(m.group(1))
    else:
        for word, value in ORDINAL_WORDS.items():
            if re.search(rf"\b{word}\b", lowered):
                q.ordinal = value
                break

    body, relations = _strip_relation_clauses(lowered)
    q.relations = relations

    for pattern, kind in EGOCENTRIC_PATTERNS:
        if re.search(pattern, body):
            q.egocentric = kind
            break

    for word in re.findall(r"[a-z_-]+", body):
        if (named := canonical_color(word)) is not None and named not in q.colors:
            q.colors.append(named)
        if word in SIZE_WORDS and q.size is None:
            q.size = SIZE_WORDS[word]

    if q.object_class is None:
        # "go to chair 3" — a bare number directly after the noun, once the
        # relation clauses are gone so "table 2" in "near table 2" cannot win.
        if m := BARE_NUMBER_RE.search(body):
            noun = _head_noun(m.group(1))
            if noun is not None:
                q.object_class = noun
                q.ordinal = q.ordinal or int(m.group(2))
        else:
            q.object_class = _head_noun(_strip_verbs(body))

    # An id the user typed outranks anything inferred from the words around it.
    if q.explicit_id:
        q.object_class = q.explicit_id.rsplit("_", 1)[0]

    # "Go near the TV" names a TARGET, not a landmark: `near` is qualifying how
    # close to get, and there is no other noun for it to relate to. Promote it.
    #
    # Guarded on a pro-form, because "the one near the table" has exactly the
    # same shape and means the opposite — there the relation IS a landmark and
    # the class is whatever the pending question was about. Promoting it there
    # would answer "which chair?" with "the table".
    if q.object_class is None and q.relations and not PRO_FORM_RE.search(lowered):
        promoted = q.relations[0]
        q.object_class = promoted.other_class
        q.relations = q.relations[1:]
    return q


def _strip_verbs(text: str) -> str:
    """Drop the command verb so the head-noun search sees only the object."""
    return re.sub(
        r"^\s*(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
        r"(?:go|drive|move|walk|navigate|head|take me|come|show me|point|look|"
        r"turn|face|present|climb|get on|jump on|step onto|sit on|sit near|rest on)\b(?:\s+(?:to|at|over|towards?|me|on|onto))*",
        " ", text)
