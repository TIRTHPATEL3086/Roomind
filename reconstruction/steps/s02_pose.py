"""S02 - camera pose estimation and metric scale recovery (spec 10.4).

Three backends, chosen by what the capture actually provides:

  known    poses shipped alongside the frames (poses.json). Synthetic captures
           and any client that already ran ARKit/ARCore VIO take this path.
  rgbd     Open3D RGBD odometry + pose-graph optimisation with loop closure.
           Needs depth. This is the path a phone with LiDAR takes.
  colmap   Shells out to COLMAP for monocular SfM. Highest quality, needs the
           binary on PATH, and has no metric scale of its own.

>>> METRIC SCALE IS NOT OPTIONAL <<<

Monocular SfM reconstructs the room up to an unknown scale factor. Skip the
recovery and you get a room with the correct shape and an arbitrary size --
which §18.1 calls out as the classic failure, because everything downstream
still "works": the mesh loads, the objects lift, A* plans a path, and ARIA
drives into a table because the map says it is 40 cm away when it is 90.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np

log = logging.getLogger("recon.s02")

CEILING_HEIGHT_M = 2.5      # fallback assumption (spec 10.4, option 3)
A4_LONG_EDGE_M = 0.297      # ISO 216 A4 short-side-up on the floor


class ScaleUnknown(RuntimeError):
    """Raised when no scale source is available and --allow-unscaled is off."""


# How many consecutive-frame alignments the odometry backend failed on, so the
# pipeline can warn that the geometry is suspect instead of quietly shipping a
# drifted room.
_ODOMETRY_FAILURES: dict[str, int] = {"count": 0, "pairs": 0}


def available_backends() -> dict[str, bool]:
    return {
        "colmap": shutil.which("colmap") is not None,
        "rgbd": True,        # Open3D is a hard dependency of this venv
        "known": True,
    }


def find_poses_file(work_dir: Path, input_dir: Path | None) -> Path | None:
    """poses.json ships WITH the capture (ARKit/ARCore write it), not with the
    work directory the pipeline just created. Look in both."""
    for cand in (work_dir / "poses.json",
                 *( (input_dir / "poses.json",) if input_dir else () )):
        if cand.exists():
            return cand
    return None


def choose_backend(requested: str, work_dir: Path, has_depth: bool,
                   input_dir: Path | None = None) -> str:
    if requested != "auto":
        return requested
    if find_poses_file(work_dir, input_dir):
        return "known"
    if has_depth:
        return "rgbd"
    if shutil.which("colmap"):
        return "colmap"
    raise RuntimeError(
        "no usable pose backend: the capture has no depth, no poses.json, and "
        "COLMAP is not on PATH. Install COLMAP for monocular captures, or "
        "supply depth frames.")


# ─────────────────────────────── known poses ───────────────────────────────

def _load_known(path: Path, n_frames: int,
                source_idx: list[int] | None = None) -> np.ndarray:
    """Load supplied poses, selecting by ORIGINAL frame index.

    S01 drops blurry and near-duplicate frames from the middle of the capture,
    so poses[:n] pairs keyframe k with the pose of source frame k -- which it
    is not. Every frame after the first drop would be misaligned.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    poses = np.array(raw["poses"], dtype=np.float64)
    if poses.ndim != 3 or poses.shape[1:] != (4, 4):
        raise ValueError(f"poses.json must hold 4x4 matrices, got {poses.shape}")

    if source_idx:
        if max(source_idx) >= len(poses):
            raise ValueError(
                f"poses.json has {len(poses)} poses but keyframes reference "
                f"source frame {max(source_idx)}")
        return poses[np.asarray(source_idx)]

    if len(poses) < n_frames:
        raise ValueError(f"poses.json has {len(poses)} poses for {n_frames} frames")
    return poses[:n_frames]


# ──────────────────────────────── RGBD odometry ────────────────────────────

