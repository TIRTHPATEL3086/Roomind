"""Seed the DB (+ ChromaDB later) with the fixture room, so the whole stack is
demoable before any scanning or hardware exists.

    py -3.11 scripts/seed_demo_room.py

Validates the fixture against contracts/scene_graph.schema.json BEFORE inserting -
a malformed scene graph in the DB poisons every downstream consumer.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import jsonschema  # noqa: E402

from app.db.models import Robot, Room, SceneObject, Waypoint  # noqa: E402
from app.db.session import async_session  # noqa: E402

GRAPH = json.loads((ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))
SCHEMA = json.loads(
    (ROOT / "contracts" / "scene_graph.schema.json").read_text(encoding="utf-8")
)

# Exactly one robot. Change display_name here + ROBOT_DISPLAY_NAME in .env to rename it.
ROBOTS = [
    dict(
        id="aria",
        kind="humanoid",
        display_name="ARIA",
        accent_color="#3B82F6",
        persona="aria",
        emotion="neutral",
        state="idle",
        online=False,
        battery=1.0,
        pose={"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0},
        joints={
            "head_pan": 0, "head_tilt": 0, "waist_yaw": 0,
            "l_shoulder_pitch": 0, "l_shoulder_roll": 5, "l_elbow": 15,
            "r_shoulder_pitch": 0, "r_shoulder_roll": 5, "r_elbow": 15,
        },
        capabilities=[
            "navigate", "come_here", "stop", "follow_me", "dock", "turn", "set_speed",
            "look_at", "point_at", "wave", "nod", "shake_head", "gesture", "express",
            "dance", "scan_area", "remember_spot", "locate", "photo",
            "report_battery", "present", "imagine",
        ],
    ),
]

OBJECT_FIELDS = (
    "id", "label", "position", "dimensions", "rotation_y", "color", "confidence",
    "is_obstacle", "is_climbable", "surface_height", "source", "scale_confidence",
)


async def main() -> int:
    jsonschema.validate(GRAPH, SCHEMA)
    print(f"fixture validates against scene_graph.schema.json ({len(GRAPH['objects'])} objects)")

    async with async_session() as db:
        await db.merge(
            Room(
                id=GRAPH["room_id"],
                name=GRAPH.get("name", "Untitled Room"),
                mesh_path=GRAPH.get("mesh", {}).get("url"),
                navmesh_path=GRAPH.get("navmesh", {}).get("url"),
                bounds=GRAPH["bounds"],
                floor_y=GRAPH["floor_y"],
                robot_dock=GRAPH["robot_dock"],
                scene_graph=GRAPH,
            )
        )
        for o in GRAPH["objects"]:
            await db.merge(
                SceneObject(
                    room_id=GRAPH["room_id"],
                    **{k: o[k] for k in OBJECT_FIELDS if k in o},
                )
            )
        for w in GRAPH.get("waypoints", []):
            await db.merge(
                Waypoint(
                    id=f"{GRAPH['room_id']}__{w['name']}",
                    room_id=GRAPH["room_id"],
                    name=w["name"],
                    position=w["position"],
                )
            )
        for r in ROBOTS:
            await db.merge(Robot(**r))
        await db.commit()

    print(
        f"Seeded {GRAPH['room_id']}: {len(GRAPH['objects'])} objects, "
        f"{len(GRAPH.get('waypoints', []))} waypoints, ARIA registered."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
