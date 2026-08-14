"""The word -> scene-graph-label vocabulary, in one place.

Users say "couch", the detector says "sofa"; users say "telly", COCO says "tv".
Every part of the system that reads a user's noun needs the same mapping —
retrieval, the offline intent parser, and now the target resolver — and the
moment two of them disagree, a query that counts three chairs resolves against
a different set than the one it counted.

This lives in `core/` rather than in `rag_service` because it is data, not a
service: `core/` may not import from `services/` (spec 1.4.2), and the resolver
is a core-level concern that must not drag retrieval in behind it.
"""
from __future__ import annotations

# Everyday words -> scene-graph labels.
SYNONYMS: dict[str, str] = {
    "couch": "sofa", "settee": "sofa", "sofas": "sofa", "couches": "sofa",
    "seat": "chair", "seats": "chair", "chairs": "chair", "armchair": "chair",
    "stools": "stool",
    "tables": "table", "desk": "table", "desks": "table",
    "lamps": "lamp", "light": "lamp", "lights": "lamp", "lighting": "lamp",
    "plant": "potted_plant", "plants": "potted_plant", "pot": "potted_plant",
    "pots": "potted_plant",
    "television": "tv", "televisions": "tv", "telly": "tv", "screen": "tv",
    "screens": "tv", "monitor": "tv", "tvs": "tv",
    "bookshelf": "shelf", "shelves": "shelf", "bookcase": "shelf",
    "shelfs": "shelf", "cabinet": "shelf", "cupboard": "shelf",
    "carpet": "rug", "mat": "rug", "rugs": "rug",
    "beds": "bed", "mattress": "bed",
    "benches": "bench", "fridge": "fridge", "refrigerator": "fridge",
}

# Multi-word phrases, longest first. Checked before single words so "dining
# table" and "coffee table" resolve as tables rather than leaving "dining" to
# be mistaken for a class of its own.
PHRASES: tuple[tuple[str, str], ...] = (
    ("potted plant", "potted_plant"),
    ("dining table", "table"),
    ("coffee table", "table"),
    ("side table", "table"),
    ("floor lamp", "lamp"),
    ("table lamp", "lamp"),
    ("book shelf", "shelf"),
    ("book case", "shelf"),
    ("tv stand", "shelf"),
    ("night stand", "table"),
)


def canonical_label(word: str) -> str:
    """A user's noun -> the scene-graph label it most likely means.

    Falls through unchanged when there is no mapping: an unknown noun is not an
    error here, it is simply a class this room may or may not contain, and the
    caller decides what to do about that.
    """
    w = (word or "").strip().lower().replace(" ", "_")
    return SYNONYMS.get(w, w)


def class_matches(object_label: str, wanted: str) -> bool:
    """Does an object of `object_label` satisfy a query for class `wanted`?

    Head-noun matching, one-directional, exactly as `rag_service.by_label` does
    it: a query for "chair" is answered by a "wooden_chair", because a wooden
    chair IS a chair. The reverse is not true — asking for a "wooden chair"
    must not hand back a plain one, or a user who took the trouble to be
    specific gets the object they ruled out.
    """
    got = (object_label or "").strip().lower()
    want = canonical_label(wanted)
    if not got or not want:
        return False
    if got == want or canonical_label(got) == want:
        return True
    # head noun of a compound label: wooden_chair -> chair
    head = got.rsplit("_", 1)[-1]
    return head == want or canonical_label(head) == want
