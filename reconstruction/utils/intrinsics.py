"""Camera intrinsics loading and rescaling.

S01 resizes every frame to 960 px wide. Intrinsics are in PIXELS, so they must
be rescaled by the same factor or every back-projected point lands at the wrong
depth-scaled offset -- a silent error that shows up as a room that is the right
shape but the wrong size.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


def load(path: str | Path | None, width: int, height: int) -> tuple[np.ndarray, dict]:
    """Return (K, meta). Falls back to a plausible phone camera when absent.

    The fallback is a 60-degree horizontal field of view, which is close to the
    main camera on most phones. It is a guess and it is labelled as one in the
    returned meta, because a wrong focal length scales the whole reconstruction:
    §18.1 lists exactly this as the way to get a room that is the right shape
    and the wrong size.
    """
    if path and Path(path).exists():
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        src_w = raw.get("width", width)
        src_h = raw.get("height", height)
        k = np.array([
            [raw["fx"], 0.0, raw["cx"]],
            [0.0, raw["fy"], raw["cy"]],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)
        k = rescale(k, src_w, src_h, width, height)
        return k, {"source": "file", "path": str(path),
                   "depth_scale": float(raw.get("depth_scale", 1000.0))}

    fov_x = math.radians(60.0)
    fx = fy = width / (2 * math.tan(fov_x / 2))
    k = np.array([[fx, 0.0, width / 2], [0.0, fy, height / 2], [0.0, 0.0, 1.0]])
    return k, {"source": "assumed_60deg_fov", "depth_scale": 1000.0}


def rescale(k: np.ndarray, src_w: int, src_h: int, dst_w: int, dst_h: int) -> np.ndarray:
    sx, sy = dst_w / src_w, dst_h / src_h
    out = k.copy().astype(np.float64)
    out[0, 0] *= sx
    out[0, 2] *= sx
    out[1, 1] *= sy
    out[1, 2] *= sy
    return out


def save(path: str | Path, k: np.ndarray, width: int, height: int,
         depth_scale: float = 1000.0) -> None:
    Path(path).write_text(json.dumps({
        "fx": float(k[0, 0]), "fy": float(k[1, 1]),
        "cx": float(k[0, 2]), "cy": float(k[1, 2]),
        "width": int(width), "height": int(height),
        "depth_scale": float(depth_scale),
    }, indent=2), encoding="utf-8")


def to_open3d(k: np.ndarray, width: int, height: int):
    import open3d as o3d
    return o3d.camera.PinholeCameraIntrinsic(
        int(width), int(height),
        float(k[0, 0]), float(k[1, 1]), float(k[0, 2]), float(k[1, 2]))
