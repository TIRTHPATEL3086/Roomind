"""Geometry shared by the reconstruction steps.

Everything here obeys spec 8.1: right-handed, Y-up, metres, yaw measured from
+Z *toward* +X.

>>> SIGN WARNING - the spec's own snippet in 10.7 gets this wrong <<<

Section 10.7 defines the OBB yaw as

    yaw = arctan2(vt[0, 1], vt[0, 0])        # WRONG for this project

with xz = pts[:, [0, 2]], so vt[0] is (x_component, z_component). That formula
measures the angle from +X toward +Z -- the ordinary maths convention, and the
exact mirror of what 8.1 specifies. Feeding it a sofa aligned with +Z returns
yaw 0 correctly by luck, but a sofa aligned with +X returns 0 instead of 90 deg,
so every object in the room comes out rotated by its own angle, negated.

This is the same family of bug as the -yaw/+yaw error in the 12.6.3 C++ snippet
that broke look_at (see backend/app/core/kinematics.py). Both come from copying
a textbook formula into a left-handed-about-Y convention. The correct form
swaps the arguments:

    yaw = arctan2(x_component, z_component)

test_lift3d.py::test_yaw_matches_spec_8_1 pins all four cardinal directions so
this cannot regress.
"""
from __future__ import annotations

import math

import numpy as np

# Rejected outright in S10 (spec 10.7 post-processing table).
MIN_DIM_M = 0.05
MAX_DIM_M = 4.0


def yaw_from_xz(x_component: float, z_component: float) -> float:
    """Yaw of a direction vector, per spec 8.1: 0 = +Z, positive toward +X."""
    return float(math.atan2(x_component, z_component))


def world_to_local_xz(xz_centred: np.ndarray, yaw: float) -> np.ndarray:
    """Rotate centred (x, z) world offsets into the box's local frame.

    Identical maths to kinematics.world_to_body, kept in the same +yaw
    convention on purpose: if these two ever disagree, the robot points at a
    different place than the box says it is.
    """
    c, s = math.cos(yaw), math.sin(yaw)
    m = np.array([[c, -s], [s, c]], dtype=np.float64)
    return xz_centred @ m.T


def min_area_rect_xz(xz: np.ndarray) -> tuple[np.ndarray, float, float, float]:
    """Minimum-area enclosing rectangle of 2D points (rotating calipers).

    Returns (centre, extent_along_axis, extent_across_axis, yaw) where yaw is
    the direction of the LONGER side, in the spec 8.1 convention.

    Why not PCA, which is what 10.7 suggests? PCA finds the direction of
    greatest VARIANCE, which is only the right answer when the footprint is
    clearly oblong. A chair is roughly square in plan (0.55 x 0.60 m), so the
    variance is almost equal along every direction and the fitted angle is
    essentially noise -- and a square fitted at 45 degrees measures
    0.55*cos45 + 0.60*sin45 = 0.81 m on each side, inflating a chair by 40%.
    That was not hypothetical: it is exactly what the first version of this
    function did to test_multi_view_lift_recovers_a_chair.

    The minimum-area rectangle has no such failure mode. Its optimum is always
    flush with an edge of the convex hull, so it is exact for any convex
    footprint and degrades gracefully for a partly-observed one.
    """
    from scipy.spatial import ConvexHull

    xz = np.asarray(xz, dtype=np.float64)
    if len(xz) < 3:
        lo, hi = xz.min(0), xz.max(0)
        return (lo + hi) / 2, float(hi[0] - lo[0]), float(hi[1] - lo[1]), 0.0

    try:
        hull = xz[ConvexHull(xz).vertices]
    except Exception:  # noqa: BLE001 - degenerate (collinear) clouds
        lo, hi = xz.min(0), xz.max(0)
        return (lo + hi) / 2, float(hi[0] - lo[0]), float(hi[1] - lo[1]), 0.0

    edges = np.roll(hull, -1, axis=0) - hull
    lengths = np.linalg.norm(edges, axis=1)
    edges = edges[lengths > 1e-12] / lengths[lengths > 1e-12, None]

    best = None
    for ex, ez in edges:
        # Project the hull onto this edge and its normal.
        along = hull @ np.array([ex, ez])
        across = hull @ np.array([-ez, ex])
        w = along.max() - along.min()
        h = across.max() - across.min()
        area = w * h
        if best is None or area < best[0]:
            mid_a = (along.max() + along.min()) / 2
            mid_c = (across.max() + across.min()) / 2
            centre = mid_a * np.array([ex, ez]) + mid_c * np.array([-ez, ex])
            best = (area, w, h, ex, ez, centre)

    _, w, h, ex, ez, centre = best
    # Report the LONGER side as the box's local +Z. Putting the long axis on a
    # fixed local axis makes the representation canonical, which is what lets
    # two views of one sofa cluster together instead of looking 90 deg apart.
    if w >= h:
        return centre, float(h), float(w), yaw_from_xz(ex, ez)
    return centre, float(w), float(h), yaw_from_xz(-ez, ex)


