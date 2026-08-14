"""RoomMind 3D reconstruction pipeline — the CLI contract from spec 10.1.

    python reconstruction/pipeline.py \
      --input storage/scans/<scan_id>/ \
      --out   storage/meshes/<room_id>/ \
      --room-id <room_id> \
      --intrinsics storage/scans/<scan_id>/intrinsics.json \
      --depth-mode auto --quality medium \
      --progress-url http://localhost:8000/api/v1/scan/<scan_id>/progress

Emits room.glb, room.json, navmesh.npy and preview.png into --out.

Runs in its own venv (reconstruction/.venv) and talks to the API only over
stdout JSONL and the optional progress URL. The API process must never import
Open3D or torch — same subprocess boundary as genai3d, for the same reason.

Exit codes
    0  success
    2  bad usage / missing input
    3  completed, but with a degraded path (no metric scale, geometric
       detector, or an over-budget mesh). The room is usable; the caller
       should surface the warnings.
    4  pipeline failure
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from steps import (  # noqa: E402
    s01_ingest, s02_pose, s03_depth, s04_fuse, s06_texture,
    s07_detect, s08_lift3d, s09_floorplan, s10_scenegraph,
)
from utils import intrinsics as intr_utils  # noqa: E402
from utils.progress import Progress  # noqa: E402

SCHEMA = ROOT.parent / "contracts" / "scene_graph.schema.json"
log = logging.getLogger("recon")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="frames dir or a video file")
    p.add_argument("--out", required=True)
    p.add_argument("--room-id", required=True)
    p.add_argument("--scan-id", default=None)
    p.add_argument("--name", default=None, help="human-readable room name")
    p.add_argument("--intrinsics", default=None)
    p.add_argument("--depth-mode", default="auto",
                   choices=["auto", "sensor", "mono", "none"])
    p.add_argument("--pose-backend", default="auto",
                   choices=["auto", "known", "rgbd", "colmap"])
    p.add_argument("--detector", default="auto",
                   choices=["auto", "yolo", "geometric"])
    p.add_argument("--weights", default=None, help="YOLO weights (Phase 6)")
    p.add_argument("--quality", default="medium", choices=["fast", "medium", "high"])
    p.add_argument("--max-frames", type=int, default=200)
    p.add_argument("--target-width", type=int, default=960,
                   help="keyframe width (spec 10.3 uses 960; lower is much "
                        "faster and avoids upscaling a low-res capture)")
    p.add_argument("--min-votes", type=int, default=3,
                   help="multi-view votes required to keep an object")
    p.add_argument("--mesh-max-mb", type=float, default=25.0)
    p.add_argument("--progress-url", default=None)
    p.add_argument("--allow-unscaled", action="store_true",
                   help="accept a reconstruction with no metric scale")
    p.add_argument("--debug", action="store_true", help="keep per-stage artefacts")
    p.add_argument("--quiet", action="store_true", help="no stdout JSONL")
    return p.parse_args(argv)


def run(a) -> int:
    t0 = time.time()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)

    scan_id = a.scan_id or a.room_id
    prog = Progress(scan_id, a.progress_url, quiet=a.quiet)
    warnings: list[str] = []

    # ── S01 ingest ──
    prog.stage("ingest", 0.0, "extracting keyframes")
    manifest = s01_ingest.run(a.input, work, target_w=a.target_width,
                              max_frames=a.max_frames, progress=prog)
    frames = manifest["frames"]
    if len(frames) < 8:
        raise RuntimeError(
            f"only {len(frames)} usable keyframes (need 8+). "
            f"{manifest['rejected_blur']} were rejected as blurry.")
    if manifest.get("warning"):
        warnings.append(manifest["warning"])
    prog.stage("ingest", 1.0, f"{len(frames)} keyframes")

    import cv2
    probe = cv2.imread(frames[0], cv2.IMREAD_COLOR)
    height, width = probe.shape[:2]
    k, k_meta = intr_utils.load(a.intrinsics, width, height)
    if k_meta["source"] != "file":
        warnings.append("camera intrinsics were ASSUMED (60 deg fov) - "
                        "sizes may be systematically off; supply intrinsics.json")

    # ── S03 depth (before pose: the pose backend choice depends on it) ──
    prog.stage("depth", 0.0, "resolving depth")
    source_idx = manifest.get("source_idx")
    depths, depth_mode = (None, "none") if a.depth_mode == "none" else s03_depth.run(
        Path(a.input), frames, (width, height), a.depth_mode,
        k_meta.get("depth_scale", 1000.0), source_idx, prog)
    if depth_mode == "none":
        warnings.append("no depth available - fusion and lifting are disabled")
    prog.stage("depth", 1.0, f"depth: {depth_mode}")

    # ── S02 pose + metric scale ──
    prog.stage("pose", 0.0, "estimating camera poses")
    pose_res = s02_pose.run(work, frames, k, depths, a.pose_backend,
                            a.allow_unscaled, Path(a.input), source_idx, prog)
    poses = pose_res["poses"]
    if pose_res["scale_meta"].get("warning"):
        warnings.append(pose_res["scale_meta"]["warning"])
    if pose_res.get("tracking_warning"):
        warnings.append(pose_res["tracking_warning"])

    if depths is None:
        raise RuntimeError(
            "cannot fuse a mesh without depth. Supply depth frames, or install "
            "MiDaS for the monocular path (--depth-mode mono).")

    # ── S04-S05 fuse + mesh ──
    prog.stage("fuse", 0.0, "TSDF fusion")
    volume = s04_fuse.fuse(frames, depths, poses, k, a.quality, prog)
    prog.stage("mesh", 0.0, "extracting mesh")
    mesh = s04_fuse.extract_mesh(volume, prog)
    mesh = s04_fuse.boost_saturation(mesh)
    if len(mesh.triangles) == 0:
        raise RuntimeError("fusion produced an empty mesh - check depth units "
                           "and that the poses are camera-to-world")

    # ── gravity alignment ──
    # Must happen before anything reads a height. Pose estimation leaves the
    # reconstruction in the first camera's frame, so "up" is wherever the phone
    # was pointing at frame 0 (spec 8.1 requires Y-up).
    prog.stage("floorplan", 0.0, "aligning to gravity")
    mesh, poses, align_meta = s09_floorplan.align_to_gravity(mesh, poses)
    if align_meta.get("applied") and align_meta.get("plane_inliers", 0) < 0.05:
        warnings.append("floor plane is weak - the room may be tilted; "
                        "heights and the navmesh slice are unreliable")

    # ── S09 floorplan (before detection: the geometric detector needs floor_y
    #     to know what is standing on the floor) ──
    prog.stage("floorplan", 0.2, "floor plane and occupancy")
    floor = s09_floorplan.run(mesh, prog)
    floor["alignment"] = align_meta

    # ── the drift detector ──
    #
    # A reconstruction whose camera solution drifted smears every surface, and
    # the floor -- the single largest flat thing in any room -- stops being
    # flat. Measured on this project's fixtures: 28.7% of vertices lie in the
    # floor plane for a good reconstruction, 8.2% for a drifted one. Nothing
    # else this cheap separates the two so clearly, and it catches wrong
    # intrinsics and a bad COLMAP solve as well as bad odometry.
    #
    # It matters because the failure is otherwise SILENT: the mesh loads, the
    # objects lift, A* plans a path, and the robot drives into a table that the
    # map put somewhere else.
    FLOOR_INLIER_FLOOR = 0.12
    if floor["floor_inliers"] < FLOOR_INLIER_FLOOR:
        warnings.append(
            f"the floor plane holds only {floor['floor_inliers'] * 100:.0f}% of "
            f"the geometry (expected 25%+), which means the camera solution "
            f"drifted and this room's dimensions should not be trusted")

    # ── S06 texture / export ──
    prog.stage("texture", 0.0, "exporting glb")
    mesh_info = s06_texture.export_glb(mesh, out_dir / "room.glb",
                                       a.mesh_max_mb, True, prog)
    if mesh_info["over_budget"]:
        warnings.append(f"mesh is {mesh_info['size_mb']} MB, over the "
                        f"{a.mesh_max_mb} MB budget")
    s06_texture.render_preview(mesh, out_dir / "preview.png")

    # ── S07 detect ──
    prog.stage("detect", 0.0, "detecting objects")
    dets, detector = s07_detect.run(frames, depths, poses, k, floor["floor_y"],
                                    a.detector,
                                    Path(a.weights) if a.weights else None,
                                    min_votes=a.min_votes,
                                    bounds_min=floor["bounds_min"],
                                    bounds_max=floor["bounds_max"],
                                    mesh_points=np.asarray(mesh.vertices),
                                    progress=prog)
    if detector == "geometric":
        warnings.append("no detector weights - labels were guessed from object "
                        "SIZE, not recognised")

    # ── S08 lift ──
    prog.stage("lift3d", 0.0, f"lifting {len(dets)} detections")
    rgbs = [cv2.cvtColor(cv2.imread(f, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            for f in frames]
    objects = s08_lift3d.lift_boxes_to_3d(dets, depths, poses, k,
                                          min_votes=a.min_votes, rgbs=rgbs)
    prog.stage("lift3d", 1.0, f"{len(objects)} objects merged")

    # ── S10 scene graph ──
    prog.stage("scenegraph", 0.0, "writing room.json")
    scan_meta = {
        "scan_id": scan_id,
        "frames_used": len(frames),
        "frames_seen": manifest["seen"],
        "pose_backend": pose_res["backend"],
        "depth_mode": depth_mode,
        "detector": detector,
        "quality": a.quality,
        "scale": pose_res["scale"],
        "scale_method": pose_res["scale_meta"].get("method"),
        "intrinsics_source": k_meta["source"],
        "warnings": warnings,
    }
    result = s10_scenegraph.run(a.room_id, out_dir, objects, floor, mesh_info,
                                scan_meta, SCHEMA, detector, a.name, prog)

    if not a.debug:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    elapsed = time.time() - t0
    prog.done(room_id=a.room_id, objects=result["kept"],
              tri_count=mesh_info["tri_count"],
              mesh_mb=mesh_info["size_mb"], elapsed_s=round(elapsed, 1),
              warnings=warnings)

    degraded = bool(warnings) or detector == "geometric"
    log.info("reconstruction finished in %.1fs: %d objects, %d triangles",
             elapsed, result["kept"], mesh_info["tri_count"])
    return 3 if degraded else 0


def main(argv=None) -> int:
    a = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if a.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    try:
        return run(a)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"stage": "failed", "error": str(e)}), flush=True)
        log.error("%s", e)
        return 2
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"stage": "failed", "error": str(e)}), flush=True)
        log.error("pipeline failed: %s", e)
        log.debug("%s", traceback.format_exc())
        return 4


if __name__ == "__main__":
    sys.exit(main())
