"""Scene registry (Orchestration layer).

Holds the active scene graph in memory. Seeded from contracts/demo_room.json at
startup, replaced by the DB copy when one exists, and updated by the Twin
Generator (Phase 5) and Imagine Manager (Phase 3b).

Why an in-memory fallback: the planner, the companion and the frontend all need a
scene graph, but none of them need *persistence* to work. Requiring Postgres just
to render a room would mean the whole demo dies if the DB hiccups, and it would
have blocked all of Phase 2 behind a database password.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.enrich import enrich_graph, enrich_object
from app.core.errors import NotFound
from app.core.events import bus

log = logging.getLogger("roommind.scene")

CONTRACTS = Path(__file__).resolve().parents[2].parent / "contracts"
FIXTURE = CONTRACTS / "demo_room.json"

# Every checked-in room, primary one first. `demo_room_multi.json` is not
# hand-written: it is the literal output of reconstruction/pipeline.py over the
# rendered multi-instance capture, mesh URL rewritten to point at the API. It
# ships because the feature it exercises - several objects of the same class,
# told apart by colour and by what they stand next to - cannot be demonstrated
# in a room that has one of everything, and re-running the reconstruction to
# see it would cost 27 seconds and a 1.5 GB venv.
EXTRA_FIXTURES = ("demo_room_multi.json",)


class SceneService:
    def __init__(self) -> None:
        self._graphs: dict[str, dict] = {}

    def load_fixture(self) -> dict | None:
        if not FIXTURE.exists():
            log.warning("no fixture at %s", FIXTURE)
            return None
        graph = enrich_graph(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self._graphs[graph["room_id"]] = graph
        log.info("scene '%s' loaded from fixture (%d objects)",
                 graph["room_id"], len(graph["objects"]))

        # Secondary rooms load too, so /rooms can offer them and the resolver
        # can be pointed at one without a rescan. A missing extra fixture is
        # not an error - the primary room is what the app needs to start.
        for name in EXTRA_FIXTURES:
            path = CONTRACTS / name
            if not path.exists():
                continue
            try:
                extra = enrich_graph(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("skipping fixture %s: %r", name, e)
                continue
            self._graphs[extra["room_id"]] = extra
            log.info("scene '%s' loaded from fixture (%d objects)",
                     extra["room_id"], len(extra["objects"]))

        return graph

    def get(self, room_id: str) -> dict:
        graph = self._graphs.get(room_id)
        if graph is None:
            raise NotFound(f"room '{room_id}' not found")
        return graph

    def get_default(self) -> dict | None:
        return next(iter(self._graphs.values()), None)

    def list_rooms(self) -> list[dict]:
        return [
            {
                "id": g["room_id"],
                "name": g.get("name", "Untitled Room"),
                "created_at": g.get("created_at"),
                "object_count": len(g.get("objects", [])),
            }
            for g in self._graphs.values()
        ]

    def find_object(self, room_id: str, object_id: str) -> dict | None:
        for o in self.get(room_id).get("objects", []):
            if o["id"] == object_id:
                return o
        return None

    async def put(self, graph: dict) -> None:
        """Install a scene graph and tell everyone. Used by the Twin Generator
        and, on commit, by the Imagine Manager.

        Enriched on the way in, so every graph in memory carries colour names,
        size classes and the relation layer whatever produced it. The resolver
        then has exactly one shape to read: a hand-written fixture and a freshly
        reconstructed room answer "the red chair near the table" identically,
        and no caller has to remember to prepare a graph first.
        """
        enrich_graph(graph)
        self._graphs[graph["room_id"]] = graph
        await bus.publish("scene.updated", graph)

    async def add_object(self, room_id: str, obj: dict) -> dict:
        """Insert a single object (Imagine commit path, Phase 3b)."""
        graph = self.get(room_id)
        graph.setdefault("objects", []).append(enrich_object(obj, "generated"))
        # A new object changes what every OTHER object is near, so the relation
        # layer is rebuilt rather than appended to.
        enrich_graph(graph)
        await bus.publish("scene.updated", graph)
        return obj

    def next_object_id(self, room_id: str, label: str) -> str:
        """Allocate the next `{label}_{NN}` id (spec 8.2).

        Generated objects follow the identical rule as detected ones - downstream
        consumers must not be able to tell them apart.
        """
        snake = "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")
        existing = {o["id"] for o in self.get(room_id).get("objects", [])}
        for i in range(1, 100):
            candidate = f"{snake}_{i:02d}"
            if candidate not in existing:
                return candidate
        raise ValueError(f"more than 99 '{snake}' objects in {room_id}")


scene_service = SceneService()
