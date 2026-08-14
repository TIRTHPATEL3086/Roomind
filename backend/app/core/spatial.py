"""The spatial relation layer: where things are relative to each other.

"Go to the chair near the table" is two problems, and only one of them is hard.
Deciding which chairs exist is recognition. Deciding which of them is *near the
table* is geometry, and geometry has exact answers — so this module computes
them once, deterministically, and the resolver filters on the result rather
than asking a language model to estimate distances it cannot see.

Everything here is measured between ORIENTED BOXES, not between centres. Two
sofas whose centres are 2 m apart can be touching; centre distance would call
them far apart and "the lamp next to the sofa" would pick the wrong lamp.

Frames — spec 8.1, and worth re-reading before editing anything below:

    right-handed, Y-up, metres
    yaw 0 faces +Z, positive yaw rotates toward +X

That last clause makes it a *left-handed* rotation about Y, and it has already
caused three separate bugs elsewhere in this project. Two consequences are
load-bearing here:

    ROOM frame     facing +Z, so +X is to the RIGHT and -X is to the LEFT
    BODY frame     bx = dx*cos(yaw) - dz*sin(yaw)   component along `right`
                   bz = dx*sin(yaw) + dz*cos(yaw)   component along `forward`

The body-frame transform is `+yaw`, not the textbook `-yaw`, and it is copied
from `kinematics.world_to_body` on purpose — one convention, stated once.

Pure stdlib: the API imports this directly and the reconstruction pipeline
imports it over sys.path from its own venv, the same arrangement firmware/sim
uses for kinematics. A relation the pipeline bakes into room.json and one the
resolver computes live must come out of the same code, or "near" quietly means
two different things at two ends of the system.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.geometry import Vec2, obb_corners_xz

# Surface gap under which two objects count as related. 0.90 m is roughly "you
# could not walk between them comfortably" — ARIA's own inflated footprint is
# 0.62 m across, so anything under this really is a gap she would not route
# through, which is what makes "near" mean something physical rather than
# decorative.
NEAR_M = 0.90
# Touching-or-nearly distance for the stronger words.
BESIDE_M = 0.35
# Beyond this, objects are explicitly "far" from each other.
FAR_M = 2.50

# A directional relation is only emitted when one axis clearly dominates. At
# 45 degrees "left of" and "in front of" are equally true and equally useless,
# and emitting both makes every filter match everything.
DIRECTION_DOMINANCE = 1.30

DIRECTIONAL = ("left_of", "right_of", "in_front_of", "behind")


# ───────────────────────────────── geometry ────────────────────────────────

def corners_xz(obj: dict) -> list[Vec2]:
    """The four XZ corners of a scene-graph object's oriented box.

    Delegates to `geometry.obb_corners_xz` rather than repeating the rotation:
    the sign convention in there is the one the navmesh rasteriser already
    trusts, and two copies of it is exactly how the yaw-sign bug in section 7.1
    got in three times.
    """
    return obb_corners_xz(
        tuple(float(v) for v in obj["position"]),
        tuple(float(v) for v in obj["dimensions"]),
        float(obj.get("rotation_y", 0.0)),
    )


def _seg_point_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    px, pz = p
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    length_sq = dx * dx + dz * dz
    if length_sq <= 1e-12:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / length_sq))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def _polys_intersect(p: list[Vec2], q: list[Vec2]) -> bool:
    """Separating-axis test over two convex polygons."""
    for poly in (p, q):
        n = len(poly)
        for i in range(n):
            ax, az = poly[i]
            bx, bz = poly[(i + 1) % n]
            # outward normal of this edge
            nx, nz = bz - az, -(bx - ax)
            p_min = min(nx * x + nz * z for x, z in p)
            p_max = max(nx * x + nz * z for x, z in p)
            q_min = min(nx * x + nz * z for x, z in q)
            q_max = max(nx * x + nz * z for x, z in q)
            if p_max < q_min or q_max < p_min:
                return False
    return True


def polygon_gap(p: list[Vec2], q: list[Vec2]) -> float:
    """Exact shortest distance between two convex polygons. 0 if they overlap.

    Exhaustive vertex-to-edge, both directions: 32 point-segment tests for two
    boxes, which is nothing, and it is exact for corner-to-corner cases that a
    separating-axis approximation gets wrong by up to the corner offset.
    """
    if _polys_intersect(p, q):
        return 0.0
    best = math.inf
    for poly_a, poly_b in ((p, q), (q, p)):
        n = len(poly_b)
        for point in poly_a:
            for i in range(n):
                best = min(best, _seg_point_distance(point, poly_b[i],
                                                     poly_b[(i + 1) % n]))
    return best


def surface_gap(a: dict, b: dict) -> float:
    """Gap in metres between two scene-graph objects' footprints."""
    return polygon_gap(corners_xz(a), corners_xz(b))


