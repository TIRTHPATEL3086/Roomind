"""Safety Supervisor (spec 9.10, 1.4.2).

The one module allowed to pre-empt any layer. Its e-stop path bypasses every queue
and every DB write - persisting first would add latency to the single path where
latency can break something physical.
"""
from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.core.errors import UnsupportedCapability, Unsafe
from app.core.geometry import Vec2
from app.services.mqtt_service import mqtt_service

log = logging.getLogger("roommind.safety")

# Actions that need hardware which may simply not be fitted.
HARDWARE_GATED = {
    "gesture": "robot_has_waist",     # some poses need the waist servo
    "imagine": "imagine_enabled",
}


class SafetyService:
    def __init__(self) -> None:
        self.estopped = False
        self.last_estop_ts: float | None = None
        self.last_estop_latency_ms: float | None = None

    # ── e-stop ──

    def estop(self, robot_id: str = "aria") -> float:
        """Publish the stop and return the measured publish latency in ms.

        Ordering is load-bearing: MQTT first at QoS 0, THEN state, THEN (by the
        caller) any persistence.
        """
        t0 = time.perf_counter()
        mqtt_service.publish_estop(robot_id, time.time())
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.estopped = True
        self.last_estop_ts = time.time()
        self.last_estop_latency_ms = latency_ms

        budget = get_settings().estop_latency_budget_ms
        if latency_ms > budget:
            log.error("E-STOP publish took %.1f ms (budget %d ms)", latency_ms, budget)
        else:
            log.warning("E-STOP published in %.1f ms", latency_ms)
        return latency_ms

    def clear_estop(self, robot_id: str = "aria") -> None:
        """Release BOTH latches - the backend's and the robot's.

        Clearing only this side leaves the robot frozen while the API reports it
        ready, which looks exactly like a dead robot on demo day.
        """
        self.estopped = False
        mqtt_service.publish_estop_clear(robot_id, time.time())
        log.info("e-stop cleared (backend + robot)")

    # ── pre-flight checks ──

    def check_capability(self, action: str, capabilities: list[str]) -> None:
        s = get_settings()
        if action not in capabilities:
            raise UnsupportedCapability(
                f"ARIA has no '{action}' capability"
            )
        flag = HARDWARE_GATED.get(action)
        if flag and not getattr(s, flag, True):
            raise UnsupportedCapability(
                f"'{action}' needs hardware that is not fitted ({flag}=false)"
            )

    def check_not_estopped(self, action: str) -> None:
        """`stop` is always allowed through; nothing else is while latched."""
        if self.estopped and action != "stop":
            raise Unsafe("robot is e-stopped - clear it before issuing commands")

    def clamp_speed(self, mps: float) -> float:
        s = get_settings()
        return max(0.05, min(s.max_speed_mps, mps))

    def check_geofence(self, scene_graph: dict, point: Vec2) -> None:
        """Refuse a target outside the scanned room bounds."""
        b = scene_graph.get("bounds")
        if not b:
            return
        margin = get_settings().geofence_margin_m
        min_x, _, min_z = b["min"]
        max_x, _, max_z = b["max"]
        if not (min_x + margin <= point[0] <= max_x - margin
                and min_z + margin <= point[1] <= max_z - margin):
            raise Unsafe(f"target {point} is outside the room geofence")

    def status(self) -> dict:
        return {
            "estopped": self.estopped,
            "last_estop_ts": self.last_estop_ts,
            "last_estop_latency_ms": self.last_estop_latency_ms,
            "budget_ms": get_settings().estop_latency_budget_ms,
        }


safety_service = SafetyService()