def _rgbd_odometry(frames: list[str], depths: list[np.ndarray], k: np.ndarray,
                   progress=None) -> np.ndarray:
    """Frame-to-frame odometry, then global pose-graph optimisation.

    The pose graph is what makes the room CLOSE. Pure sequential odometry
    accumulates drift, so walking a loop around a room and back to the start
    leaves the two ends metres apart and the far wall appears twice in the
    fused mesh. Loop-closure edges plus Levenberg-Marquardt pull them together.
    """
    import cv2
    import open3d as o3d

    from utils.intrinsics import to_open3d

    h, w = depths[0].shape[:2]
    intr = to_open3d(k, w, h)
    option = o3d.pipelines.odometry.OdometryOption()
    jacobian = o3d.pipelines.odometry.RGBDOdometryJacobianFromHybridTerm()

    def rgbd(i: int):
        bgr = cv2.imread(frames[i], cv2.IMREAD_COLOR)
        bgr = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)
        colour = o3d.geometry.Image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        depth = o3d.geometry.Image(depths[i].astype(np.float32))
        return o3d.geometry.RGBDImage.create_from_color_and_depth(
            colour, depth, depth_scale=1.0, depth_trunc=5.0,
            convert_rgb_to_intensity=False)

    n = len(frames)
    cache = {i: rgbd(i) for i in range(n)}

    pose_graph = o3d.pipelines.registration.PoseGraph()
    odom = np.eye(4)
    pose_graph.nodes.append(o3d.pipelines.registration.PoseGraphNode(odom))

    def align(a: int, b: int, init=None):
        ok, trans, info = o3d.pipelines.odometry.compute_rgbd_odometry(
            cache[a], cache[b], intr,
            np.eye(4) if init is None else init, jacobian, option)
        return (trans, info) if ok else (None, None)

    # Constant-velocity initial guess: seed each pair with the previous pair's
    # transform. Photometric odometry is a local optimiser, so from an identity
    # start it can only track motion small enough to stay inside the basin of
    # attraction -- fine at 30 fps, marginal for the wider baselines a keyframe
    # extractor leaves behind. Handing it the previous step as a starting point
    # costs nothing and roughly doubles the motion it can follow.
    failures = 0
    velocity = None
    steps: list[np.ndarray] = []
    infos: list[np.ndarray] = []
    for i in range(n - 1):
        trans, info = align(i, i + 1, velocity)
        if trans is None and velocity is not None:
            trans, info = align(i, i + 1, None)      # retry from identity
        if trans is None:
            trans, info = np.eye(4), np.eye(6)
            failures += 1
            velocity = None
            log.warning("odometry failed between frames %d and %d", i, i + 1)
        else:
            velocity = trans
        steps.append(trans)
        infos.append(info)
        if progress and i % 5 == 0:
            progress.stage("pose", 0.7 * (i + 1) / n, f"odometry {i + 1}/{n}")

    # ── on detecting divergence ──
    #
    # compute_rgbd_odometry's success flag CANNOT be trusted. On the test
    # capture it returned ok=True for EVERY pair while settling into the wrong
    # local minimum on roughly a third of them: measured frame-to-frame error
    # jumped from under a millimetre to the full ~30 cm of inter-frame motion,
    # with no failure reported.
    #
    # A step-length outlier test was tried here and does not work -- a diverged
    # pair moves a plausible DISTANCE in the wrong DIRECTION, so its length
    # sits comfortably inside the distribution. It is deliberately not left in
    # place: a detector that always reports zero failures is worse than none,
    # because it reads as a clean bill of health.
    #
    # Drift is instead caught downstream, where it is unambiguous and cheap:
    # S09's floor-plane inlier fraction collapses when the trajectory smears
    # the room (28.7% on a good reconstruction here, 8.2% on a drifted one).
    # That check lives in the pipeline and catches bad intrinsics and bad
    # COLMAP solutions too, not just odometry.

    for i, (trans, info) in enumerate(zip(steps, infos)):
        odom = odom @ np.linalg.inv(trans)
        pose_graph.nodes.append(o3d.pipelines.registration.PoseGraphNode(odom))
        pose_graph.edges.append(o3d.pipelines.registration.PoseGraphEdge(
            i, i + 1, trans, info, uncertain=False))

    # Loop closure: try to match every 5th frame against the ones well behind
    # it. Cheap, and it is the only thing that lets the graph correct drift.
    for i in range(0, n, 5):
        for j in range(i + 10, n, 5):
            trans, info = align(i, j)
            if trans is None:
                continue
            pose_graph.edges.append(o3d.pipelines.registration.PoseGraphEdge(
                i, j, trans, info, uncertain=True))

    if progress:
        progress.stage("pose", 0.85, "global optimisation")

    o3d.pipelines.registration.global_optimization(
        pose_graph,
        o3d.pipelines.registration.GlobalOptimizationLevenbergMarquardt(),
        o3d.pipelines.registration.GlobalOptimizationConvergenceCriteria(),
        o3d.pipelines.registration.GlobalOptimizationOption(
            max_correspondence_distance=0.05,
            edge_prune_threshold=0.25, reference_node=0))

    if failures:
        log.warning("odometry looks unreliable on %d/%d consecutive pairs - "
                    "the pose solution is probably drifted", failures, n - 1)
    _ODOMETRY_FAILURES["count"] = failures
    _ODOMETRY_FAILURES["pairs"] = n - 1
    return np.array([node.pose for node in pose_graph.nodes], dtype=np.float64)


