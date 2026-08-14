"""Metric scaling tests (spec 10B.10) — the #1 bug source in Imagine.

A regression here ships a chair the size of a house, so these are deliberately
exhaustive: every primitive, every axis convention, every degenerate input.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import trimesh
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steps.g06_scale import (  # noqa: E402
    MAX_DIM_M,
    MIN_DIM_M,
    prior_dims,
    sanitize_dims,
    scale_to_metric,
)
from steps.g08_proxy import build_proxy, choose_primitive  # noqa: E402

IMG = Image.new("RGBA", (64, 64), (200, 100, 80, 255))


def unit_cube() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(1.0, 1.0, 1.0))


# ── the core contract ──

def test_height_is_matched_exactly() -> None:
    m = unit_cube()
    r = scale_to_metric(m, [0.35, 1.62, 0.35])
    assert m.bounding_box.extents[1] == pytest.approx(1.62, abs=1e-3)
    assert r.final_dims[1] == pytest.approx(1.62, abs=1e-3)


def test_scale_is_uniform_not_per_axis() -> None:
    """Per-axis scaling to hit all three targets distorts the object — a
    stretched sofa reads as broken instantly."""
    m = trimesh.creation.box(extents=(2.0, 1.0, 1.0))   # x:z aspect = 2.0
    scale_to_metric(m, [0.35, 1.62, 0.35])              # target aspect = 1.0
    x, _, z = m.bounding_box.extents
    assert x / z == pytest.approx(2.0, rel=1e-6), "aspect must survive scaling"


def test_aspect_preserved_flag_is_honest() -> None:
    m = trimesh.creation.box(extents=(2.0, 1.0, 0.5))
    assert scale_to_metric(m, [1.0, 1.0, 1.0]).aspect_preserved


def test_base_sits_exactly_on_the_floor() -> None:
    m = unit_cube()
    scale_to_metric(m, [0.4, 1.0, 0.4], floor_y=0.0)
    assert m.bounds[0][1] == pytest.approx(0.0, abs=1e-6)


def test_base_respects_a_nonzero_floor() -> None:
    m = unit_cube()
    scale_to_metric(m, [0.4, 1.0, 0.4], floor_y=0.35)
    assert m.bounds[0][1] == pytest.approx(0.35, abs=1e-6)


def test_pivot_is_centred_in_xz() -> None:
    """Otherwise rotation_y swings the object around an arbitrary point."""
    m = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    m.apply_translation([5.0, 0.0, -3.0])
    scale_to_metric(m, [0.4, 1.0, 0.4])
    c = m.bounds.mean(axis=0)
    assert c[0] == pytest.approx(0.0, abs=1e-6)
    assert c[2] == pytest.approx(0.0, abs=1e-6)


def test_an_already_correct_mesh_is_left_alone() -> None:
    m = trimesh.creation.box(extents=(0.35, 1.62, 0.35))
    r = scale_to_metric(m, [0.35, 1.62, 0.35])
    assert r.scale == pytest.approx(1.0, abs=1e-9)


def test_scaling_is_idempotent() -> None:
    """Running the step twice must not compound — a double-scale is exactly how
    a 1.55 m lamp becomes a 6.9 m one."""
    m = unit_cube()
    scale_to_metric(m, [0.35, 1.62, 0.35])
    first = tuple(m.bounding_box.extents)
    scale_to_metric(m, [0.35, 1.62, 0.35])
    assert tuple(m.bounding_box.extents) == pytest.approx(first, abs=1e-6)


# ── degenerate and hostile inputs ──

def test_flat_mesh_does_not_divide_by_zero() -> None:
    m = trimesh.creation.box(extents=(1.0, 1e-12, 1.0))
    r = scale_to_metric(m, [1.0, 0.02, 1.0])
    assert r.scale > 0
    assert all(v == v for v in r.final_dims)   # no NaN


@pytest.mark.parametrize("bad", [
    [0.3, 0.0, 0.3], [0.3, -2.0, 0.3], [0.3, float("nan"), 0.3],
    [0.3, float("inf"), 0.3],
])
def test_invalid_dimensions_are_clamped_not_obeyed(bad) -> None:
    dims, clamped = sanitize_dims(bad)
    assert clamped
    assert all(MIN_DIM_M <= v <= MAX_DIM_M for v in dims)


def test_absurd_estimate_is_clamped() -> None:
    """A VLM that says a lamp is 40 m tall should be clamped, not obeyed."""
    m = unit_cube()
    r = scale_to_metric(m, [0.3, 40.0, 0.3])
    assert r.clamped
    assert r.final_dims[1] <= MAX_DIM_M


# ── the proxy path goes through the SAME scaler ──

@pytest.mark.parametrize("dims,placement", [
    ((0.35, 1.55, 0.35), "floor"),    # slender -> cylinder
    ((1.20, 0.74, 0.70), "floor"),    # bulky   -> box
    ((0.60, 0.90, 0.03), "wall"),     # flat    -> plane
    ((0.09, 0.10, 0.09), "surface"),  # small   -> box
])
def test_every_proxy_primitive_ends_at_the_target_size(dims, placement) -> None:
    """Regression for the cylinder-axis bug: trimesh builds cylinders along Z,
    so an unrotated one is lying down — and since scaling matches on HEIGHT,
    that made a 1.55 m lamp come out 4.4x too big in every axis."""
    mesh, _kind = build_proxy(IMG, dims, placement)
    scale_to_metric(mesh, dims)
    got = mesh.bounding_box.extents
    assert got[1] == pytest.approx(dims[1], abs=1e-3), "height must match"
    # width/depth follow from uniform scale; a correctly-built primitive is
    # already the right aspect, so they should land close too
    assert got[0] == pytest.approx(dims[0], abs=0.02)
    assert got[2] == pytest.approx(dims[2], abs=0.02)


def test_cylinder_is_built_upright() -> None:
    mesh, kind = build_proxy(IMG, (0.35, 1.55, 0.35), "floor")
    assert kind == "cylinder"
    x, y, z = mesh.bounding_box.extents
    assert y > x and y > z, "cylinder must be tall in Y, not lying along Z"


def test_primitive_choice_matches_the_object_shape() -> None:
    assert choose_primitive((0.35, 1.55, 0.35), "floor") == "cylinder"
    assert choose_primitive((1.20, 0.74, 0.70), "floor") == "box"
    assert choose_primitive((0.60, 0.90, 0.03), "wall") == "plane"
    assert choose_primitive((2.40, 0.01, 1.60), "floor") == "plane"


def test_proxy_is_marked_as_a_proxy() -> None:
    """The frontend renders these with a dashed outline — nobody should mistake
    a stand-in for a real reconstruction."""
    mesh, _ = build_proxy(IMG, (0.4, 0.4, 0.4), "floor")
    assert mesh.metadata["roommind_proxy"] is True


def test_proxy_carries_the_image_as_a_texture() -> None:
    mesh, _ = build_proxy(IMG, (0.4, 0.4, 0.4), "floor")
    assert mesh.visual.uv is not None
    assert len(mesh.visual.uv) == len(mesh.vertices)


# ── the offline size table ──

def test_prior_table_knows_common_furniture() -> None:
    dims, conf = prior_dims("chair")
    assert dims == (0.45, 0.90, 0.45)
    assert conf >= 0.5


def test_prior_table_falls_back_to_the_head_noun() -> None:
    dims, conf = prior_dims("reading_lamp")
    assert dims == prior_dims("lamp")[0]
    assert conf < 0.5, "an inferred match should be less confident"


def test_unknown_label_gets_low_confidence() -> None:
    """Below 0.5 the pipeline shows a preview instead of committing (10B.5)."""
    _dims, conf = prior_dims("flurbulator")
    assert conf < 0.5


def test_every_prior_entry_is_physically_plausible() -> None:
    from steps.g06_scale import PRIOR_DIMS

    for label, dims in PRIOR_DIMS.items():
        assert all(MIN_DIM_M <= v <= MAX_DIM_M for v in dims), label
