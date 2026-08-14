"""ARIA joint solver tests (spec 8.3.2, 12.6.3, 12.6.4).

Pure maths - no hardware, no DB. These guard the signature behaviour of the whole
project: ARIA looking at and pointing to the thing she is talking about.
"""
from __future__ import annotations

import math

import pytest

from app.core.kinematics import (
    LIMITS,
    REST_POSE,
    Pose,
    clamp_joint,
    pointing_error_deg,
    slew,
    solve_look_at,
    solve_point_at,
)

ORIGIN = Pose(0.0, 0.0, 0.0, 0.0)


# ── look_at ──

def test_target_straight_ahead_needs_no_pan() -> None:
    r = solve_look_at(ORIGIN, (0.0, 0.30, 2.0))   # dead ahead at head height
    assert r.head_pan == pytest.approx(0.0, abs=0.01)
    assert r.head_tilt == pytest.approx(0.0, abs=0.5)
    assert r.base_turn_needed == 0.0


def test_target_to_the_right_pans_positive() -> None:
    """+X is ARIA's right, and positive yaw rotates toward +X (spec 8.1)."""
    r = solve_look_at(ORIGIN, (2.0, 0.30, 2.0))
    assert r.head_pan == pytest.approx(45.0, abs=0.01)


def test_target_to_the_left_pans_negative() -> None:
    r = solve_look_at(ORIGIN, (-2.0, 0.30, 2.0))
    assert r.head_pan == pytest.approx(-45.0, abs=0.01)


def test_high_target_tilts_up() -> None:
    r = solve_look_at(ORIGIN, (0.0, 1.30, 1.0))   # 1 m up, 1 m ahead
    assert r.head_tilt > 0


def test_low_target_tilts_down() -> None:
    r = solve_look_at(ORIGIN, (0.0, 0.0, 1.0))
    assert r.head_tilt < 0


def test_target_behind_requests_a_base_turn() -> None:
    """Head range is +/-90. Anything behind must move the BASE, not strain the neck."""
    r = solve_look_at(ORIGIN, (0.0, 0.30, -2.0))
    assert r.clamped
    assert abs(r.base_turn_needed) > 45.0
    assert LIMITS["head_pan"][0] <= r.head_pan <= LIMITS["head_pan"][1]


def test_look_respects_base_yaw() -> None:
    """With the base already facing +X, a target on +X is straight ahead."""
    turned = Pose(0.0, 0.0, 0.0, math.pi / 2)     # yaw +90deg faces +X
    r = solve_look_at(turned, (2.0, 0.30, 0.0))
    assert r.head_pan == pytest.approx(0.0, abs=0.01)


def test_yaw_sign_convention_left_and_right() -> None:
    """Regression guard for the world->body sign (spec 8.1).

    Facing +X, a target on +Z is on ARIA's LEFT and one on -Z is on her RIGHT.
    Flipping the rotation sign makes both of these come out backwards, and ARIA
    points at empty space whenever her base isn't facing +Z.
    """
    facing_x = Pose(0.0, 0.0, 0.0, math.pi / 2)
    assert solve_look_at(facing_x, (0.0, 0.30, 2.0)).head_pan == pytest.approx(-90.0, abs=0.01)
    assert solve_look_at(facing_x, (0.0, 0.30, -2.0)).head_pan == pytest.approx(90.0, abs=0.01)
    assert solve_point_at(facing_x, (0.0, 0.30, 2.0)).arm == "l"
    assert solve_point_at(facing_x, (0.0, 0.30, -2.0)).arm == "r"


def test_look_respects_base_translation() -> None:
    at_x1 = Pose(1.0, 0.0, 0.0, 0.0)
    r = solve_look_at(at_x1, (1.0, 0.30, 3.0))    # directly ahead of the new position
    assert r.head_pan == pytest.approx(0.0, abs=0.01)


def test_every_look_output_is_inside_limits() -> None:
    for tx in (-4.0, -1.0, 0.0, 1.0, 4.0):
        for ty in (-1.0, 0.3, 3.0):
            for tz in (-4.0, -0.5, 0.0, 0.5, 4.0):
                r = solve_look_at(ORIGIN, (tx, ty, tz))
                assert LIMITS["head_pan"][0] <= r.head_pan <= LIMITS["head_pan"][1]
                assert LIMITS["head_tilt"][0] <= r.head_tilt <= LIMITS["head_tilt"][1]


