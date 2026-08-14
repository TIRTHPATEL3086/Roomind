"""S03 - metric depth per keyframe (spec 10.5).

Two paths:

  sensor  the client shipped depth PNGs (uint16 millimetres). Already metric.
  mono    MiDaS gives INVERSE RELATIVE depth. It is not metres and it is not
          even linear in metres, so it has to be aligned against something
          metric before anything downstream can use it.

The alignment is the whole job on the mono path. MiDaS returns disparity d;
metric depth is recovered as 1 / (a*d + b), with a and b solved by least
squares against sparse SfM depths. Treating the raw MiDaS output as metres --
the tempting one-liner -- produces a room shaped roughly right and sized
completely wrong.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("recon.s03")

DEPTH_SUFFIXES = (".png", ".tiff", ".tif", ".npy")


def find_depth_dir(input_path: Path) -> Path | None:
    """A sibling or child 'depth' directory is the convention clients follow."""
    for cand in (input_path / "depth", input_path.parent / "depth"):
        if cand.is_dir() and any(p.suffix.lower() in DEPTH_SUFFIXES
                                 for p in cand.iterdir()):
            return cand
    return None


def load_sensor_depth(depth_dir: Path, n: int, size: tuple[int, int],
                      depth_scale: float = 1000.0,
                      source_idx: list[int] | None = None) -> list[np.ndarray] | None:
    """Load uint16 millimetre depth maps and convert to float32 metres.

    source_idx maps keyframe -> ORIGINAL frame number. S01 drops blurry and
    duplicate frames from the middle of the sequence, so taking the first n
    depth files pairs keyframe 12 with the depth of source frame 12 when it
    actually came from source frame 14 -- and every point in that frame
    back-projects to the wrong place.
    """
    files = sorted(p for p in depth_dir.iterdir()
                   if p.suffix.lower() in DEPTH_SUFFIXES)
    if source_idx:
        if max(source_idx) >= len(files):
            log.warning("depth sequence is shorter than the frame sequence "
                        "(%d maps, need index %d) - ignoring sensor depth",
                        len(files), max(source_idx))
            return None
        chosen = [files[i] for i in source_idx]
    else:
        if len(files) < n:
            log.warning("only %d depth maps for %d frames - ignoring sensor depth",
                        len(files), n)
            return None
        chosen = files[:n]

    w, h = size
    out = []
    for p in chosen:
        if p.suffix.lower() == ".npy":
            d = np.load(p).astype(np.float32)
        else:
            d = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if d is None:
                return None
            d = d.astype(np.float32)
            if d.dtype != np.float32 or d.max() > 100:   # millimetre integers
                d = d / depth_scale
        if d.shape[:2] != (h, w):
            # INTER_NEAREST, never INTER_LINEAR: interpolating across a depth
            # discontinuity invents surfaces halfway between the foreground
            # and the wall behind it.
            d = cv2.resize(d, (w, h), interpolation=cv2.INTER_NEAREST)
        out.append(d)
    return out


# ─────────────────────────────────── mono ──────────────────────────────────

def _load_midas():
    import torch
    model = torch.hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
    transforms = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
    model.eval()
    return model, transforms.small_transform


def estimate_mono_depth(frames: list[str], sparse_depths=None,
                        progress=None) -> list[np.ndarray]:
    """MiDaS disparity aligned to metric depth via sparse SfM points."""
    import torch

    model, transform = _load_midas()
    out = []
    for i, path in enumerate(frames):
        bgr = cv2.imread(path, cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        with torch.no_grad():
            pred = model(transform(rgb))
            pred = torch.nn.functional.interpolate(
                pred.unsqueeze(1), size=rgb.shape[:2],
                mode="bicubic", align_corners=False).squeeze()
        disparity = pred.cpu().numpy()

        sparse = sparse_depths[i] if sparse_depths else None
        out.append(align_disparity_to_metric(disparity, sparse))
        if progress and i % 5 == 0:
            progress.stage("depth", i / len(frames), f"MiDaS {i}/{len(frames)}")
    return out


def align_disparity_to_metric(disparity: np.ndarray,
                              sparse: dict | None) -> np.ndarray:
    """Solve depth = 1 / (a * disparity + b) against known sparse depths.

    Without sparse points there is nothing to align to, so the result is
    normalised into a plausible 0.4-5 m band and flagged by the caller as
    non-metric. It keeps the pipeline running for a preview; it does not make
    the numbers true.
    """
    if not sparse or len(sparse.get("depths", ())) < 8:
        d = disparity.astype(np.float32)
        d = (d - d.min()) / max(float(d.max() - d.min()), 1e-6)
        return (0.4 + (1.0 - d) * 4.6).astype(np.float32)

    px = np.asarray(sparse["px"], dtype=int)
    py = np.asarray(sparse["py"], dtype=int)
    z = np.asarray(sparse["depths"], dtype=np.float64)

    d_at = disparity[py, px].astype(np.float64)
    inv_z = 1.0 / np.clip(z, 1e-3, None)

    a_b = np.linalg.lstsq(np.stack([d_at, np.ones_like(d_at)], 1), inv_z,
                          rcond=None)[0]
    metric = 1.0 / np.clip(a_b[0] * disparity + a_b[1], 1e-3, None)
    return np.clip(metric, 0.0, 8.0).astype(np.float32)


def run(input_path: Path, frames: list[str], size: tuple[int, int],
        mode: str = "auto", depth_scale: float = 1000.0,
        source_idx: list[int] | None = None,
        progress=None) -> tuple[list[np.ndarray] | None, str]:
    """Return (depths, mode_used). depths is None only when mode='none'."""
    input_path = Path(input_path)

    if mode in ("auto", "sensor"):
        depth_dir = find_depth_dir(input_path if input_path.is_dir()
                                   else input_path.parent)
        if depth_dir:
            depths = load_sensor_depth(depth_dir, len(frames), size, depth_scale,
                                       source_idx)
            if depths:
                if progress:
                    progress.stage("depth", 1.0, f"sensor depth ({len(depths)})")
                return depths, "sensor"
        if mode == "sensor":
            raise FileNotFoundError(
                f"--depth-mode sensor but no depth maps found near {input_path}")

    if mode in ("auto", "mono"):
        try:
            depths = estimate_mono_depth(frames, None, progress)
            return depths, "mono"
        except Exception as e:  # noqa: BLE001 - no torch hub / no network
            if mode == "mono":
                raise
            log.warning("MiDaS unavailable (%s) - continuing without depth", e)

    return None, "none"
