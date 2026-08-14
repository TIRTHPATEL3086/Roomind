"""G06 — unit-cube mesh -> real-world metres (spec 10B.5).

READ THIS TWICE. It is the single largest source of bugs in the Imagine feature.

Every image-to-3D model emits a mesh normalised into a unit cube with NO
real-world scale. A generated lamp is exactly the same size as a generated sofa
until this step fixes it. Get it wrong and the demo shows a chair the size of a
house — which is the classic, and very visible, failure.

Three rules, all load-bearing:

  1. UNIFORM scale only. Per-axis scaling to hit all three target dimensions
     distorts the object, and a stretched sofa reads as broken instantly.
  2. Match on HEIGHT. Humans judge whether an object is the right size almost
     entirely by its height; width and depth errors go unnoticed.
  3. Base on the floor, pivot centred in XZ. Otherwise the object floats or
     sinks, and rotating it swings it around some arbitrary point.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Sanity envelope for a household object. A VLM that returns 40 m for a lamp
# should be clamped, not obeyed.
#
# The floor is 5 mm, not something rounder like 2 cm: genuinely flat objects
# exist (a rug is ~1 cm, a book cover ~3 mm) and clamping them up would inflate
# a rug to twice its real thickness. 5 mm is still far below anything real, so
# it catches zero, negative, and NaN without touching a legitimate estimate.
MIN_DIM_M = 0.005
MAX_DIM_M = 4.0


@dataclass
class ScaleResult:
    scale: float                      # uniform factor applied
    final_dims: tuple[float, float, float]
    clamped: bool                     # est_dims were outside the sane envelope
    aspect_preserved: bool


def sanitize_dims(dims) -> tuple[tuple[float, float, float], bool]:
    """Clamp an estimate into the plausible envelope for a room object."""
    out, clamped = [], False
    for v in dims:
        v = float(v)
        if not np.isfinite(v) or v <= 0:
            v, clamped = 0.5, True
        if v < MIN_DIM_M:
            v, clamped = MIN_DIM_M, True
        elif v > MAX_DIM_M:
            v, clamped = MAX_DIM_M, True
        out.append(v)
    return (out[0], out[1], out[2]), clamped


def scale_to_metric(mesh, est_dims_m, floor_y: float = 0.0) -> ScaleResult:
    """Scale `mesh` in place to the estimated real-world size.

    `est_dims_m` is [width, height, depth] in metres, Y-up (spec 8.1).
    Returns the applied factor and the resulting bounding box.
    """
    target, clamped = sanitize_dims(est_dims_m)
    extents = mesh.bounding_box.extents
    before_aspect = _aspect(extents)

    height = float(extents[1])
    if height <= 1e-9:
        # Degenerate/flat mesh: fall back to the largest axis so we still get a
        # sane object rather than dividing by zero.
        height = float(max(extents)) or 1.0
        scale = target[1] / height
    else:
        scale = target[1] / height

    mesh.apply_scale(scale)

    # Base exactly on the floor plane. Do this BEFORE the XZ recentre so the
    # translation isn't computed against stale bounds.
    mesh.apply_translation([0.0, floor_y - mesh.bounds[0][1], 0.0])

    # Pivot centred in XZ so rotation_y spins the object about itself.
    c = mesh.bounds.mean(axis=0)
    mesh.apply_translation([-c[0], 0.0, -c[2]])

    final = mesh.bounding_box.extents
    return ScaleResult(
        scale=scale,
        final_dims=(float(final[0]), float(final[1]), float(final[2])),
        clamped=clamped,
        aspect_preserved=abs(_aspect(final) - before_aspect) < 1e-6,
    )


def _aspect(extents) -> float:
    """x:z ratio — invariant under uniform scaling, so it's the check that
    catches an accidental per-axis scale."""
    x, _, z = (float(v) for v in extents)
    return x / z if z > 1e-9 else 0.0


# Fallback size table for the offline path (spec 10B.5, estimator=prior_table).
# Median real-world dimensions, [w, h, d] metres. This is what makes Imagine
# work with MOCK_LLM=true and no network — it is mandatory, not a nicety.
PRIOR_DIMS: dict[str, tuple[float, float, float]] = {
    "chair": (0.45, 0.90, 0.45), "stool": (0.35, 0.60, 0.35),
    "sofa": (1.90, 0.80, 0.85), "armchair": (0.90, 0.85, 0.85),
    "table": (1.20, 0.74, 0.70), "desk": (1.20, 0.74, 0.60),
    "coffee_table": (1.00, 0.42, 0.55), "side_table": (0.45, 0.55, 0.45),
    "lamp": (0.35, 1.55, 0.35), "table_lamp": (0.25, 0.45, 0.25),
    "shelf": (0.90, 1.80, 0.30), "bookshelf": (0.90, 1.80, 0.30),
    "tv": (1.15, 0.65, 0.08), "monitor": (0.60, 0.40, 0.18),
    "potted_plant": (0.40, 0.70, 0.40), "vase": (0.18, 0.32, 0.18),
    "rug": (2.40, 0.01, 1.60), "box": (0.40, 0.35, 0.30),
    "bed": (1.50, 0.55, 2.00), "cabinet": (0.90, 1.20, 0.45),
    "mug": (0.09, 0.10, 0.09), "book": (0.15, 0.22, 0.03),
    "laptop": (0.33, 0.02, 0.23), "guitar": (0.38, 1.00, 0.12),
    "clock": (0.30, 0.30, 0.05), "mirror": (0.60, 0.90, 0.03),
}

DEFAULT_DIMS = (0.35, 0.40, 0.35)


def prior_dims(label: str) -> tuple[tuple[float, float, float], float]:
    """(dims, confidence) for a label, using the offline table.

    Confidence is deliberately modest even on a hit: a median chair is not the
    user's chair. Below 0.5 the pipeline shows a preview instead of committing
    (spec 10B.5), which is the honest behaviour.
    """
    key = label.lower().strip().replace(" ", "_")
    if key in PRIOR_DIMS:
        return PRIOR_DIMS[key], 0.55
    # try the head noun: "reading_lamp" -> "lamp"
    for part in reversed(key.split("_")):
        if part in PRIOR_DIMS:
            return PRIOR_DIMS[part], 0.45
    return DEFAULT_DIMS, 0.2
