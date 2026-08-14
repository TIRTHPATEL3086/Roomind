"""Placement solver tests (spec 10B.10).

The hard rule under test: a generated object never overlaps an existing one.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "genai3d"))

from steps.g09_place import (  # noqa: E402
    CLEARANCE_M,
    collides,
    in_bounds,
    solve,
)

DEMO = json.loads((ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))


def dist_xz(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


# ── collision ──

def test_placing_inside_the_table_collides() -> None:
    table = next(o for o in DEMO["objects"] if o["id"] == "table_01")
    assert collides(DEMO, table["position"], [0.3, 0.3, 0.3]) == "table_01"


def one_box_room() -> dict:
    """A room with exactly one obstacle, so a clearance assertion can't be
    confounded by some other object happening to sit nearby."""
    return {
        "room_id": "t", "version": "1.0", "units": "meters",
        "bounds": {"min": [-5.0, 0.0, -5.0], "max": [5.0, 2.5, 5.0]},
        "floor_y": 0.0, "robot_dock": [-4.0, 0.0, -4.0],
        "objects": [{
            "id": "box_01", "label": "box", "position": [0.0, 0.25, 0.0],
            "dimensions": [1.0, 0.5, 1.0], "rotation_y": 0.0, "is_obstacle": True,
        }],
    }


def test_clearance_margin_is_enforced() -> None:
    """Touching isn't good enough — a generated object must leave real space."""
    room = one_box_room()
    probe = [0.1, 0.3, 0.1]
    edge = 0.5 + probe[0] / 2          # box half-width + probe half-width

    inside_margin = (edge + CLEARANCE_M * 0.5, 0.15, 0.0)
    assert collides(room, inside_margin, probe) == "box_01"

    outside_margin = (edge + CLEARANCE_M + 0.05, 0.15, 0.0)
    assert collides(room, outside_margin, probe) is None


def test_non_obstacles_do_not_collide() -> None:
    """The rug is is_obstacle=false — you can put a lamp on a rug."""
    rug = next(o for o in DEMO["objects"] if o["id"] == "rug_01")
    hit = collides(DEMO, rug["position"], [0.2, 0.2, 0.2])
    assert hit != "rug_01"


def test_ignore_set_is_respected() -> None:
    table = next(o for o in DEMO["objects"] if o["id"] == "table_01")
    assert collides(DEMO, table["position"], [0.2, 0.2, 0.2],
                    ignore={"table_01"}) != "table_01"


def test_bounds_check_rejects_outside_the_room() -> None:
    assert not in_bounds(DEMO, (99.0, 0.5, 0.0), [0.4, 1.0, 0.4])
    assert in_bounds(DEMO, (0.0, 0.5, 0.0), [0.4, 1.0, 0.4])


def test_bounds_account_for_the_object_footprint() -> None:
    """A 2 m object centred 0.5 m from the wall is half outside the room."""
    max_x = DEMO["bounds"]["max"][0]
    assert not in_bounds(DEMO, (max_x - 0.5, 0.5, 0.0), [2.0, 1.0, 0.4])


# ── the solver ──

def test_floor_placement_never_overlaps_anything() -> None:
    p = solve(DEMO, [0.35, 1.55, 0.35], placement="floor")
    assert collides(DEMO, p.position, [0.35, 1.55, 0.35]) is None
    assert in_bounds(DEMO, p.position, [0.35, 1.55, 0.35])


def test_floor_placement_sits_on_the_floor() -> None:
    dims = [0.35, 1.55, 0.35]
    p = solve(DEMO, dims, placement="floor")
    # position is the CENTRE (spec 8.2), so y = floor + half height
    assert p.position[1] == pytest.approx(DEMO["floor_y"] + dims[1] / 2, abs=1e-6)


def test_solver_does_not_block_the_dock() -> None:
    dock = DEMO["robot_dock"]
    p = solve(DEMO, [0.4, 0.6, 0.4], placement="floor")
    assert dist_xz(p.position, (dock[0], 0, dock[2])) > 0.4


def test_surface_placement_lands_on_a_table_top() -> None:
    p = solve(DEMO, [0.12, 0.25, 0.12], placement="surface")
    assert p.on is not None
    surf = next(o for o in DEMO["objects"] if o["id"] == p.on)
    assert p.position[1] == pytest.approx(
        surf["surface_height"] + 0.25 / 2, abs=1e-6
    )


def test_place_on_pins_a_specific_surface() -> None:
    p = solve(DEMO, [0.10, 0.15, 0.10], placement="surface", place_on="shelf_01")
    assert p.on == "shelf_01"


def test_object_too_big_for_a_surface_falls_to_the_floor() -> None:
    p = solve(DEMO, [3.0, 0.3, 2.0], placement="surface")
    assert p.on is None


def test_camera_position_pulls_placement_closer() -> None:
    """An object should appear where the user is looking, not behind them."""
    near = solve(DEMO, [0.3, 0.4, 0.3], placement="floor", camera_xz=(2.0, 1.5))
    far = solve(DEMO, [0.3, 0.4, 0.3], placement="floor", camera_xz=(-2.0, -1.5))
    assert dist_xz(near.position, (2.0, 0, 1.5)) < dist_xz(far.position, (2.0, 0, 1.5))


def test_crowded_room_flags_for_review_rather_than_overlapping() -> None:
    """A visibly wrong position the user can drag beats an object buried
    inside the sofa."""
    packed = dict(DEMO)
    packed["objects"] = [{
        "id": "wall_01", "label": "wall", "position": [0.0, 1.0, 0.0],
        "dimensions": [12.0, 2.0, 12.0], "rotation_y": 0.0, "is_obstacle": True,
    }]
    p = solve(packed, [0.4, 0.5, 0.4], placement="floor")
    assert p.needs_review
    assert p.reasons


def test_result_carries_a_human_reason() -> None:
    p = solve(DEMO, [0.35, 1.55, 0.35], placement="floor")
    assert p.reasons, "the UI shows this to explain why it landed there"


# ── the invariant that matters most ──

@pytest.mark.parametrize("dims", [
    [0.35, 1.55, 0.35], [1.20, 0.74, 0.70], [0.09, 0.10, 0.09],
    [0.90, 1.80, 0.30], [0.40, 0.70, 0.40],
])
def test_no_generated_object_ever_overlaps_an_existing_one(dims) -> None:
    p = solve(DEMO, dims, placement="floor")
    if not p.needs_review:
        assert collides(DEMO, p.position, dims) is None, (
            f"{dims} placed at {p.position} overlaps an existing object"
        )