# ── point_at ──

def test_point_uses_the_nearer_arm() -> None:
    assert solve_point_at(ORIGIN, (2.0, 0.5, 2.0)).arm == "r"
    assert solve_point_at(ORIGIN, (-2.0, 0.5, 2.0)).arm == "l"


def test_point_always_looks_at_the_same_target() -> None:
    """A robot pointing one way while facing another looks broken (spec 12.6.4)."""
    target = (1.5, 0.6, 1.5)
    p = solve_point_at(ORIGIN, target)
    expected = solve_look_at(ORIGIN, target)
    assert p.look is not None
    assert p.look.head_pan == pytest.approx(expected.head_pan, abs=1e-9)
    assert p.look.head_tilt == pytest.approx(expected.head_tilt, abs=1e-9)


def test_point_emits_only_the_chosen_arm() -> None:
    p = solve_point_at(ORIGIN, (2.0, 0.5, 2.0))
    assert set(p.joints) == {"r_shoulder_pitch", "r_shoulder_roll", "r_elbow"}


def test_point_output_is_inside_limits() -> None:
    for tx in (-3.0, -0.5, 0.5, 3.0):
        for ty in (0.0, 0.5, 2.0):
            for tz in (0.2, 1.0, 3.0):
                p = solve_point_at(ORIGIN, (tx, ty, tz))
                for name, v in p.joints.items():
                    lo, hi = LIMITS[name]
                    assert lo <= v <= hi, f"{name}={v} outside [{lo},{hi}]"


def test_pointing_accuracy_meets_the_hardware_gate() -> None:
    """Spec P7: the forearm axis must pass within 15 cm of the target at 1.5 m,
    which is atan(0.15/1.5) = 5.71 degrees."""
    tolerance = math.degrees(math.atan2(0.15, 1.5))
    for tx, ty, tz in ((1.0, 0.5, 1.1), (-1.0, 0.3, 1.1), (0.4, 0.8, 1.4), (-0.4, 0.1, 1.4)):
        p = solve_point_at(ORIGIN, (tx, ty, tz))
        err = pointing_error_deg(ORIGIN, (tx, ty, tz), p)
        assert err <= tolerance, f"pointing error {err:.2f}deg exceeds {tolerance:.2f}deg"


def test_higher_target_raises_the_shoulder() -> None:
    low = solve_point_at(ORIGIN, (1.0, 0.0, 1.0))
    high = solve_point_at(ORIGIN, (1.0, 1.5, 1.0))
    assert high.joints["r_shoulder_pitch"] > low.joints["r_shoulder_pitch"]


# ── clamping and slew ──

def test_clamp_joint_bounds() -> None:
    assert clamp_joint("head_pan", 200.0) == 90.0
    assert clamp_joint("head_pan", -200.0) == -90.0
    assert clamp_joint("l_elbow", 60.0) == 60.0


def test_slew_never_exceeds_the_rate() -> None:
    """Instant jumps strip gears and brown out the servo rail (spec 12.3)."""
    cur = dict(REST_POSE)
    out = slew(cur, {"head_pan": 90.0}, dt=0.1)     # 90 deg/s * 0.1 s = 9 deg max
    assert out["head_pan"] == pytest.approx(9.0, abs=1e-6)


def test_slew_snaps_when_within_one_step() -> None:
    out = slew({"head_pan": 88.0}, {"head_pan": 90.0}, dt=0.1)
    assert out["head_pan"] == pytest.approx(90.0)


def test_slew_converges_and_stays_in_limits() -> None:
    cur = dict(REST_POSE)
    target = {"head_pan": 90.0, "head_tilt": -35.0, "r_elbow": 120.0}
    for _ in range(200):                              # 2 s at 10 Hz
        cur = slew(cur, target, dt=0.1)
    for k, want in target.items():
        assert cur[k] == pytest.approx(want, abs=1e-6)


def test_slew_clamps_an_out_of_range_request() -> None:
    """A bad angle from the network must be clamped, never obeyed."""
    cur = dict(REST_POSE)
    for _ in range(500):
        cur = slew(cur, {"head_pan": 999.0}, dt=0.1)
    assert cur["head_pan"] == 90.0