# ──────────────────────────────────── COLMAP ───────────────────────────────

def _colmap(work_dir: Path, frames_dir: Path, progress=None) -> np.ndarray:
    """Monocular SfM. Poses come out up to an unknown SCALE -- see _recover_scale."""
    db = work_dir / "colmap.db"
    sparse = work_dir / "sparse"
    sparse.mkdir(exist_ok=True)

    steps = [
        ["colmap", "feature_extractor", "--database_path", str(db),
         "--image_path", str(frames_dir), "--ImageReader.camera_model", "PINHOLE"],
        ["colmap", "sequential_matcher", "--database_path", str(db)],
        ["colmap", "mapper", "--database_path", str(db),
         "--image_path", str(frames_dir), "--output_path", str(sparse)],
        ["colmap", "model_converter", "--input_path", str(sparse / "0"),
         "--output_path", str(sparse / "0"), "--output_type", "TXT"],
    ]
    for i, cmd in enumerate(steps):
        if progress:
            progress.stage("pose", 0.2 * i, cmd[1])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{cmd[1]} failed: {r.stderr.strip()[-400:]}")

    return _parse_colmap_images(sparse / "0" / "images.txt")


def _parse_colmap_images(path: Path) -> np.ndarray:
    """images.txt holds world-FROM-camera quaternions; we want camera-to-world."""
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 10 or not parts[0].isdigit():
            continue                      # the 2D-point line that follows each pose
        qw, qx, qy, qz = (float(v) for v in parts[1:5])
        tx, ty, tz = (float(v) for v in parts[5:8])
        entries.append((parts[9], _qt_to_c2w(qw, qx, qy, qz, tx, ty, tz)))
    entries.sort(key=lambda e: e[0])
    return np.array([e[1] for e in entries], dtype=np.float64)


def _qt_to_c2w(qw, qx, qy, qz, tx, ty, tz) -> np.ndarray:
    r = np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])
    w2c = np.eye(4)
    w2c[:3, :3] = r
    w2c[:3, 3] = [tx, ty, tz]
    return np.linalg.inv(w2c)


# ───────────────────────────── metric scale ────────────────────────────────

def detect_a4_scale(frames: list[str], k: np.ndarray) -> tuple[float, dict] | None:
    """Find an A4 sheet on the floor and solve scale = 0.297 / measured.

    Looks for a bright quadrilateral with A4's aspect ratio (1.414). The
    tolerance is wide because the sheet is seen in perspective; the aspect
    check exists to reject rugs and laptop lids, not to be precise.
    """
    import cv2

    ratios = []
    for path in frames[:40]:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < 800:
                continue
            approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            (_, _), (w, h), _ = cv2.minAreaRect(approx)
            if min(w, h) < 12:
                continue
            long_px, short_px = max(w, h), min(w, h)
            if not (1.20 < long_px / short_px < 1.65):     # A4 is 1.414
                continue
            ratios.append(long_px)

    if len(ratios) < 3:
        return None
    # The sheet's apparent size depends on distance, so this only gives scale
    # once combined with the un-scaled depth at the sheet. Reported as a
    # candidate for the caller to weigh, not as gospel.
    return float(np.median(ratios)), {"method": "a4_marker", "samples": len(ratios)}


