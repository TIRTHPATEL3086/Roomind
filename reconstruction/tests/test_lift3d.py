"""S08 lifting tests (required by the Phase 5 prompt).

These are built around SYNTHETIC boxes with exactly known geometry. That is the
only way to test a reconstruction step honestly: with real capture data you can
tell that the answer looks plausible, but not that it is right to a centimetre.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from steps.s08_lift3d import (
    backproject_box,
    lift_boxes_to_3d,
    sanitise_label,
    _circular_mean_yaw,
)
from utils.geometry import (
    canonicalise_yaw,
    fit_oriented_box_yaw_only,
    iou3d,
    yaw_from_xz,
)


def box_cloud(centre, dims, yaw, n=4000, seed=0):
    """Dense point cloud filling a yaw-rotated box, in world space."""
    rng = np.random.default_rng(seed)
    w, h, d = dims
    local = rng.uniform(-0.5, 0.5, size=(n, 3)) * np.array([w, h, d])
    # local -> world, spec 8.1: yaw 0 faces +Z, positive turns toward +X.
    c, s = math.cos(yaw), math.sin(yaw)
    x = local[:, 0] * c + local[:, 2] * s
    z = -local[:, 0] * s + local[:, 2] * c
    return np.stack([x, local[:, 1], z], axis=1) + np.asarray(centre)


# ─────────────────────────── the yaw convention ───────────────────────────

def test_yaw_from_xz_matches_spec_8_1():
    """0 = +Z, positive toward +X. The spec's own 10.7 snippet has this mirrored."""
    assert yaw_from_xz(0, 1) == pytest.approx(0.0)                    # +Z
    assert yaw_from_xz(1, 0) == pytest.approx(math.pi / 2)            # +X
    assert yaw_from_xz(0, -1) == pytest.approx(math.pi)               # -Z
    assert yaw_from_xz(-1, 0) == pytest.approx(-math.pi / 2)          # -X


@pytest.mark.parametrize("yaw_deg", [0, 15, 30, 45, -30, -60, 80])
def test_obb_recovers_the_yaw_it_was_built_with(yaw_deg):
    yaw = math.radians(yaw_deg)
    # Deliberately oblong: PCA needs a dominant axis to have an opinion.
    pts = box_cloud((1.0, 0.4, -0.5), (0.6, 0.8, 1.8), yaw)
    box = canonicalise_yaw(fit_oriented_box_yaw_only(pts))
    assert box["rotation_y"] == pytest.approx(yaw, abs=0.03)


def test_canonicalisation_folds_modulo_180_and_keeps_the_shape():
    """95 deg folds to -85 deg -- a 180 deg turn, which maps a box onto itself.

    The dimensions must pass through untouched: only a 90 deg fold would trade
    the axes, and this fold is never 90.
    """
    pts = box_cloud((0, 0.5, 0), (0.6, 1.0, 1.8), math.radians(95))
    box = canonicalise_yaw(fit_oriented_box_yaw_only(pts))
    assert box["rotation_y"] == pytest.approx(math.radians(-85), abs=0.03)
    assert box["dimensions"] == pytest.approx([0.6, 1.0, 1.8], abs=0.05)


def test_two_views_180_degrees_apart_canonicalise_to_the_same_yaw():
    """The reason canonicalisation exists: these two must cluster together."""
    a = canonicalise_yaw(fit_oriented_box_yaw_only(
        box_cloud((0, 0.5, 0), (0.6, 1.0, 1.8), math.radians(20))))
    b = canonicalise_yaw(fit_oriented_box_yaw_only(
        box_cloud((0, 0.5, 0), (0.6, 1.0, 1.8), math.radians(200))))
    assert a["rotation_y"] == pytest.approx(b["rotation_y"], abs=0.03)