def fit_oriented_box_yaw_only(pts: np.ndarray) -> dict:
    """Yaw-only OBB around a point cloud (spec 10.7).

    Roll and pitch are deliberately not estimated: furniture stands upright, so
    solving for them fits noise and produces tilted sofas.

    The box's long horizontal axis becomes its local +Z (its "depth"), which is
    what makes rotation_y compose correctly with a [width, height, depth] box
    in the renderer.
    """
    pts = np.asarray(pts, dtype=np.float64)
    centre_xz, width, depth, yaw = min_area_rect_xz(pts[:, [0, 2]])
    y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())

    # The centre comes from the rectangle's extents, never from the mean of the
    # points: only the camera-facing shell of an object is ever observed, and
    # perspective packs more samples onto the near face, so the mean sits
    # centimetres toward the camera. Extents do not care how many points there
    # are, only where the outermost ones lie.
    return {
        "position": [float(centre_xz[0]), (y_min + y_max) / 2, float(centre_xz[1])],
        "dimensions": [width, y_max - y_min, depth],
        "rotation_y": yaw,
        "surface_height": y_max,
        "y_min": y_min,
    }


def canonicalise_yaw(box: dict) -> dict:
    """Fold yaw into [-90, 90).

    A box rotated 180 degrees is the same box, but the fitter has no way to
    know which end is the "front" -- so two views of one sofa can come back as
    10 deg and 190 deg and the IoU clustering never merges them. Folding modulo
    180 makes the representation unique.

    Note this fold is modulo 180, not 90, so the local axes never trade places
    and the dimensions pass through untouched. min_area_rect_xz has already put
    the long side on local +Z, which is the part that needed canonicalising.
    """
    out = dict(box)
    out["rotation_y"] = (box["rotation_y"] + math.pi / 2) % math.pi - math.pi / 2
    return out


def aabb_of(box: dict) -> tuple[np.ndarray, np.ndarray]:
    """Axis-aligned bounds of a yaw-rotated box, in world space."""
    px, py, pz = box["position"]
    w, h, d = box["dimensions"]
    c, s = abs(math.cos(box["rotation_y"])), abs(math.sin(box["rotation_y"]))
    # Extent of a rotated rectangle projected onto the world axes.
    ex = (w * c + d * s) / 2
    ez = (w * s + d * c) / 2
    lo = np.array([px - ex, py - h / 2, pz - ez])
    hi = np.array([px + ex, py + h / 2, pz + ez])
    return lo, hi


def iou3d(a: dict, b: dict) -> float:
    """IoU of two boxes, computed on their axis-aligned bounds.

    An approximation, and a deliberate one: exact OBB intersection needs a
    convex-hull clip per pair, and this runs across every detection pair in
    every frame. For merging multi-view detections of the SAME object the
    boxes are nearly co-oriented anyway, so the AABB error is small where it
    matters and the cost is a few microseconds.
    """
    alo, ahi = aabb_of(a)
    blo, bhi = aabb_of(b)
    lo = np.maximum(alo, blo)
    hi = np.minimum(ahi, bhi)
    dims = np.clip(hi - lo, 0, None)
    inter = float(dims.prod())
    if inter <= 0:
        return 0.0
    va = float((ahi - alo).prod())
    vb = float((bhi - blo).prod())
    union = va + vb - inter
    return inter / union if union > 0 else 0.0


def remove_outliers(pts: np.ndarray, nb: int = 20, std_ratio: float = 2.0) -> np.ndarray:
    """Statistical outlier removal, Open3D's algorithm without the dependency.

    Drops points whose mean distance to their nb nearest neighbours is more than
    std_ratio standard deviations above the global mean. This is what stops a
    handful of background pixels bleeding through a bounding box and stretching
    the OBB across the room.
    """
    from scipy.spatial import cKDTree

    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    if n <= nb + 1:
        return pts

    # A k-d tree, not brute-force pairwise distances. The n x n distance matrix
    # is O(n^2) in both time and memory -- 800 MB at n = 10k -- and a close-up
    # sofa easily fills that many pixels. The first version of this ran the
    # whole lift3d test file in 119 s; the tree does the same work in seconds.
    k = min(nb, n - 1)
    dist, _ = cKDTree(pts).query(pts, k=k + 1, workers=-1)
    means = dist[:, 1:].mean(axis=1)          # column 0 is the point itself

    thresh = means.mean() + std_ratio * means.std()
    keep = means <= thresh
    return pts[keep] if keep.any() else pts


def voxel_downsample(pts: np.ndarray, voxel: float) -> np.ndarray:
    """One point per occupied voxel. Keeps outlier removal affordable."""
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) == 0 or voxel <= 0:
        return pts
    keys = np.floor(pts / voxel).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    return pts[np.sort(idx)]


def dims_plausible(dims) -> bool:
    """Spec 10.7: reject anything smaller than 5 cm or larger than 4 m."""
    return all(MIN_DIM_M <= float(v) <= MAX_DIM_M for v in dims)
