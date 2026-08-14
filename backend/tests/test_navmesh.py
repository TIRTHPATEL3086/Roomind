"""Navmesh + A* tests (spec 14.2). Pure logic - no DB, no MQTT, no network."""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from app.core.navmesh import (
    ROBOT_RADIUS,
    astar,
    build_grid,
    path_length,
    plan,
    smooth,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = json.loads((ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))


def empty_room(half: float = 3.0) -> dict:
    return {
        "room_id": "empty",
        "version": "1.0",
        "units": "meters",
        "bounds": {"min": [-half, 0.0, -half], "max": [half, 2.5, half]},
        "floor_y": 0.0,
        "robot_dock": [0.0, 0.0, 0.0],
        "objects": [],
    }


def room_with_wall() -> dict:
    """A wall across the middle with a gap on the +X side, forcing a detour."""
    r = empty_room()
    r["objects"] = [
        {
            "id": "wall_01", "label": "wall",
            "position": [-1.0, 0.5, 0.0],       # spans x in [-3, 1]
            "dimensions": [4.0, 1.0, 0.2],
            "rotation_y": 0.0, "is_obstacle": True,
        }
    ]
    return r


# ── grid construction ──

def test_grid_dimensions_match_bounds() -> None:
    g = build_grid(empty_room(3.0), resolution=0.05)
    assert g.width == 120 and g.height == 120
    assert g.origin == (-3.0, -3.0)


def test_perimeter_is_sealed() -> None:
    """A path must never be able to leave the scanned volume."""
    g = build_grid(empty_room(), resolution=0.05)
    assert not g.is_free(0, 0)
    assert not g.is_free(g.width - 1, g.height - 1)
    assert g.is_free(g.width // 2, g.height // 2)


def test_cell_world_roundtrip() -> None:
    g = build_grid(empty_room(), resolution=0.05)
    for cx, cz in ((10, 10), (50, 73), (119, 0)):
        wx, wz = g.cell_to_world(cx, cz)
        assert g.world_to_cell(wx, wz) == (cx, cz)


def test_non_obstacles_do_not_block() -> None:
    """The rug is is_obstacle=false - ARIA drives straight over it."""
    r = empty_room()
    r["objects"] = [{
        "id": "rug_01", "label": "rug", "position": [0.0, 0.005, 0.0],
        "dimensions": [2.0, 0.01, 2.0], "rotation_y": 0.0, "is_obstacle": False,
    }]
    g = build_grid(r, resolution=0.05)
    assert g.is_free(*g.world_to_cell(0.0, 0.0))


def test_obstacle_is_inflated_by_radius_plus_margin() -> None:
    """A cell just outside the box but inside the inflation ring must be blocked,
    or ARIA clips furniture with her shoulder."""
    r = empty_room()
    r["objects"] = [{
        "id": "box_01", "label": "box", "position": [0.0, 0.25, 0.0],
        "dimensions": [0.5, 0.5, 0.5], "rotation_y": 0.0, "is_obstacle": True,
    }]
    margin = 0.15
    g = build_grid(r, resolution=0.05, geofence_margin_m=margin)
    inflate = ROBOT_RADIUS["aria"] + margin          # 0.31 m

    just_outside_box = 0.25 + 0.02                    # inside the inflation ring
    assert not g.is_free(*g.world_to_cell(just_outside_box, 0.0))

    clear_of_ring = 0.25 + inflate + 0.10
    assert g.is_free(*g.world_to_cell(clear_of_ring, 0.0))


def test_rotated_obstacle_blocks_along_its_own_axis() -> None:
    """A 45-degree rotated box must block its rotated footprint, not its AABB."""
    r = empty_room()
    r["objects"] = [{
        "id": "板_01".replace("板", "panel"), "label": "panel",
        "position": [0.0, 0.5, 0.0], "dimensions": [2.0, 1.0, 0.2],
        "rotation_y": math.pi / 4, "is_obstacle": True,
    }]
    g = build_grid(r, resolution=0.05)
    # along the rotated long axis -> blocked
    d = 0.6
    assert not g.is_free(*g.world_to_cell(d * math.cos(math.pi / 4), -d * math.sin(math.pi / 4)))
    # perpendicular, well clear -> free
    assert g.is_free(*g.world_to_cell(-1.4, -1.4))


# ── A* ──

def test_straight_line_in_empty_room() -> None:
    p = plan(empty_room(), (-2.0, 0.0), (2.0, 0.0))
    assert p, "no path found in an empty room"
    assert path_length(p) == pytest.approx(4.0, abs=0.35)
    assert len(p) <= 3, f"empty-room path should smooth to a straight line, got {len(p)}"


def test_path_detours_around_a_wall() -> None:
    r = room_with_wall()
    p = plan(r, (-2.0, -2.0), (-2.0, 2.0))
    assert p, "no path found around the wall"
    # the direct route is 4 m; going round the +X gap must be materially longer
    assert path_length(p) > 5.0


def test_path_never_enters_a_blocked_cell() -> None:
    r = room_with_wall()
    g = build_grid(r)
    p = plan(r, (-2.0, -2.0), (-2.0, 2.0))
    assert p
    for wx, wz in p:
        assert g.is_free(*g.world_to_cell(wx, wz)), f"waypoint {wx, wz} is inside an obstacle"


def sealed_chamber_room() -> dict:
    """A walled chamber big enough that ARIA would fit inside - but with no door.

    The chamber must be genuinely larger than the robot after inflation, otherwise
    nearest_free() legitimately snaps the goal to the outside wall and a path IS
    found (see test_goal_inside_an_object_snaps_to_its_edge for that behaviour).
    """
    r = empty_room(4.5)
    r["objects"] = [
        {"id": "w_01", "label": "w", "position": [1.5, 0.5, 0.0],
         "dimensions": [0.2, 1.0, 3.2], "rotation_y": 0.0, "is_obstacle": True},
        {"id": "w_02", "label": "w", "position": [3.5, 0.5, 0.0],
         "dimensions": [0.2, 1.0, 3.2], "rotation_y": 0.0, "is_obstacle": True},
        {"id": "w_03", "label": "w", "position": [2.5, 0.5, 1.5],
         "dimensions": [2.2, 1.0, 0.2], "rotation_y": 0.0, "is_obstacle": True},
        {"id": "w_04", "label": "w", "position": [2.5, 0.5, -1.5],
         "dimensions": [2.2, 1.0, 0.2], "rotation_y": 0.0, "is_obstacle": True},
    ]
    return r


def test_sealed_chamber_interior_is_actually_free() -> None:
    """Guards the test below: if inflation swallowed the whole chamber, the
    unreachability test would pass for the wrong reason."""
    g = build_grid(sealed_chamber_room())
    assert g.is_free(*g.world_to_cell(2.5, 0.0))


def test_unreachable_goal_returns_empty() -> None:
    """A free cell with no route to it must yield [] - never a partial path.
    A partial path would drive ARIA into a wall and report success."""
    assert plan(sealed_chamber_room(), (-2.0, 0.0), (2.5, 0.0)) == []


def test_goal_inside_an_object_snaps_to_its_edge() -> None:
    """Navigating to 'table_01' targets the table CENTRE, which is inside the
    obstacle. The planner must snap to a reachable cell rather than fail."""
    table = next(o for o in DEMO["objects"] if o["id"] == "table_01")
    gx, _, gz = table["position"]
    p = plan(DEMO, (0.0, 0.0), (gx, gz))
    assert p, "planner failed on a goal inside an obstacle"
    end = p[-1]
    assert math.hypot(end[0] - gx, end[1] - gz) < 1.0


# ── smoothing ──

def test_smoothing_shortens_the_path() -> None:
    r = room_with_wall()
    g = build_grid(r)
    raw = astar(g, (-2.0, -2.0), (-2.0, 2.0))
    assert raw
    sm = smooth(g, raw)
    assert len(sm) < len(raw)
    assert path_length(sm) <= path_length(raw) + 1e-6


def test_smoothing_preserves_endpoints() -> None:
    r = room_with_wall()
    g = build_grid(r)
    raw = astar(g, (-2.0, -2.0), (-2.0, 2.0))
    sm = smooth(g, raw)
    assert sm[0] == raw[0]
    assert sm[-1] == raw[-1]


def test_line_of_sight_refuses_diagonal_corner_squeeze() -> None:
    """Two diagonally touching obstacles leave no real gap. A naive Bresenham
    slips through and produces a path that clips both corners."""
    r = empty_room()
    r["objects"] = [
        {"id": "a_01", "label": "a", "position": [-0.4, 0.5, -0.4],
         "dimensions": [0.4, 1.0, 0.4], "rotation_y": 0.0, "is_obstacle": True},
        {"id": "b_01", "label": "b", "position": [0.4, 0.5, 0.4],
         "dimensions": [0.4, 1.0, 0.4], "rotation_y": 0.0, "is_obstacle": True},
    ]
    g = build_grid(r, resolution=0.05)
    a = g.world_to_cell(-1.2, 1.2)
    b = g.world_to_cell(1.2, -1.2)
    assert not g.line_of_sight(a, b)


# ── the real demo room ──

def test_demo_room_is_navigable() -> None:
    g = build_grid(DEMO)
    assert g.free_count > 0, "demo room has no free space - inflation is too aggressive"


def test_dock_to_every_object_is_reachable() -> None:
    """If ARIA can't path to an object, no chat command targeting it can ever work."""
    dock = (DEMO["robot_dock"][0], DEMO["robot_dock"][2])
    unreachable = []
    for obj in DEMO["objects"]:
        if not obj.get("is_obstacle", True):
            continue
        gx, _, gz = obj["position"]
        if not plan(DEMO, dock, (gx, gz)):
            unreachable.append(obj["id"])
    assert not unreachable, f"unreachable from the dock: {unreachable}"