def test_obb_recovers_position_and_dimensions():
    centre, dims = (1.5, 0.45, -2.0), (0.8, 0.9, 1.6)
    box = fit_oriented_box_yaw_only(box_cloud(centre, dims, math.radians(20)))
    assert box["position"] == pytest.approx(list(centre), abs=0.05)
    assert box["dimensions"] == pytest.approx(list(dims), abs=0.06)
    assert box["surface_height"] == pytest.approx(centre[1] + dims[1] / 2, abs=0.05)


def test_centre_uses_extents_not_the_mean():
    """A cloud whose SAMPLES are lopsided must still yield a centred box.

    Perspective packs far more pixels onto the near face of an object than the
    far one, so the mean of the observed points sits centimetres toward the
    camera even when the full depth is visible. The midpoint of the extents
    does not care how many points there are, only where the outermost lie.

    (A uniformly-sampled partial box would NOT show this: there the mean and
    the extent midpoint agree exactly, which is why the first version of this
    test could not fail.)
    """
    rng = np.random.default_rng(0)
    # Heavily lopsided sampling: density rises toward the far face.
    z = -0.5 + rng.power(4.0, size=8000)
    x = rng.uniform(-0.5, 0.5, 8000)
    y = rng.uniform(0.0, 1.0, 8000)
    pts = np.stack([x, y, z], axis=1)

    # Both faces get a thin ring of samples. This is not a convenience: an
    # object's SILHOUETTE is always observed -- it is the outline the detector
    # drew its box around -- so the extremes are present however lopsided the
    # interior sampling is. Extents are unbiased exactly when that holds.
    for face_z in (-0.5, 0.5):
        ring = np.stack([rng.uniform(-0.5, 0.5, 200),
                         rng.uniform(0.0, 1.0, 200),
                         np.full(200, face_z)], axis=1)
        pts = np.vstack([pts, ring])

    box = fit_oriented_box_yaw_only(pts)
    mean_z = float(pts[:, 2].mean())

    assert mean_z > 0.15, "fixture should be lopsided toward the far face"
    assert abs(box["position"][2]) < 0.02, "extent midpoint should sit at 0"
    assert abs(box["position"][2]) < abs(mean_z)


# ───────────────────────────── circular mean ──────────────────────────────

def test_yaw_mean_wraps_across_the_half_circle():
    """-89 deg and +89 deg are 2 deg apart, not 178. Averaging must know that."""
    yaws = np.radians([-89.0, 89.0])
    got = math.degrees(_circular_mean_yaw(yaws, np.array([0.5, 0.5])))
    assert abs(abs(got) - 90.0) < 1.0      # near +/-90, NOT near 0


def test_yaw_mean_is_the_plain_mean_when_there_is_no_wrap():
    yaws = np.radians([10.0, 20.0, 30.0])
    got = math.degrees(_circular_mean_yaw(yaws, np.full(3, 1 / 3)))
    assert got == pytest.approx(20.0, abs=0.5)


# ──────────────────────────── back-projection ─────────────────────────────

def _camera(fx=500.0, w=640, h=480):
    return np.array([[fx, 0, w / 2], [0, fx, h / 2], [0, 0, 1]], dtype=np.float64)


def test_backprojection_puts_points_where_the_depth_says():
    K = _camera()
    depth = np.full((480, 640), 2.0)
    pose = np.eye(4)                       # camera at origin looking down +Z
    pts = backproject_box((300, 220, 340, 260), depth, K, pose)
    assert len(pts) > 0
    assert pts[:, 2] == pytest.approx(2.0, abs=1e-6)
    # Pixels near the principal point back-project near the optical axis.
    assert abs(pts[:, 0].mean()) < 0.1 and abs(pts[:, 1].mean()) < 0.1


def test_backprojection_rejects_background_bleed_through():
    """The gap between a chair's legs shows the far wall. It must not be kept."""
    K = _camera()
    depth = np.full((480, 640), 4.5)       # far wall
    depth[220:260, 300:340] = 1.5          # the object
    depth[230:240, 310:320] = 4.5          # a hole straight through it
    pts = backproject_box((300, 220, 340, 260), depth, K, np.eye(4))
    assert len(pts) > 0
    assert pts[:, 2].max() < 2.0, "wall depth survived the median-shell filter"


