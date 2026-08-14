"""Differential-drive motion model for the ARIA simulator (spec 12.8).

Deliberately not a rigid-body engine. What matters for the demo is that motion has
believable acceleration limits and turn-before-drive behaviour, so the browser twin
moves like a real robot rather than teleporting between waypoints.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ARIA's drivetrain envelope.
MAX_LINEAR_MPS = 0.45          # matches MAX_SPEED_MPS in .env
MAX_ANGULAR_RAD_S = 1.8
LINEAR_ACCEL_MPS2 = 0.8
ANGULAR_ACCEL_RAD_S2 = 4.0

# Drive straight only once roughly aligned; otherwise turn in place first.
# Without this ARIA arcs wide around every corner and clips furniture.
ALIGN_TOLERANCE_RAD = math.radians(12)
WAYPOINT_REACHED_M = 0.06


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass
class DriveState:
    x: float = 0.0
    z: float = 0.0
    yaw: float = 0.0          # radians; 0 faces +Z, positive toward +X (spec 8.1)
    v: float = 0.0            # current linear m/s
    w: float = 0.0            # current angular rad/s


def _approach(current: float, target: float, max_delta: float) -> float:
    d = target - current
    if abs(d) <= max_delta:
        return target
    return current + math.copysign(max_delta, d)


def step_towards(
    st: DriveState, goal: tuple[float, float], dt: float, speed: float
) -> bool:
    """Advance one tick toward an XZ goal. Returns True when the goal is reached.

    Mutates `st` in place.
    """
    dx = goal[0] - st.x
    dz = goal[1] - st.z
    dist = math.hypot(dx, dz)

    if dist <= WAYPOINT_REACHED_M:
        st.v = _approach(st.v, 0.0, LINEAR_ACCEL_MPS2 * dt)
        st.w = _approach(st.w, 0.0, ANGULAR_ACCEL_RAD_S2 * dt)
        return True

    # Desired heading in the spec's convention: yaw 0 = +Z, positive toward +X.
    desired_yaw = math.atan2(dx, dz)
    yaw_err = wrap(desired_yaw - st.yaw)

    # Angular: proportional, saturated.
    want_w = max(-MAX_ANGULAR_RAD_S, min(MAX_ANGULAR_RAD_S, 2.4 * yaw_err))
    st.w = _approach(st.w, want_w, ANGULAR_ACCEL_RAD_S2 * dt)

    # Linear: only once roughly aligned, and slow down on approach so the last
    # waypoint isn't overshot at full speed.
    cruise = min(speed, MAX_LINEAR_MPS)
    if abs(yaw_err) > ALIGN_TOLERANCE_RAD:
        want_v = 0.0
    else:
        want_v = min(cruise, math.sqrt(max(0.0, 2 * LINEAR_ACCEL_MPS2 * dist)))
    st.v = _approach(st.v, want_v, LINEAR_ACCEL_MPS2 * dt)

    # Integrate.
    st.yaw = wrap(st.yaw + st.w * dt)
    st.x += st.v * math.sin(st.yaw) * dt
    st.z += st.v * math.cos(st.yaw) * dt
    return False


def turn_towards(st: DriveState, target_yaw: float, dt: float) -> bool:
    """Rotate in place. Returns True when aligned."""
    err = wrap(target_yaw - st.yaw)
    if abs(err) < math.radians(2):
        st.w = _approach(st.w, 0.0, ANGULAR_ACCEL_RAD_S2 * dt)
        return True
    want_w = max(-MAX_ANGULAR_RAD_S, min(MAX_ANGULAR_RAD_S, 2.4 * err))
    st.w = _approach(st.w, want_w, ANGULAR_ACCEL_RAD_S2 * dt)
    st.yaw = wrap(st.yaw + st.w * dt)
    st.v = _approach(st.v, 0.0, LINEAR_ACCEL_MPS2 * dt)
    return False


def halt(st: DriveState) -> None:
    """E-stop: velocities to zero immediately. Position is left alone - a real
    robot does not teleport back."""
    st.v = 0.0
    st.w = 0.0
