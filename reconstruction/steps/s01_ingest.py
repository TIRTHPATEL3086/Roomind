"""S01 - ingest: extract sharp, well-spaced keyframes (spec 10.3).

The blur gate is the single highest-value filter in the pipeline. Motion blur
destroys feature matching, and one blurry frame in a sequential matcher does not
just fail itself -- it breaks the chain, and the pose graph splits into two
components that never register. Rejecting frames is cheap; a failed
reconstruction is three minutes wasted.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("recon.s01")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def resolve_frames_dir(input_path: Path) -> Path:
    """Accept either a directory of stills or a scan directory containing one.

    The 10.1 contract passes --input storage/scans/<scan_id>/, but that
    directory holds frames/, depth/ and intrinsics.json -- the images are one
    level down. Looking only at the top level finds zero frames and fails with
    "0 usable keyframes", which reads like a blur problem rather than a path
    problem.
    """
    if not input_path.is_dir():
        return input_path
    if any(p.suffix.lower() in IMAGE_SUFFIXES for p in input_path.iterdir()):
        return input_path
    nested = input_path / "frames"
    if nested.is_dir():
        return nested
    # A single video sitting in the scan directory is also a valid capture.
    videos = [p for p in input_path.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES]
    return videos[0] if len(videos) == 1 else input_path


def _iter_frames(input_path: Path):
    """Yield BGR frames from a video file or a directory of stills."""
    input_path = resolve_frames_dir(input_path)
    if input_path.is_dir():
        files = sorted(p for p in input_path.iterdir()
                       if p.suffix.lower() in IMAGE_SUFFIXES)
        for p in files:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is not None:
                yield img
        return

    cap = cv2.VideoCapture(str(input_path))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


def _blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian. Higher is sharper."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def run(input_path, work_dir, target_w: int = 960, blur_thresh: float = 60.0,
        max_frames: int = 200, min_diff: float = 6.0, progress=None) -> dict:
    """Extract keyframes into work_dir/frames/ and return a manifest.

    Returns {"frames": [...], "kept": n, "seen": n, "rejected_blur": n, ...}
    so S02 can warn when it is about to run on too little data.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"scan input not found: {input_path}")

    out = Path(work_dir) / "frames"
    out.mkdir(parents=True, exist_ok=True)

    kept: list[str] = []
    # Which SOURCE frame each keyframe came from. Anything supplied per-frame
    # alongside the capture -- ARKit poses, sensor depth, IMU -- is indexed by
    # the original frame number, and this step drops frames from the middle of
    # the sequence. Without this mapping, frame 12's pose gets applied to
    # frame 14's image and every object lands somewhere plausible but wrong.
    source_idx: list[int] = []
    prev_gray = None
    seen = rejected_blur = rejected_dup = 0
    blur_scores: list[float] = []

    for img in _iter_frames(input_path):
        src = seen
        seen += 1
        h, w = img.shape[:2]
        if w != target_w:
            img = cv2.resize(img, (target_w, int(round(h * target_w / w))),
                             interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        score = _blur_score(gray)
        blur_scores.append(score)
        if score < blur_thresh:
            rejected_blur += 1
            continue

        # Near-duplicate rejection. Standing still for five seconds should not
        # produce 150 keyframes: they add fusion time and contribute no new
        # geometry, and a degenerate all-identical pair makes SfM ill-conditioned.
        if prev_gray is not None and float(cv2.absdiff(gray, prev_gray).mean()) < min_diff:
            rejected_dup += 1
            continue

        prev_gray = gray
        p = out / f"{len(kept):05d}.jpg"
        cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        kept.append(str(p))
        source_idx.append(src)

        if progress and len(kept) % 10 == 0:
            progress.stage("ingest", min(0.95, len(kept) / max_frames),
                           f"{len(kept)} keyframes")
        if len(kept) >= max_frames:
            break

    manifest = {
        "frames": kept,
        "source_idx": source_idx,
        "kept": len(kept),
        "seen": seen,
        "rejected_blur": rejected_blur,
        "rejected_duplicate": rejected_dup,
        "blur_median": float(np.median(blur_scores)) if blur_scores else 0.0,
        "blur_threshold": blur_thresh,
        "width": target_w,
    }

    # A capture that loses most of its frames to blur is a capture that will
    # produce a bad room. Say so loudly here rather than let S02 fail obscurely.
    if seen and rejected_blur / seen > 0.6:
        manifest["warning"] = (
            f"{rejected_blur}/{seen} frames rejected as blurry - "
            "the capture was probably moved too fast")
        log.warning(manifest["warning"])

    (Path(work_dir) / "frames.json").write_text(json.dumps(manifest, indent=2),
                                                encoding="utf-8")
    return manifest
