"""G08 — the proxy fallback (spec 10B.7).

When there is no GPU, generation times out, or the backend throws, we still
produce a usable object: a primitive matching the estimated size, wearing the
source image as a front-facing billboard texture.

This is deliberately built FIRST and shipped always. A visible, correctly-sized
stand-in that ARIA can navigate to and point at is a feature. A spinner that
never resolves in front of judges is a failure.
"""
from __future__ import annotations

import numpy as np
import trimesh
from PIL import Image


def _uv_for_box(mesh: trimesh.Trimesh) -> np.ndarray:
    """Planar UVs projected on the XY plane, so the cut-out reads as a
    front-facing billboard on the primitive's front face."""
    v = mesh.vertices
    mn, mx = v.min(axis=0), v.max(axis=0)
    span = np.where((mx - mn) < 1e-9, 1.0, mx - mn)
    u = (v[:, 0] - mn[0]) / span[0]
    w = (v[:, 1] - mn[1]) / span[1]
    return np.column_stack([u, w])


def choose_primitive(dims, placement: str) -> str:
    """Pick a shape that reads as the right kind of thing at a glance."""
    w, h, d = dims
    if placement == "wall":
        return "plane"
    slender = h > 2.0 * max(w, d)
    if placement == "floor" and slender:
        return "cylinder"
    if h < 0.06:
        return "plane"
    return "box"


def build_proxy(image: Image.Image, dims, placement: str = "floor"
                ) -> tuple[trimesh.Trimesh, str]:
    """A textured primitive sized to `dims`. Returns (mesh, primitive_kind).

    The mesh is built at unit scale in Y and left for g06 to scale — one
    scaling path for every backend means the metric-scaling tests cover the
    proxy too, rather than it having a second, untested sizing route.
    """
    kind = choose_primitive(dims, placement)
    w, h, d = (max(float(v), 1e-3) for v in dims)

    if kind == "cylinder":
        r = max(w, d) / 2.0
        mesh = trimesh.creation.cylinder(radius=r, height=h, sections=24)
        # trimesh builds cylinders along Z. Our world is Y-up (spec 8.1), so an
        # unrotated cylinder is lying on its side — and because g06 matches
        # scale on HEIGHT, that made a 1.55 m lamp come out 4.4x too big in
        # every axis. Rotate it upright before anything measures it.
        mesh.apply_transform(
            trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
        )
    elif kind == "plane":
        mesh = trimesh.creation.box(extents=(w, max(h, 0.01), max(d, 0.01)))
    else:
        mesh = trimesh.creation.box(extents=(w, h, d))

    mesh.visual = trimesh.visual.TextureVisuals(
        uv=_uv_for_box(mesh),
        image=image.convert("RGBA"),
    )
    # Marks it as a stand-in — the frontend renders these with a dashed outline
    # so nobody mistakes a proxy for a real reconstruction.
    mesh.metadata["roommind_proxy"] = True
    mesh.metadata["primitive"] = kind
    return mesh, kind
