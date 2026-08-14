"""Targeted navigation: resolve a described object, then get to it safely.

The resolver decides WHICH object; these tests are about everything after that.
Two properties matter and neither is visible from a status code:

  * ARIA stops a real gap from the object's SURFACE, not from its centre. The
    centre of a 1.9 m sofa is a metre inside the sofa, so any check expressed
    in centre distance passes for paths that drive through the arm rest.
  * the route never crosses an obstacle, because the whole point of planning
    around the scene graph is that the twin agrees with the room.
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from app.core import spatial
from app.core.enrich import enrich_graph
from app.core.geometry import point_in_obb_xz
from app.services.planner_service import (
    APPROACH_RING_SAMPLES,
    approach_distance,
    planner_service,
)
from app.services.robot_service import RobotService
from app.services.safety_service import safety_service

ROOT = pathlib.Path(__file__).resolve().parents[2]
MULTI = enrich_graph(
    json.loads((ROOT / "contracts" / "demo_room_multi.json").read_text(encoding="utf-8"))
)
DEMO = enrich_graph(
    json.loads((ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))
)

OBSTACLES = [o for o in MULTI["objects"] if o.get("is_obstacle", True)]


def gap_to(point, obj) -> float:
    """Surface gap from a world XZ point to an object's footprint."""
    probe = {"position": [point[0], 0.0, point[1]],
             "dimensions": [1e-3, 1e-3, 1e-3], "rotation_y": 0.0}
    return spatial.surface_gap(probe, obj)


@pytest.fixture
def robot() -> RobotService:
    safety_service.clear_estop()
    r = RobotService()
    r.state["capabilities"] = ["navigate", "look_at", "point_at", "present", "dock"]
    r.state["online"] = True
    r.set_scene_graph(MULTI)
    return r


# ── stopping distance ──

@pytest.mark.parametrize("oid", [o["id"] for o in OBSTACLES])
def test_stops_a_safe_gap_from_every_object(oid) -> None:
    obj = next(o for o in MULTI["objects"] if o["id"] == oid)
    point, path = planner_service.approach_point(MULTI, obj, (-2.9, -2.1))

    want = approach_distance()
    assert gap_to(point, obj) >= want - 0.02, (
        f"stopped {gap_to(point, obj):.2f} m from {oid}, wanted {want:.2f} m")
    assert path, f"no route to {oid}"


def test_the_stand_off_is_derived_from_the_robot_not_hardcoded() -> None:
    """Widen the robot or the geofence and the stop distance must follow."""
    assert approach_distance("aria", 0.15) == pytest.approx(0.51, abs=1e-9)
    assert approach_distance("aria", 0.40) > approach_distance("aria", 0.15)


def test_the_stand_off_lands_in_the_specified_band() -> None:
    """0.4-0.7 m from the surface: close enough to be 'at' the thing, far
    enough that her arms clear it."""
    assert 0.40 <= approach_distance() <= 0.70


def test_approach_candidates_ring_the_whole_footprint() -> None:
    sofa = next(o for o in MULTI["objects"] if o["id"] == "sofa_01")
    ring = planner_service.approach_candidates(sofa)
    assert len(ring) == APPROACH_RING_SAMPLES
    # every candidate is at least the stand-off from the object...
    assert all(gap_to(c, sofa) >= approach_distance() - 0.02 for c in ring)
    # ...and they surround it rather than clustering on one side
    cx, _, cz = sofa["position"]
    angles = {round(math.atan2(c[0] - cx, c[1] - cz) / (math.pi / 2)) % 4
              for c in ring}
    assert angles == {0, 1, 2, 3}


def test_a_stand_off_point_is_never_inside_another_object() -> None:
    """Stopping 0.51 m from the chair is no good if that spot is inside the
    table — the navmesh check is what keeps the two consistent."""
    for obj in OBSTACLES:
        point, _ = planner_service.approach_point(MULTI, obj, (-2.9, -2.1))
        for other in OBSTACLES:
            assert not point_in_obb_xz(
                point, tuple(other["position"]), tuple(other["dimensions"]),
                float(other.get("rotation_y", 0.0))
            ), f"approach point for {obj['id']} lies inside {other['id']}"


# ── obstacle avoidance ──

def _samples(path, step=0.04):
    """Dense samples along a polyline, so a straight leg through a table is
    caught rather than only its endpoints being checked."""
    for a, b in zip(path, path[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        for i in range(max(int(length / step), 1) + 1):
            t = min(1.0, i * step / length) if length else 0.0
            yield (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


@pytest.mark.parametrize("oid", [o["id"] for o in OBSTACLES])
def test_the_route_never_crosses_furniture(oid) -> None:
    obj = next(o for o in MULTI["objects"] if o["id"] == oid)
    _, path = planner_service.approach_point(MULTI, obj, (-2.9, -2.1))

    for point in _samples(path):
        for other in OBSTACLES:
            if other["id"] == oid:
                continue
            assert not point_in_obb_xz(
                point, tuple(other["position"]), tuple(other["dimensions"]),
                float(other.get("rotation_y", 0.0))
            ), f"route to {oid} passes through {other['id']} at {point}"


async def test_navigate_to_a_described_object_end_to_end(robot) -> None:
    rec = await robot.enqueue({"action": "navigate", "target": "chair_02"})
    assert rec["status"] == "dispatched"
    assert rec["path"], "no path planned"

    chair = next(o for o in MULTI["objects"] if o["id"] == "chair_02")
    end = tuple(rec["path"][-1])
    assert gap_to(end, chair) >= approach_distance() - 0.05


async def test_an_unreachable_target_is_rejected_not_faked(robot) -> None:
    rec = await robot.enqueue({"action": "navigate", "target": "nothing_99"})
    assert rec["status"] == "rejected"
    assert "nothing_99" in rec["reason"]


# ── the old fixture still works ──

def test_the_original_demo_room_still_plans(robot) -> None:
    """The approach rewrite must not have been tuned to one room."""
    for obj in DEMO["objects"]:
        if not obj.get("is_obstacle", True):
            continue
        point, path = planner_service.approach_point(DEMO, obj, (0.0, 0.0))
        assert path, f"no route to {obj['id']} in the original demo room"
        assert gap_to(point, obj) >= approach_distance() - 0.05