def centre_distance(a: dict, b: dict) -> float:
    ax, _, az = a["position"]
    bx, _, bz = b["position"]
    return math.hypot(float(ax) - float(bx), float(az) - float(bz))


def footprint_radius(obj: dict) -> float:
    """Half the diagonal of the footprint - how far the box reaches from centre."""
    w, _, d = (float(v) for v in obj["dimensions"])
    return math.hypot(w, d) / 2.0


def volume(obj: dict) -> float:
    w, h, d = (float(v) for v in obj["dimensions"])
    return w * h * d


# ────────────────────────────────── frames ─────────────────────────────────

def world_to_body(dx: float, dz: float, yaw: float) -> Vec2:
    """World XZ offset -> (right, forward) in a body frame at `yaw`.

    `+yaw`, not `-yaw`. See the module docstring: this project measures yaw from
    +Z toward +X, which is a left-handed rotation about Y, and the sign flip is
    exactly the bug caught by test_look_respects_base_yaw in kinematics.
    """
    c, s = math.cos(yaw), math.sin(yaw)
    return (dx * c - dz * s, dx * s + dz * c)


def egocentric(obj: dict, viewer_xz: Vec2, viewer_yaw: float) -> dict:
    """Where `obj` sits from a viewer standing at `viewer_xz` facing `viewer_yaw`.

    Used for "the chair on the left", which is meaningless without a point of
    view. ARIA's live pose is the point of view when she has one, because she
    is the agent that has to go there.
    """
    ox, _, oz = obj["position"]
    right, forward = world_to_body(float(ox) - viewer_xz[0],
                                   float(oz) - viewer_xz[1], viewer_yaw)
    return {
        "right": right,
        "forward": forward,
        "side": "right" if right >= 0 else "left",
        "depth": "front" if forward >= 0 else "behind",
        "distance": math.hypot(right, forward),
        # How unambiguous the left/right call is. Something dead ahead is
        # neither left nor right, and saying it is either is a guess.
        "lateral_clarity": abs(right) / max(abs(forward), 1e-6),
    }


def room_frame(obj: dict) -> dict:
    """Where `obj` sits in the ROOM's own frame (facing +Z, right is +X)."""
    ox, _, oz = obj["position"]
    return {"right": float(ox), "forward": float(oz),
            "side": "right" if float(ox) >= 0 else "left"}


# ──────────────────────────────── relations ────────────────────────────────

@dataclass(frozen=True)
class Relation:
    frm: str
    rel: str
    to: str
    distance_m: float

    def as_dict(self) -> dict:
        return {"from": self.frm, "rel": self.rel, "to": self.to,
                "distance_m": round(self.distance_m, 3)}

    def as_outgoing(self) -> dict:
        return {"rel": self.rel, "to": self.to,
                "distance_m": round(self.distance_m, 3)}


def _directional(a: dict, b: dict) -> str | None:
    """Room-frame direction of `a` relative to `b`, or None if ambiguous."""
    ax, _, az = (float(v) for v in a["position"])
    bx, _, bz = (float(v) for v in b["position"])
    dx, dz = ax - bx, az - bz

    if abs(dx) > abs(dz) * DIRECTION_DOMINANCE:
        # +X is the room's right (facing +Z), so a smaller X is to its left.
        return "right_of" if dx > 0 else "left_of"
    if abs(dz) > abs(dx) * DIRECTION_DOMINANCE:
        # +Z is the room's forward.
        return "in_front_of" if dz > 0 else "behind"
    return None


def _supported_by(a: dict, b: dict) -> bool:
    """Is `a` resting on `b`'s top surface?"""
    top = b.get("surface_height")
    if top is None:
        return False
    ay, ah = float(a["position"][1]), float(a["dimensions"][1])
    bottom = ay - ah / 2.0
    if abs(bottom - float(top)) > 0.12:
        return False
    # and its footprint has to actually be over the other object
    return surface_gap(a, b) <= 0.02