def test_backprojection_honours_the_camera_pose():
    K = _camera()
    depth = np.full((480, 640), 2.0)
    pose = np.eye(4)
    pose[:3, 3] = [5.0, 1.0, -3.0]
    pts = backproject_box((310, 230, 330, 250), depth, K, pose)
    assert pts[:, 0].mean() == pytest.approx(5.0, abs=0.1)
    assert pts[:, 2].mean() == pytest.approx(-1.0, abs=0.1)   # -3 + 2


def test_backprojection_survives_a_box_clipped_by_the_image_edge():
    K = _camera()
    depth = np.full((480, 640), 2.0)
    assert len(backproject_box((-50, -50, 40, 40), depth, K, np.eye(4))) > 0
    assert len(backproject_box((700, 500, 800, 600), depth, K, np.eye(4))) == 0


# ────────────────────────── multi-view merging ────────────────────────────

def _synthetic_views(centre, dims, yaw, n_views, label="chair", conf=0.9,
                     jitter=0.0, seed=0):
    """Render one box from n_views cameras placed around it.

    Each view sees only the camera-facing shell, exactly like a real capture,
    which is what makes the merge do real work.
    """
    rng = np.random.default_rng(seed)
    K = _camera()
    dets, depths, poses = [], [], []
    for i in range(n_views):
        ang = 2 * math.pi * i / n_views
        cam = np.array([centre[0] + 3.0 * math.sin(ang), centre[1],
                        centre[2] + 3.0 * math.cos(ang)])
        # Camera looks back at the object: its +Z axis points from cam to centre.
        fwd = np.asarray(centre) - cam
        fwd = fwd / np.linalg.norm(fwd)
        right = np.cross([0, 1, 0], fwd)
        right /= np.linalg.norm(right)
        up = np.cross(fwd, right)
        pose = np.eye(4)
        pose[:3, 0], pose[:3, 1], pose[:3, 2] = right, up, fwd
        pose[:3, 3] = cam + rng.normal(0, jitter, 3)

        # Project the box's world points into this camera to get a depth map.
        pts = box_cloud(centre, dims, yaw, n=20000, seed=100 + i)
        cam_pts = (pose[:3, :3].T @ (pts - pose[:3, 3]).T).T
        front = cam_pts[cam_pts[:, 2] > 0.2]
        u = (front[:, 0] * K[0, 0] / front[:, 2] + K[0, 2]).astype(int)
        v = (front[:, 1] * K[1, 1] / front[:, 2] + K[1, 2]).astype(int)
        ok = (u >= 0) & (u < 640) & (v >= 0) & (v < 480)
        u, v, z = u[ok], v[ok], front[ok, 2]

        depth = np.full((480, 640), 6.0)
        # z-buffer: nearest wins, which is what gives us the visible shell only.
        order = np.argsort(-z)
        depth[v[order], u[order]] = z[order]
        depths.append(depth)
        poses.append(pose)
        dets.append({"frame_idx": i, "label": label, "conf": conf,
                     "bbox": [u.min(), v.min(), u.max() + 1, v.max() + 1]})
    return dets, depths, poses, K


def test_multi_view_lift_recovers_a_chair():
    centre, dims, yaw = (1.0, 0.45, 0.5), (0.55, 0.9, 0.6), math.radians(25)
    dets, depths, poses, K = _synthetic_views(centre, dims, yaw, 6)
    objs = lift_boxes_to_3d(dets, depths, poses, K, min_votes=3)

    assert len(objs) == 1
    o = objs[0]
    assert o["id"] == "chair_01"
    assert o["position"] == pytest.approx(list(centre), abs=0.12)
    assert o["dimensions"] == pytest.approx(list(dims), rel=0.15)
    assert o["votes"] == 6


