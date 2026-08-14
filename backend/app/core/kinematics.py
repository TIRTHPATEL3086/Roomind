"""ARIA's joint solvers - look_at and point_at (spec 8.3.2, 12.6.3, 12.6.4).

ONE implementation of this maths, shared by the simulator and mirrored by the MCU
firmware in C++. If the two ever disagree, the virtual twin stops matching the real
robot and the whole digital-twin illusion collapses - so the sim imports this module
rather than reimplementing it.

All angles are DEGREES in ARIA's body frame. World frame is right-handed Y-up:
+Z forward, yaw 0 faces +Z, positive yaw rotates toward +X (spec 8.1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Geometry of the physical robot, metres.
HEAD_HEIGHT_M = 0.30       # head pivot above the base origin
SHOULDER_HEIGHT_M = 0.24   # shoulder pivot above the base origin
SHOULDER_OFFSET_M = 0.08   # lateral distance from centreline to each shoulder

# Per-joint limits - MUST match pins.h LIM_* and the spec 8.3.2 table.
LIMITS: dict[str, tuple[float, float]] = {
    "head_pan": (-90.0, 90.0),
    "head_tilt": (-35.0, 35.0),
    "waist_yaw": (-45.0, 45.0),
    "l_shoulder_pitch": (-20.0, 150.0),
    "r_shoulder_pitch": (-20.0, 150.0),
    "l_shoulder_roll": (0.0, 90.0),
    "r_shoulder_roll": (0.0, 90.0),
    "l_elbow": (0.0, 120.0),
    "r_elbow": (0.0, 120.0),
}

REST_POSE: dict[str, float] = {
    "head_pan": 0.0, "head_tilt": 0.0, "waist_yaw": 0.0,
    "l_shoulder_pitch": 0.0, "l_shoulder_roll": 5.0, "l_elbow": 15.0,
    "r_shoulder_pitch": 0.0, "r_shoulder_roll": 5.0, "r_elbow": 15.0,
}

# Default slew rates, degrees/second. The head is deliberately slower: a head that
# whips round reads as mechanical, one that turns at ~90 deg/s reads as attention.
SLEW_DEG_S: dict[str, float] = {
    "head_pan": 90.0, "head_tilt": 90.0, "waist_yaw": 60.0,
    "l_shoulder_pitch": 150.0, "r_shoulder_pitch": 150.0,
    "l_shoulder_roll": 150.0, "r_shoulder_roll": 150.0,
    "l_elbow": 150.0, "r_elbow": 150.0,
}


def clamp_joint(name: str, value: float) -> float:
    """Clamp to the joint's limit. The MCU is the final authority and does this too -
    never trust the planner, the LLM or the network to respect a servo limit."""
    lo, hi = LIMITS[name]
    return max(lo, min(hi, value))


def clamp_pose(pose: dict[str, float]) -> dict[str, float]:
    return {k: clamp_joint(k, v) for k, v in pose.items() if k in LIMITS}


@dataclass
class Pose:
    """Base pose in the world frame."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0   # RADIANS (matches the telemetry contract)


def world_to_body(pose: Pose, tx: float, ty: float, tz: float, pivot_height: float
                  ) -> tuple[float, float, float]:
    """Transform a world point into ARIA's body frame.

    Returns (bx, by, bz) where +bz is straight ahead and +bx is to ARIA's right.

    SIGN WARNING - this trips everyone, and the spec's C++ snippet had it wrong:
    the usual world->body transform rotates by -yaw, but this project measures yaw
    from +Z *toward* +X (spec 8.1), which is a LEFT-handed rotation about Y in an
    otherwise right-handed frame. That flips the sign, so we rotate by +yaw:

        forward = (sin yaw, cos yaw)      yaw=0 -> +Z,  yaw=90deg -> +X
        right   = (cos yaw, -sin yaw)     yaw=0 -> +X,  yaw=90deg -> -Z

        bx = dx*cos(yaw) - dz*sin(yaw)    (component along `right`)
        bz = dx*sin(yaw) + dz*cos(yaw)    (component along `forward`)

    Get this backwards and ARIA points confidently at empty space whenever her
    base is not facing +Z - which is almost always.
    """
    dx = tx - pose.x
    dz = tz - pose.z
    c, s = math.cos(pose.yaw), math.sin(pose.yaw)
    bx = dx * c - dz * s
    bz = dx * s + dz * c
    by = ty - (pose.y + pivot_height)
    return bx, by, bz


@dataclass
class LookResult:
    head_pan: float
    head_tilt: float
    base_turn_needed: float = 0.0   # degrees the base must rotate; 0 if none
    clamped: bool = False


