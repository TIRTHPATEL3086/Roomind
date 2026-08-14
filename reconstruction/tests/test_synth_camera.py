"""Camera-convention tests for the synthetic harness.

These exist because a wrong cross-product order in look_at produced a matrix
that was still a perfectly valid rotation -- so nothing raised, nothing looked
obviously broken in the logs, and the only symptom was that gravity estimation
decided the room was upside down. Conventions need assertions, not comments.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from synth.make_room import DEFAULT_ROOM, build_scene, look_at, orbit_trajectory, render


def test_look_at_is_a_proper_rotation():
    pose = look_at(np.array([1.0, 1.5, -2.0]), np.array([0.0, 0.5, 1.0]))
    r = pose[:3, :3]
    assert np.linalg.det(r) == pytest.approx(1.0, abs=1e-9), "must not mirror"
    assert (r.T @ r) == pytest.approx(np.eye(3), abs=1e-9), "must be orthonormal"


def test_camera_axes_for_a_camera_looking_along_plus_z():
    """The case worked through in look_at's docstring."""
    pose = look_at(np.zeros(3), np.array([0.0, 0.0, 1.0]))
    right, down, fwd = pose[:3, 0], pose[:3, 1], pose[:3, 2]
    assert fwd == pytest.approx([0, 0, 1], abs=1e-9)
    assert right == pytest.approx([-1, 0, 0], abs=1e-9)
    assert down == pytest.approx([0, -1, 0], abs=1e-9)
    # right x down == fwd is what makes it right-handed.
    assert np.cross(right, down) == pytest.approx(fwd, abs=1e-9)


def test_camera_y_axis_points_downward_for_every_orbit_pose():
    """S09 estimates gravity from this column. If it points up, the room flips."""
    for pose in orbit_trajectory(DEFAULT_ROOM, 12):
        assert pose[1, 1] < 0, "camera y axis must have a downward world component"


def test_the_floor_renders_below_the_ceiling():
    """The end-to-end orientation check: row 0 is the TOP of the image."""
    prims = build_scene(DEFAULT_ROOM)
    # Stand in the middle of the room, look horizontally at the far wall.
    pose = look_at(np.array([0.0, 1.3, 1.5]), np.array([0.0, 1.3, -1.9]))
    w, h = 160, 120
    f = w / (2 * math.tan(math.radians(62) / 2))
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])

    _, depth = render(prims, pose, k, w, h)

    # Back-project the centre column and check world height falls as the row
    # index rises -- i.e. looking further down the image looks further down.
    rows = np.array([10, h // 2, h - 10])
    d = depth[rows, w // 2]
    assert (d > 0).all(), "centre column should hit geometry at every row"
    cam = np.stack([np.zeros(3), (rows - k[1, 2]) * d / k[1, 1], d], axis=1)
    world_y = (pose[:3, :3] @ cam.T).T[:, 1] + pose[1, 3]
    assert world_y[0] > world_y[1] > world_y[2], (
        f"image rows must run top-to-bottom, got world heights {world_y}")


def test_render_produces_depth_in_a_plausible_range():
    prims = build_scene(DEFAULT_ROOM)
    pose = look_at(np.array([1.8, 1.4, 1.4]), np.array([-1.0, 0.5, -1.2]))
    w, h = 160, 120
    f = w / (2 * math.tan(math.radians(62) / 2))
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])

    rgb, depth = render(prims, pose, k, w, h)
    hit = depth[depth > 0]
    assert len(hit) > 0.95 * depth.size, "an interior view should hit geometry"
    # Nothing can be further away than the room's diagonal.
    assert hit.max() < 8.0
    assert hit.min() > 0.15
    assert rgb.shape == (h, w, 3)
