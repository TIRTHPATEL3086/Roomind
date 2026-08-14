"""Placement solver — where a generated object goes (spec 10B.6).

Pure geometry over the scene graph. Runs in the Imagine Manager's process
(the backend), not in the genai3d subprocess, because it needs the live scene.

The hard rule: a generated object must never overlap an existing one, and once
committed the navmesh must be re-baked. A generated obstacle that A* cannot see
is a robot that drives into a lamp.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

CLEARANCE_M = 0.15          # hard reject below this gap to any existing object
SURFACE_MARGIN_M = 0.05     # inset from the edge when placing on a table top
DOORWAY_KEEPOUT_M = 0.45    # don't block the dock


@dataclass
class Placement:
    position: tuple[float, float, float]
    rotation_y: float = 0.0
    on: str | None = None            # id of the surface it sits on, if any
    score: float = 0.0
    needs_review: bool = False       # nothing scored well; user should confirm
    reasons: list[str] = field(default_factory=list)


def _obb_overlap_xz(a_pos, a_dim, a_rot, b_pos, b_dim, b_rot, margin=0.0) -> bool:
    """Separating Axis Theorem on XZ, with clearance baked into A."""
    def corners(pos, dim, rot):
        hw, hd = dim[0] / 2, dim[2] / 2
        c, s = math.cos(rot), math.sin(rot)
        return [
            (pos[0] + dx * c + dz * s, pos[2] - dx * s + dz * c)
            for dx, dz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))
        ]

    a_dim = (a_dim[0] + 2 * margin, a_dim[1], a_dim[2] + 2 * margin)
    ca, cb = corners(a_pos, a_dim, a_rot), corners(b_pos, b_dim, b_rot)
    for rot in (a_rot, b_rot):
        for ax in ((math.cos(rot), -math.sin(rot)), (math.sin(rot), math.cos(rot))):
            pa = [p[0] * ax[0] + p[1] * ax[1] for p in ca]
            pb = [p[0] * ax[0] + p[1] * ax[1] for p in cb]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def collides(graph: dict, pos, dims, rot: float = 0.0,
             ignore: set[str] | None = None) -> str | None:
    """Id of the first object this would overlap, or None. Hard reject."""
    ignore = ignore or set()
    for o in graph.get("objects", []):
        if o["id"] in ignore or not o.get("is_obstacle", True):
            continue
        if _obb_overlap_xz(pos, dims, rot,
                           tuple(o["position"]), tuple(o["dimensions"]),
                           float(o.get("rotation_y", 0.0)),
                           margin=CLEARANCE_M):
            return o["id"]
    return None


def in_bounds(graph: dict, pos, dims) -> bool:
    b = graph["bounds"]
    hw, hd = dims[0] / 2, dims[2] / 2
    return (b["min"][0] + hw <= pos[0] <= b["max"][0] - hw
            and b["min"][2] + hd <= pos[2] <= b["max"][2] - hd)


def _surfaces(graph: dict, dims) -> list[dict]:
    """Objects with a usable flat top big enough to hold this."""
    return [
        o for o in graph.get("objects", [])
        if o.get("surface_height")
        and o["dimensions"][0] >= dims[0] + SURFACE_MARGIN_M
        and o["dimensions"][2] >= dims[2] + SURFACE_MARGIN_M
    ]


def solve(graph: dict, dims, placement: str = "floor",
          place_on: str | None = None,
          camera_xz: tuple[float, float] | None = None) -> Placement:
    """Find a spot for an object of `dims`.

    `placement` is the VLM's hint: floor | surface | wall.
    `place_on` pins a specific surface object id when the user asked for one.
    """
    floor_y = graph.get("floor_y", 0.0)
    reasons: list[str] = []

    # ── surface placement ──
    if placement == "surface" or place_on:
        candidates = _surfaces(graph, dims)
        if place_on:
            candidates = [o for o in candidates if o["id"] == place_on]
            if not candidates:
                reasons.append(f"'{place_on}' has no usable top surface")
        for surf in sorted(candidates, key=lambda o: -o["surface_height"]):
            pos = (surf["position"][0],
                   surf["surface_height"] + dims[1] / 2,
                   surf["position"][2])
            # Objects on a table don't collide with the table itself.
            hit = collides(graph, pos, dims, ignore={surf["id"]})
            if hit is None:
                return Placement(position=pos, on=surf["id"], score=10.0,
                                 reasons=[f"on top of {surf['id']}"])
            reasons.append(f"{surf['id']} top blocked by {hit}")

    # ── floor placement: score a grid of candidates ──
    b = graph["bounds"]
    dock = graph.get("robot_dock", [0, 0, 0])
    best: Placement | None = None
    step = 0.25

    x = b["min"][0] + dims[0] / 2
    while x <= b["max"][0] - dims[0] / 2:
        z = b["min"][2] + dims[2] / 2
        while z <= b["max"][2] - dims[2] / 2:
            pos = (x, floor_y + dims[1] / 2, z)
            if collides(graph, pos, dims) is None:
                score = 0.0
                # near the room centre reads as "placed", not "shoved aside"
                cx = (b["min"][0] + b["max"][0]) / 2
                cz = (b["min"][2] + b["max"][2]) / 2
                score += 2.0 - min(2.0, math.hypot(x - cx, z - cz) / 2.0)
                # in front of the camera if we know where it is
                if camera_xz:
                    score += 3.0 - min(3.0, math.hypot(x - camera_xz[0],
                                                       z - camera_xz[1]) / 2.0)
                # never block the dock
                if math.hypot(x - dock[0], z - dock[2]) < DOORWAY_KEEPOUT_M:
                    score -= 5.0
                if best is None or score > best.score:
                    best = Placement(position=pos, score=score,
                                     reasons=["free floor space"])
            z += step
        x += step

    if best is not None:
        return best

    # ── nothing fits: put it in front of the camera and ask the user ──
    # Deliberately NOT overlapping something as a fallback — a visibly wrong
    # position the user can drag beats an object buried inside the sofa.
    fallback = camera_xz or (0.0, 0.0)
    reasons.append("no clear spot found — placed for review")
    return Placement(
        position=(fallback[0], floor_y + dims[1] / 2, fallback[1]),
        score=0.0, needs_review=True, reasons=reasons,
    )
