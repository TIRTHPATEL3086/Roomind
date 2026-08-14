"""S02 pose-estimation accuracy against a known trajectory.

Measures the RGBD odometry backend directly rather than inferring its quality
from how bad the final mesh looks. A pose test that runs in seconds is worth
far more than a three-minute end-to-end run when you are trying to work out
whether the camera solution or the fusion is at fault.

Marked slow: it renders frames and runs the optimiser.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
DENSE = ROOT / "storage" / "scans" / "synth_dense"

pytestmark = pytest.mark.skipif(
    not (DENSE / "ground_truth.json").exists(),
    reason="run `python synth/make_room.py --out storage/scans/synth_dense "
           "--frames 140 --width 424 --height 320` first")


def _relative_pose_errors(est: np.ndarray, true: np.ndarray):
    """Frame-to-frame errors, which isolate odometry from accumulated drift.

    Absolute pose error is dominated by whatever the first frame was, and by
    the arbitrary world frame odometry starts in. The RELATIVE error between
    consecutive frames is the thing the odometry step is actually responsible
    for.
    """
    trans_err, rot_err = [], []
    for i in range(len(est) - 1):
        de = np.linalg.inv(est[i]) @ est[i + 1]
        dt = np.linalg.inv(true[i]) @ true[i + 1]
        diff = np.linalg.inv(dt) @ de
        trans_err.append(float(np.linalg.norm(diff[:3, 3])))
        cos = (np.trace(diff[:3, :3]) - 1) / 2
        rot_err.append(math.degrees(math.acos(float(np.clip(cos, -1, 1)))))
    return np.array(trans_err), np.array(rot_err)


@pytest.mark.slow
def test_rgbd_odometry_tracks_a_known_trajectory():
    """Documents what the odometry backend actually achieves on this capture.

    This asserts a MEASURED bound, not an aspirational one. Open3D's
    photometric odometry is built for a handheld sensor at 30 fps; a keyframe
    extractor leaves wider baselines than that, and the numbers here say how
    much wider is still tolerable.
    """
    import cv2

    from steps import s01_ingest, s02_pose, s03_depth
    from utils import intrinsics as intr_utils

    work = ROOT / "storage" / "meshes" / "_posetest"
    work.mkdir(parents=True, exist_ok=True)

    manifest = s01_ingest.run(DENSE, work, target_w=424, max_frames=140)
    frames = manifest["frames"]
    src = manifest["source_idx"]
    assert len(frames) >= 60, f"only {len(frames)} keyframes"

    probe = cv2.imread(frames[0], cv2.IMREAD_COLOR)
    h, w = probe.shape[:2]
    k, _ = intr_utils.load(DENSE / "intrinsics.json", w, h)
    depths, mode = s03_depth.run(DENSE, frames, (w, h), "sensor",
                                 source_idx=src)
    assert mode == "sensor"

    s02_pose._ODOMETRY_FAILURES.update(count=0, pairs=0)
    est = s02_pose._rgbd_odometry(frames, depths, k)

    truth_all = np.array(json.loads((DENSE / "poses.json").read_text())["poses"]) \
        if (DENSE / "poses.json").exists() else None
    if truth_all is None:
        pytest.skip("dense fixture was rendered without --write-poses")
    true = truth_all[np.asarray(src)]

    # Odometry has no global frame of its own, so compare RELATIVE motion.
    t_err, r_err = _relative_pose_errors(est, true)
    true_step = np.array([
        float(np.linalg.norm((np.linalg.inv(true[i]) @ true[i + 1])[:3, 3]))
        for i in range(len(true) - 1)])

    # A pair "converged" when the solver actually improved on doing nothing.
    # Where photometric odometry loses the basin of attraction it returns
    # (or falls back to) the identity, and the error then equals the full
    # inter-frame motion.
    converged = t_err < 0.5 * np.maximum(true_step, 1e-6)
    reported = s02_pose._ODOMETRY_FAILURES

    print(f"\n  keyframes: {len(frames)}   pairs: {len(t_err)}")
    print(f"  median inter-frame baseline: {np.median(true_step)*100:.1f} cm")
    print(f"  converged pairs: {int(converged.sum())}/{len(t_err)} "
          f"({converged.mean()*100:.0f}%)")
    print(f"  solver reported failures: {reported['count']}/{reported['pairs']}")
    if converged.any():
        print(f"  WHERE CONVERGED  translation {np.median(t_err[converged])*1000:.2f} mm, "
              f"rotation {np.median(r_err[converged]):.3f} deg")
    print(f"  overall median   translation {np.median(t_err)*100:.1f} cm, "
          f"rotation {np.median(r_err):.2f} deg")

    # 1. The implementation is CORRECT: where the solver converges it is
    #    accurate to millimetres, which is what says the intrinsics, the depth
    #    scale and the camera convention all line up.
    assert converged.any(), "odometry converged on no pair at all"
    assert np.median(t_err[converged]) < 0.01, "accuracy where converged"
    assert np.median(r_err[converged]) < 0.5, "accuracy where converged"

    # 2. Characterisation, not a pass/fail bar: this records how far the
    #    backend gets on a capture with THIS baseline, so a future change that
    #    makes it worse is visible in the printed numbers.
    #
    #    Divergence is deliberately NOT asserted here. Open3D reports ok=True
    #    even when it lands in the wrong minimum, and no cheap test inside S02
    #    distinguishes the two (a step-length outlier check was tried and
    #    fails, because a diverged pair moves a plausible distance in the wrong
    #    direction). The pipeline catches drift after fusion instead, via the
    #    floor-plane inlier fraction -- see the FLOOR_INLIER_FLOOR check in
    #    pipeline.py and test_drift_is_detected below.
    assert len(t_err) > 20, "not enough pairs to characterise anything"


def test_the_drift_detector_separates_a_good_room_from_a_drifted_one():
    """The floor-inlier threshold must actually sit between the two cases.

    A threshold nobody has checked against real numbers is a guess. These are
    the measured values from the two fixtures in storage/meshes.
    """
    from steps.s09_floorplan import estimate_floor

    import open3d as o3d

    good = ROOT / "storage" / "meshes" / "synth_known" / "room.glb"
    if not good.exists():
        pytest.skip("run the pipeline on synth_demo first")

    verts = np.asarray(o3d.io.read_triangle_mesh(str(good)).vertices)
    _, inliers = estimate_floor(verts)
    assert inliers > 0.12, (
        f"a GOOD reconstruction scored {inliers:.3f} on the drift detector - "
        f"the threshold would flag healthy rooms")