def test_single_view_dimensions_are_biased_small_and_merging_fixes_it():
    """The reason multi-view voting exists, asserted rather than assumed."""
    centre, dims, yaw = (0.0, 0.45, 0.0), (0.6, 0.9, 1.4), 0.0
    dets, depths, poses, K = _synthetic_views(centre, dims, yaw, 6)

    one = lift_boxes_to_3d(dets[:1], depths, poses, K, min_votes=1)[0]
    many = lift_boxes_to_3d(dets, depths, poses, K, min_votes=3)[0]

    err_one = abs(one["dimensions"][2] - dims[2])
    err_many = abs(many["dimensions"][2] - dims[2])
    assert err_many < err_one, "merging six views should beat one view"


def test_objects_seen_too_few_times_are_dropped():
    dets, depths, poses, K = _synthetic_views((0, 0.5, 0), (0.6, 1.0, 0.6), 0.0, 2)
    assert lift_boxes_to_3d(dets, depths, poses, K, min_votes=3) == []
    assert len(lift_boxes_to_3d(dets, depths, poses, K, min_votes=2)) == 1


def test_two_separate_chairs_do_not_merge_into_one():
    a = _synthetic_views((-1.2, 0.45, 0), (0.55, 0.9, 0.55), 0.0, 4, seed=1)
    b = _synthetic_views((1.2, 0.45, 0), (0.55, 0.9, 0.55), 0.0, 4, seed=2)

    dets = list(a[0]) + [{**d, "frame_idx": d["frame_idx"] + 4} for d in b[0]]
    objs = lift_boxes_to_3d(dets, a[1] + b[1], a[2] + b[2], a[3], min_votes=3)

    assert len(objs) == 2
    assert {o["id"] for o in objs} == {"chair_01", "chair_02"}
    xs = sorted(o["position"][0] for o in objs)
    assert xs[0] == pytest.approx(-1.2, abs=0.15)
    assert xs[1] == pytest.approx(1.2, abs=0.15)


def test_ids_are_ordered_by_confidence_and_match_the_frozen_pattern():
    import re
    low = _synthetic_views((-1.5, 0.45, 0), (0.55, 0.9, 0.55), 0.0, 4,
                           conf=0.4, seed=3)
    high = _synthetic_views((1.5, 0.45, 0), (0.55, 0.9, 0.55), 0.0, 4,
                            conf=0.95, seed=4)
    dets = list(low[0]) + [{**d, "frame_idx": d["frame_idx"] + 4} for d in high[0]]
    objs = lift_boxes_to_3d(dets, low[1] + high[1], low[2] + high[2], low[3],
                            min_votes=3)

    assert [o["id"] for o in objs] == ["chair_01", "chair_02"]
    assert objs[0]["position"][0] == pytest.approx(1.5, abs=0.2)   # the confident one
    for o in objs:
        assert re.fullmatch(r"^[a-z_]+_[0-9]{2}$", o["id"]), o["id"]


def test_iou3d_is_zero_for_disjoint_boxes_and_one_for_identical_ones():
    a = {"position": [0, 0.5, 0], "dimensions": [1, 1, 1], "rotation_y": 0.0}
    b = {"position": [5, 0.5, 0], "dimensions": [1, 1, 1], "rotation_y": 0.0}
    assert iou3d(a, b) == 0.0
    assert iou3d(a, a) == pytest.approx(1.0)


# ─────────────────────────── label sanitising ─────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("potted plant", "potted_plant"),
    ("Dining Table", "dining_table"),
    ("tv", "tv"),
    ("  sofa  ", "sofa"),
    ("chair-2", "chair"),
    ("!!!", "object"),
])
def test_labels_are_sanitised_to_the_frozen_id_pattern(raw, want):
    assert sanitise_label(raw) == want
