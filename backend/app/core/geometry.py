"""Geometry helpers. Right-handed, Y-up, metres (spec 8.1).

+X right, +Y up, +Z toward the viewer.
Yaw 0 faces +Z; positive yaw rotates toward +X (clockwise seen from above).
"""
from __future__ import annotations

import math

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]


def wrap_angle(a: float) -> float:
    """Wrap radians to (-pi, pi]."""
    return math.atan2(math.sin(a), math.cos(a))


def shortest_angle(frm: float, to: float) -> float:
    """Signed smallest rotation from `frm` to `to`. Never returns the long way round -
    this is what stops the twin's head snapping 180 degrees at the wrap point."""
    return wrap_angle(to - frm)


def yaw_towards(from_xz: Vec2, to_xz: Vec2) -> float:
    """Yaw that faces from one XZ point to another, in the spec's convention:
    yaw 0 = +Z, positive yaw rotates toward +X."""
    dx = to_xz[0] - from_xz[0]
    dz = to_xz[1] - from_xz[1]
    return math.atan2(dx, dz)


def dist2d(a: Vec2, b: Vec2) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def obb_corners_xz(
    position: Vec3, dimensions: Vec3, rotation_y: float
) -> list[Vec2]:
    """Footprint corners of an oriented bounding box, projected to XZ.

    `position` is the box CENTRE (spec 8.2), `dimensions` is [w, h, d].
    """
    hw = dimensions[0] / 2.0
    hd = dimensions[2] / 2.0
    cx, _, cz = position
    c, s = math.cos(rotation_y), math.sin(rotation_y)
    out: list[Vec2] = []
    for dx, dz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        # rotate about Y then translate
        rx = dx * c + dz * s
        rz = -dx * s + dz * c
        out.append((cx + rx, cz + rz))
    return out


def obb_aabb_xz(
    position: Vec3, dimensions: Vec3, rotation_y: float
) -> tuple[float, float, float, float]:
    """Axis-aligned XZ bounds (min_x, min_z, max_x, max_z) of a rotated box."""
    pts = obb_corners_xz(position, dimensions, rotation_y)
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    return min(xs), min(zs), max(xs), max(zs)


def point_in_obb_xz(
    p: Vec2, position: Vec3, dimensions: Vec3, rotation_y: float
) -> bool:
    """Is an XZ point inside a rotated box footprint? Rotate the point into the
    box's local frame and do a trivial axis-aligned test."""
    cx, _, cz = position
    dx, dz = p[0] - cx, p[1] - cz
    c, s = math.cos(-rotation_y), math.sin(-rotation_y)
    lx = dx * c + dz * s
    lz = -dx * s + dz * c
    return abs(lx) <= dimensions[0] / 2.0 and abs(lz) <= dimensions[2] / 2.0


def obb_overlap_xz(
    a_pos: Vec3, a_dim: Vec3, a_rot: float,
    b_pos: Vec3, b_dim: Vec3, b_rot: float,
    margin: float = 0.0,
) -> bool:
    """Separating Axis Theorem on the XZ plane, with an optional clearance margin.

    Used by the Imagine placement solver (spec 10B.6) to hard-reject a generated
    object that would intersect an existing one.
    """
    def axes(rot: float) -> list[Vec2]:
        return [(math.cos(rot), -math.sin(rot)), (math.sin(rot), math.cos(rot))]

    # inflate A by the margin so "touching" counts as overlapping
    a_dim = (a_dim[0] + 2 * margin, a_dim[1], a_dim[2] + 2 * margin)
    ca = obb_corners_xz(a_pos, a_dim, a_rot)
    cb = obb_corners_xz(b_pos, b_dim, b_rot)

    for ax in axes(a_rot) + axes(b_rot):
        pa = [c[0] * ax[0] + c[1] * ax[1] for c in ca]
        pb = [c[0] * ax[0] + c[1] * ax[1] for c in cb]
        if max(pa) < min(pb) or max(pb) < min(pa):
            return False  # found a separating axis
    return True
