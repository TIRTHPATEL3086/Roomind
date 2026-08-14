"""Retrieval over the scene graph (AI Services layer, spec 9.6).

Two backends behind one interface, same pattern as the on-device inference
factory (spec P8):

  ChromaBackend   - ChromaDB embedded (PersistentClient), semantic search.
  LexicalBackend  - pure Python token/synonym scoring. No deps, no downloads.

Why a lexical fallback rather than "just use Chroma": a room holds tens of
objects, not millions. Lexical matching genuinely suffices at that size, and it
means retrieval works with the network unplugged and with MOCK_LLM=true - which
spec rule 5 requires. Chroma's default embedder downloads a model on first use;
a demo that dies on a cold cache is worse than one that ranks with token overlap.
"""
from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod

from app.config import get_settings

log = logging.getLogger("roommind.rag")

# Words that carry no discriminative signal in a room query.
STOP = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "of",
    "my", "your", "how", "many", "much", "what", "where", "which", "there",
    "here", "do", "does", "did", "i", "you", "it", "this", "that", "and", "or",
    "me", "we", "can", "could", "would", "please", "tell", "show", "aria",
    "room", "any", "some", "get", "got", "have", "has", "be", "am", "s",
}

# Affordances: what a user wants to DO -> labels that afford it.
#
# This is the one thing pure token overlap cannot do. "Where can I sit down"
# shares no word with "sofa", so without this the query scores zero against
# every object. It is not a substitute for embeddings — it covers the handful
# of intents a room actually affords, which is enough at this scale.
AFFORDANCE: dict[str, tuple[str, ...]] = {
    "sit": ("chair", "sofa"), "sitting": ("chair", "sofa"),
    "rest": ("sofa", "chair"), "relax": ("sofa",), "lounge": ("sofa",),
    "eat": ("table",), "dine": ("table",), "dinner": ("table",),
    "work": ("table", "desk"), "write": ("table",),
    "read": ("lamp", "shelf", "sofa"), "reading": ("lamp", "shelf", "sofa"),
    "sleep": ("sofa", "bed"), "nap": ("sofa",),
    "watch": ("tv",), "tv": ("tv",),
    "store": ("shelf",), "storage": ("shelf",), "books": ("shelf",),
    "bright": ("lamp",), "dark": ("lamp",), "brighter": ("lamp",),
    "place": ("table", "shelf"), "put": ("table", "shelf"),
}

# Everyday words -> scene-graph labels. Users say "couch", the detector says "sofa".
SYNONYMS: dict[str, str] = {
    "couch": "sofa", "settee": "sofa", "seat": "chair", "seats": "chair",
    "chairs": "chair", "tables": "table", "desk": "table",
    "lamps": "lamp", "light": "lamp", "lights": "lamp",
    "plant": "potted_plant", "plants": "potted_plant", "pot": "potted_plant",
    "television": "tv", "telly": "tv", "screen": "tv",
    "bookshelf": "shelf", "shelves": "shelf", "bookcase": "shelf",
    "carpet": "rug", "mat": "rug",
}


def tokenize(text: str, expand: bool = False) -> list[str]:
    """Normalise text to scoring tokens.

    `expand=True` (queries only) also emits affordance labels, so "sit down"
    scores against chair and sofa. Documents are indexed WITHOUT expansion —
    expanding both sides would make every seat match every seating intent and
    flatten the ranking.
    """
    words = re.findall(r"[a-z0-9_]+", text.lower())
    out: list[str] = []
    for w in words:
        w = SYNONYMS.get(w, w)
        if w in STOP:
            continue
        out.append(w)
        # "potted_plant" should also match a bare "plant" query
        if "_" in w:
            out.extend(p for p in w.split("_") if p not in STOP)
        if expand:
            out.extend(AFFORDANCE.get(w, ()))
    return out


def describe(obj: dict) -> str:
    """One-line natural description of an object - the retrieval document."""
    w, h, d = obj["dimensions"]
    x, y, z = obj["position"]
    parts = [
        obj["label"].replace("_", " "),
        f"id {obj['id']}",
        f"{w:.2f} by {h:.2f} by {d:.2f} metres",
        f"at x {x:.2f} z {z:.2f}",
    ]
    if obj.get("surface_height"):
        parts.append(f"top surface at {obj['surface_height']:.2f} m")
    if obj.get("is_obstacle", True):
        parts.append("blocks the floor")
    if obj.get("source") == "generated":
        parts.append("created from an image")
    return ", ".join(parts)


class RagBackend(ABC):
    name: str

    @abstractmethod
    def index(self, room_id: str, objects: list[dict]) -> None: ...

    @abstractmethod
    def query(self, room_id: str, text: str, k: int) -> list[tuple[str, float]]:
        """Return [(object_id, score)] best first."""


class LexicalBackend(RagBackend):
    """Token-overlap scoring with IDF weighting. Deterministic, no I/O."""

    name = "lexical"

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, list[str]]] = {}

    def index(self, room_id: str, objects: list[dict]) -> None:
        self._docs[room_id] = {
            o["id"]: tokenize(f"{describe(o)} {o['id']}") for o in objects
        }

    def query(self, room_id: str, text: str, k: int) -> list[tuple[str, float]]:
        docs = self._docs.get(room_id, {})
        if not docs:
            return []
        q = tokenize(text, expand=True)
        if not q:
            return []

        n = len(docs)
        df: dict[str, int] = {}
        for toks in docs.values():
            for t in set(toks):
                df[t] = df.get(t, 0) + 1

        scored: list[tuple[str, float]] = []
        for oid, toks in docs.items():
            tokset = set(toks)
            score = 0.0
            for t in q:
                if t in tokset:
                    # rarer term -> higher weight
                    score += math.log(1 + n / (1 + df.get(t, 0)))
            if score > 0:
                scored.append((oid, score))
        scored.sort(key=lambda p: -p[1])
        return scored[:k]