def compute_relations(objects: list[dict], near_m: float = NEAR_M,
                      max_per_object: int = 12) -> list[Relation]:
    """Every pairwise spatial relation in the room, nearest first.

    Ordered nearest-first and capped per object so a 40-object room does not
    ship 1,600 relations the resolver has to scan; the nearest dozen is every
    relation a person would ever refer to, and the cap is applied AFTER
    sorting so it drops the useless far ones rather than an arbitrary slice.
    """
    out: list[Relation] = []
    by_source: dict[str, list[Relation]] = {}

    for a in objects:
        rels: list[Relation] = []
        for b in objects:
            if a["id"] == b["id"]:
                continue
            gap = surface_gap(a, b)

            if _supported_by(a, b):
                rels.append(Relation(a["id"], "on", b["id"], gap))
            elif _supported_by(b, a):
                rels.append(Relation(a["id"], "under", b["id"], gap))

            if gap <= BESIDE_M:
                rels.append(Relation(a["id"], "beside", b["id"], gap))
                rels.append(Relation(a["id"], "next_to", b["id"], gap))
            if gap <= near_m:
                rels.append(Relation(a["id"], "near", b["id"], gap))
            elif gap >= FAR_M:
                rels.append(Relation(a["id"], "far", b["id"], gap))

            if (direction := _directional(a, b)) is not None:
                rels.append(Relation(a["id"], direction, b["id"], gap))

        rels.sort(key=lambda r: (r.distance_m, r.rel, r.to))
        by_source[a["id"]] = rels[: max_per_object * 2]

    for a in objects:
        out.extend(by_source.get(a["id"], []))
    return out


def attach_relations(objects: list[dict], near_m: float = NEAR_M) -> list[Relation]:
    """Compute relations and write each object's outgoing ones into attributes.

    Both forms are kept on purpose. The room-level list is what a query like
    "which chairs are near a table" scans; the per-object copy is what the
    frontend and the companion prompt read without having to index anything.
    """
    relations = compute_relations(objects, near_m=near_m)
    grouped: dict[str, list[dict]] = {}
    for r in relations:
        grouped.setdefault(r.frm, []).append(r.as_outgoing())
    for obj in objects:
        attrs = obj.setdefault("attributes", {})
        mine = grouped.get(obj["id"], [])
        if mine:
            attrs["relations"] = mine
        else:
            attrs.pop("relations", None)
    return relations


def has_relation(obj: dict, rel: str, target_ids: set[str]) -> bool:
    """Does `obj` hold `rel` to any of `target_ids`?"""
    for r in (obj.get("attributes") or {}).get("relations", []):
        if r.get("rel") == rel and r.get("to") in target_ids:
            return True
    return False


def relation_distance(obj: dict, rel: str, target_ids: set[str]) -> float:
    """Closest distance over the matching relations, or inf if none match."""
    best = math.inf
    for r in (obj.get("attributes") or {}).get("relations", []):
        if r.get("rel") == rel and r.get("to") in target_ids:
            best = min(best, float(r.get("distance_m", 0.0)))
    return best


# ───────────────────────────────── size class ──────────────────────────────

# Instances within this much of each other's volume are the same size, and
# calling one of them "the large chair" would be a lie the user could act on.
SIZE_SPREAD_MIN = 0.22


def assign_size_classes(objects: list[dict]) -> None:
    """Tag each object small/medium/large RELATIVE TO ITS OWN CLASS.

    Relative, not absolute, because "the big chair" means big for a chair. And
    only when the class has at least two instances with a real spread — a lone
    chair is neither large nor small, and three identical chairs are all the
    same size no matter how the volumes round.
    """
    by_class: dict[str, list[dict]] = {}
    for obj in objects:
        cls = (obj.get("attributes") or {}).get("class") or obj["label"]
        by_class.setdefault(cls, []).append(obj)

    for group in by_class.values():
        for obj in group:
            (obj.get("attributes") or {}).pop("size_class", None)
        if len(group) < 2:
            continue

        volumes = [volume(o) for o in group]
        lo, hi = min(volumes), max(volumes)
        if lo <= 0 or (hi - lo) / hi < SIZE_SPREAD_MIN:
            continue

        span = hi - lo
        for obj, vol in zip(group, volumes, strict=True):
            frac = (vol - lo) / span
            if frac >= 0.66:
                klass = "large"
            elif frac <= 0.34:
                klass = "small"
            else:
                klass = "medium"
            obj.setdefault("attributes", {})["size_class"] = klass