def solve_look_at(pose: Pose, target: tuple[float, float, float]) -> LookResult:
    """Head pan/tilt that aims at a world-space target.

    If the target is outside head range, ask the BASE to turn rather than straining
    the neck - and report how far, so the caller can queue a turn command.
    """
    bx, by, bz = world_to_body(pose, *target, HEAD_HEIGHT_M)

    pan = math.degrees(math.atan2(bx, bz))
    tilt = math.degrees(math.atan2(by, math.hypot(bx, bz)))

    lo, hi = LIMITS["head_pan"]
    base_turn = 0.0
    clamped = False
    if pan < lo or pan > hi:
        # rotate the base by the excess, leaving the head at its limit
        base_turn = pan - max(lo, min(hi, pan))
        clamped = True

    tilt_lo, tilt_hi = LIMITS["head_tilt"]
    if tilt < tilt_lo or tilt > tilt_hi:
        clamped = True

    return LookResult(
        head_pan=clamp_joint("head_pan", pan),
        head_tilt=clamp_joint("head_tilt", tilt),
        base_turn_needed=base_turn,
        clamped=clamped,
    )


@dataclass
class PointResult:
    arm: str                       # "l" or "r"
    joints: dict[str, float] = field(default_factory=dict)
    look: LookResult | None = None
    clamped: bool = False


def solve_point_at(pose: Pose, target: tuple[float, float, float]) -> PointResult:
    """Aim the nearer arm at a world-space target.

    This is AIMING, not reaching. We only need the forearm's direction vector to
    line up with the target - far more robust than full IK, and indistinguishable
    to an observer.
    """
    bx, by, bz = world_to_body(pose, *target, SHOULDER_HEIGHT_M)

    use_right = bx >= 0
    side = "r" if use_right else "l"

    # measure from the shoulder, not the centreline, or short-range points skew
    sx = bx - (SHOULDER_OFFSET_M if use_right else -SHOULDER_OFFSET_M)

    horiz = math.hypot(sx, bz)
    pitch = math.degrees(math.atan2(by, horiz)) + 90.0   # 90 deg = arm straight out
    roll = math.degrees(math.atan2(abs(sx), max(bz, 1e-6)))
    elbow = 10.0                                          # nearly straight = unambiguous

    raw = {
        f"{side}_shoulder_pitch": pitch,
        f"{side}_shoulder_roll": roll,
        f"{side}_elbow": elbow,
    }
    joints = clamp_pose(raw)
    clamped = any(abs(joints[k] - raw[k]) > 1e-9 for k in raw)

    return PointResult(
        arm=side,
        joints=joints,
        look=solve_look_at(pose, target),   # always look where you point (spec 12.6.4)
        clamped=clamped,
    )


def pointing_error_deg(
    pose: Pose, target: tuple[float, float, float], result: PointResult
) -> float:
    """Angle between where the arm actually points and the true target direction.

    The hardware acceptance test (spec P7) is 15 cm at 1.5 m, which is ~5.7 deg.
    """
    side = result.arm
    pitch = result.joints[f"{side}_shoulder_pitch"] - 90.0
    roll = result.joints[f"{side}_shoulder_roll"]

    # forward direction implied by the joint angles, in body frame
    sign = 1.0 if side == "r" else -1.0
    horiz = math.cos(math.radians(pitch))
    ay = math.sin(math.radians(pitch))
    ax = sign * horiz * math.sin(math.radians(roll))
    az = horiz * math.cos(math.radians(roll))

    bx, by, bz = world_to_body(pose, *target, SHOULDER_HEIGHT_M)
    bx -= sign * SHOULDER_OFFSET_M
    n = math.sqrt(bx * bx + by * by + bz * bz)
    if n < 1e-9:
        return 0.0
    dot = (ax * bx + ay * by + az * bz) / n
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def slew(
    current: dict[str, float], target: dict[str, float], dt: float,
    rates: dict[str, float] | None = None,
) -> dict[str, float]:
    """Advance joints toward their targets at a bounded rate.

    Never write a target angle straight to a servo: instant jumps strip gears,
    brown out the rail, and look robotic in the bad way.
    """
    rates = rates or SLEW_DEG_S
    out = dict(current)
    for name, want in target.items():
        if name not in LIMITS:
            continue
        have = current.get(name, REST_POSE.get(name, 0.0))
        max_step = rates.get(name, 120.0) * dt
        delta = want - have
        if abs(delta) <= max_step:
            out[name] = want
        else:
            out[name] = have + math.copysign(max_step, delta)
    return clamp_pose(out)