class ChromaBackend(RagBackend):
    """ChromaDB embedded - no server process. Falls back if unavailable."""

    name = "chroma"

    def __init__(self, path: str) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=path)

    def _coll(self, room_id: str):
        return self._client.get_or_create_collection(f"room_{room_id}")

    def index(self, room_id: str, objects: list[dict]) -> None:
        c = self._coll(room_id)
        ids = [o["id"] for o in objects]
        if ids:
            c.upsert(
                ids=ids,
                documents=[describe(o) for o in objects],
                metadatas=[{"label": o["label"]} for o in objects],
            )

    def query(self, room_id: str, text: str, k: int) -> list[tuple[str, float]]:
        res = self._coll(room_id).query(query_texts=[text], n_results=k)
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        # distance -> similarity, so both backends sort the same way
        return [(i, 1.0 / (1.0 + d)) for i, d in zip(ids, dists, strict=False)]


class RagService:
    def __init__(self) -> None:
        self._backend: RagBackend | None = None
        self._objects: dict[str, dict[str, dict]] = {}

    @property
    def backend(self) -> RagBackend:
        if self._backend is None:
            self._backend = self._pick_backend()
        return self._backend

    def _pick_backend(self) -> RagBackend:
        """Pick a backend from RAG_BACKEND. Always logs the choice and the
        reason - a silent downgrade is how you end up debugging retrieval
        quality that was never the problem.

        LEXICAL IS THE DEFAULT, and that is a measured decision, not laziness.
        Chroma's default embedder downloads a 79 MB ONNX model on first index
        and blocked startup for 37 s on this machine - to rank nine objects.
        Lexical answers the same queries (see test_companion.py: synonyms,
        affordances, exact counting) in microseconds with no network. Set
        RAG_BACKEND=chroma once a room has hundreds of objects and semantic
        recall actually starts to matter.
        """
        s = get_settings()
        choice = (s.rag_backend or "lexical").lower()

        if choice == "lexical":
            log.info("rag backend: lexical (default; set RAG_BACKEND=chroma to change)")
            return LexicalBackend()

        try:
            b = ChromaBackend(f"{s.storage_root}/chroma")
            log.info("rag backend: chroma (embedded, %s/chroma) - first index may "
                     "download an ~79 MB embedding model", s.storage_root)
            return b
        except Exception as e:  # noqa: BLE001
            log.warning("rag backend: lexical (chroma requested but unavailable: %r)", e)
            return LexicalBackend()

    # ── public API ──

    def index_room(self, graph: dict) -> int:
        room_id = graph["room_id"]
        objects = graph.get("objects", [])
        self._objects[room_id] = {o["id"]: o for o in objects}
        try:
            self.backend.index(room_id, objects)
        except Exception as e:  # noqa: BLE001
            log.warning("index failed on %s, downgrading to lexical: %r",
                        self.backend.name, e)
            self._backend = LexicalBackend()
            self._backend.index(room_id, objects)
        return len(objects)

    def retrieve(self, room_id: str, text: str, k: int = 6) -> list[dict]:
        """Objects most relevant to `text`, best first."""
        by_id = self._objects.get(room_id, {})
        if not by_id:
            return []
        try:
            hits = self.backend.query(room_id, text, k)
        except Exception as e:  # noqa: BLE001
            log.warning("query failed on %s: %r", self.backend.name, e)
            hits = LexicalBackend().query(room_id, text, k)
        return [by_id[i] for i, _ in hits if i in by_id]

    def by_label(self, room_id: str, label: str) -> list[dict]:
        """Exact label match. Counting questions must never go through fuzzy
        retrieval - 'how many chairs' has an exact answer, and a similarity
        cutoff would silently drop the third chair.

        Users type spaces, labels use underscores. Without normalising here,
        "where's the floor lamp?" never matches label 'floor_lamp' and silently
        falls through to fuzzy retrieval - which happily returns a DIFFERENT
        lamp. Generated objects hit this constantly, since their labels come
        from a hint and are usually multi-word.
        """
        raw = label.lower().strip()
        wants = {
            SYNONYMS.get(raw, raw),
            raw.replace(" ", "_"),
            SYNONYMS.get(raw.replace(" ", "_"), raw.replace(" ", "_")),
            raw.replace("_", " "),
        }

        def matches(obj_label: str) -> bool:
            low = obj_label.lower()
            if low in wants or low.replace("_", " ") in wants:
                return True
            # Head-noun match, one-directional: a query for "chair" counts a
            # "wooden_chair", because a wooden chair IS a chair. The reverse is
            # NOT true — asking for a "wooden chair" must not return a plain
            # one. Generated labels come from free text ("a wooden chair"), so
            # without this a generated object silently stops being counted.
            head = low.rsplit("_", 1)[-1]
            return head in wants

        return [
            o for o in self._objects.get(room_id, {}).values()
            if matches(o["label"])
        ]

    def all_objects(self, room_id: str) -> list[dict]:
        return list(self._objects.get(room_id, {}).values())

    def exists(self, room_id: str, object_id: str) -> bool:
        return object_id in self._objects.get(room_id, {})


rag_service = RagService()