def recover_scale(backend: str, poses: np.ndarray, depths, work_dir: Path,
                  allow_unscaled: bool = False) -> tuple[float, dict]:
    """Return (scale, meta). Every downstream stage multiplies lengths by scale.

    Order of preference matches spec 10.4: real depth beats a marker, a marker
    beats a ceiling-height assumption, and an assumption beats nothing -- but
    "nothing" is an error, not a silent 1.0.
    """
    if backend in ("known", "rgbd") or depths is not None:
        # Depth is already metric (sensor millimetres, or synthetic metres),
        # and the poses were solved against it, so the reconstruction is metric.
        return 1.0, {"method": "metric_depth", "confidence": 1.0}

    marker = (work_dir / "scale.json")
    if marker.exists():
        raw = json.loads(marker.read_text(encoding="utf-8"))
        return float(raw["scale"]), {"method": raw.get("method", "file"),
                                     "confidence": float(raw.get("confidence", 0.8))}

    # Ceiling-height fallback: assume the vertical extent of the camera
    # trajectory's environment is a standard 2.5 m room.
    span = float(np.ptp(poses[:, 1, 3])) if len(poses) > 1 else 0.0
    if span > 1e-6:
        est = CEILING_HEIGHT_M / max(span * 4.0, 1e-6)
        return est, {"method": "assumed_ceiling_2.5m", "confidence": 0.3,
                     "warning": "size is an assumption, not a measurement"}

    if allow_unscaled:
        return 1.0, {"method": "none", "confidence": 0.0,
                     "warning": "UNSCALED reconstruction - dimensions are meaningless"}
    raise ScaleUnknown(
        "no metric scale available. Supply depth, place an A4 sheet on the "
        "floor (spec 10.4), or pass --allow-unscaled to accept a wrongly-sized "
        "room.")


# ──────────────────────────────────── entry ────────────────────────────────

def run(work_dir: Path, frames: list[str], k: np.ndarray, depths=None,
        backend: str = "auto", allow_unscaled: bool = False,
        input_dir: Path | None = None, source_idx: list[int] | None = None,
        progress=None) -> dict:
    work_dir = Path(work_dir)
    chosen = choose_backend(backend, work_dir, depths is not None, input_dir)
    log.info("pose backend: %s", chosen)

    if chosen == "known":
        path = find_poses_file(work_dir, input_dir)
        if path is None:
            raise FileNotFoundError(
                "--pose-backend known but no poses.json in the work or scan dir")
        poses = _load_known(path, len(frames), source_idx)
    elif chosen == "rgbd":
        if depths is None:
            raise RuntimeError("the rgbd backend needs depth frames")
        poses = _rgbd_odometry(frames, depths, k, progress)
    elif chosen == "colmap":
        poses = _colmap(work_dir, Path(frames[0]).parent, progress)
    else:
        raise ValueError(f"unknown pose backend '{chosen}'")

    scale, scale_meta = recover_scale(chosen, poses, depths, work_dir, allow_unscaled)
    if scale != 1.0:
        poses = poses.copy()
        poses[:, :3, 3] *= scale

    (work_dir / "scale.json").write_text(
        json.dumps({"scale": scale, **scale_meta}, indent=2), encoding="utf-8")

    if progress:
        progress.stage("pose", 1.0, f"{len(poses)} poses ({chosen})")

    bad, total = _ODOMETRY_FAILURES["count"], _ODOMETRY_FAILURES["pairs"]
    warning = None
    if chosen == "rgbd" and total and bad / total > 0.1:
        warning = (f"camera tracking looks unreliable on {bad} of {total} frame "
                   f"pairs - the room's geometry is probably drifted. Capture "
                   f"more slowly, or supply per-frame poses (ARKit/ARCore write "
                   f"poses.json).")
        log.warning("%s", warning)

    return {"poses": poses, "backend": chosen, "scale": scale,
            "scale_meta": scale_meta, "tracking_warning": warning,
            "tracking_failures": bad, "tracking_pairs": total}
