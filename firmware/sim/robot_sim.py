"""ARIA simulator (spec 12.8) - the whole robot, no hardware.

Speaks the full MQTT contract from contracts/mqtt_topics.md: consumes commands and
paths, publishes telemetry at 10 Hz, acks, status with LWT, and honours e-stop.

It simulates the NINE JOINTS as well as the base pose, using the *same*
app.core.kinematics module the backend uses and the MCU firmware mirrors. One
implementation of that maths, so the sim can't quietly drift from the real robot -
which is exactly the bug that would only surface with hardware on the table.

    py -3.11 firmware/sim/robot_sim.py --robot aria --broker localhost
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.kinematics import (  # noqa: E402
    REST_POSE,
    Pose,
    clamp_pose,
    slew,
    solve_look_at,
    solve_point_at,
)
from physics import DriveState, halt, step_towards, turn_towards, wrap  # noqa: E402

log = logging.getLogger("aria.sim")

TELEMETRY_HZ = 10.0
TICK_HZ = 50.0
FIRMWARE_VERSION = "sim-1.0.0"

# Battery model: ~45 min of continuous driving, ~4 h idle. Fractions per second.
DRAIN_DRIVING_PER_S = 1.0 / (45 * 60)
DRAIN_IDLE_PER_S = 1.0 / (4 * 60 * 60)

# Walking gait: without this, driving only ever moved drive.x/z - the legs sat
# frozen in rest pose and ARIA slid across the floor like she was on casters.
# One full swing cycle (both legs) per this many metres travelled, so a faster
# `speed` param strides faster instead of covering more ground per step.
WALK_STRIDE_M = 0.55
HIP_SWING_DEG = 16.0
KNEE_LIFT_DEG = 24.0
ARM_SWING_DEG = 10.0
WALK_MOVING_THRESHOLD = 0.01   # m/s below which she's considered stopped

CAPABILITIES = [
    "navigate", "come_here", "stop", "follow_me", "dock", "turn", "set_speed",
    "look_at", "point_at", "wave", "nod", "shake_head", "gesture", "express",
    "dance", "scan_area", "remember_spot", "locate", "photo", "report_battery",
    "present", "imagine", "sit", "jump", "climb",
]

# Gesture keyframes: (joint, degrees_or_elevation, hold_seconds). Enhanced fluid keyframes.
GESTURES: dict[str, list[tuple[str, float, float]]] = {
    "wave": [
        ("r_shoulder_pitch", 135, 0.20), ("r_shoulder_roll", 30, 0.15),
        ("r_elbow", 80, 0.18), ("head_pan", -10, 0.15), ("head_tilt", 8, 0.15),
        ("r_elbow", 25, 0.18), ("head_pan", -15, 0.15),
        ("r_elbow", 75, 0.18), ("head_pan", -10, 0.15),
        ("r_elbow", 25, 0.18), ("head_pan", 0, 0.15),
        ("r_shoulder_pitch", 0, 0.30), ("r_shoulder_roll", 5, 0.25), ("head_tilt", 0, 0.20),
    ],
    "nod": [
        ("head_tilt", 22, 0.18), ("head_tilt", -10, 0.18),
        ("head_tilt", 20, 0.18), ("head_tilt", -5, 0.18),
        ("head_tilt", 0, 0.20),
    ],
    "shake_head": [
        ("head_pan", -28, 0.16), ("head_tilt", 5, 0.16),
        ("head_pan", 28, 0.16), ("head_tilt", -5, 0.16),
        ("head_pan", -22, 0.16), ("head_tilt", 0, 0.16),
        ("head_pan", 0, 0.20),
    ],
    "shrug": [
        ("l_shoulder_roll", 45, 0.25), ("r_shoulder_roll", 45, 0.25),
        ("l_elbow", 40, 0.20), ("r_elbow", 40, 0.20),
        ("head_tilt", -12, 0.25), ("head_pan", 12, 0.25),
        ("l_shoulder_roll", 5, 0.30), ("r_shoulder_roll", 5, 0.30),
        ("l_elbow", 15, 0.25), ("r_elbow", 15, 0.25),
        ("head_tilt", 0, 0.25), ("head_pan", 0, 0.25),
    ],
    "dance": [
        ("r_shoulder_pitch", 140, 0.22), ("l_shoulder_pitch", 20, 0.22),
        ("r_shoulder_roll", 35, 0.20), ("l_shoulder_roll", 15, 0.20),
        ("head_pan", -25, 0.20), ("head_tilt", 12, 0.20),
        ("r_shoulder_pitch", 20, 0.22), ("l_shoulder_pitch", 140, 0.22),
        ("r_shoulder_roll", 15, 0.20), ("l_shoulder_roll", 35, 0.20),
        ("head_pan", 25, 0.20), ("head_tilt", -10, 0.20),
        ("r_elbow", 90, 0.20), ("l_elbow", 90, 0.20),
        ("r_shoulder_pitch", 120, 0.22), ("l_shoulder_pitch", 120, 0.22),
        ("head_pan", 0, 0.20), ("head_tilt", 15, 0.20),
        ("r_shoulder_pitch", 0, 0.25), ("l_shoulder_pitch", 0, 0.25),
        ("r_shoulder_roll", 5, 0.20), ("l_shoulder_roll", 5, 0.20),
        ("r_elbow", 15, 0.20), ("l_elbow", 15, 0.20),
        ("head_tilt", 0, 0.20),
    ],
    "sit": [
        ("body_y", -0.08, 0.30), ("l_hip", 85, 0.30), ("r_hip", 85, 0.30),
        ("l_knee", 85, 0.30), ("r_knee", 85, 0.30),
        ("l_shoulder_pitch", 20, 0.30), ("r_shoulder_pitch", 20, 0.30),
        ("head_tilt", 5, 1.2),
        ("body_y", 0.0, 0.35), ("l_hip", 0, 0.35), ("r_hip", 0, 0.35),
        ("l_knee", 0, 0.35), ("r_knee", 0, 0.35),
        ("l_shoulder_pitch", 0, 0.35), ("r_shoulder_pitch", 0, 0.35),
        ("head_tilt", 0, 0.20),
    ],
    "jump": [
        ("body_y", -0.04, 0.15), ("l_knee", 35, 0.15), ("r_knee", 35, 0.15),
        ("body_y", 0.18, 0.22), ("l_shoulder_pitch", 130, 0.22), ("r_shoulder_pitch", 130, 0.22),
        ("l_knee", 10, 0.20), ("r_knee", 10, 0.20),
        ("body_y", 0.0, 0.20), ("l_knee", 25, 0.15), ("r_knee", 25, 0.15),
        ("l_shoulder_pitch", 0, 0.25), ("r_shoulder_pitch", 0, 0.25),
        ("l_knee", 0, 0.20), ("r_knee", 0, 0.20),
    ],
    "climb": [
        ("body_y", 0.05, 0.25), ("l_hip", 60, 0.25), ("l_knee", 60, 0.25),
        ("l_shoulder_pitch", 80, 0.25), ("r_shoulder_pitch", 80, 0.25),
        ("body_y", 0.14, 0.30), ("r_hip", 60, 0.25), ("r_knee", 60, 0.25),
        ("body_y", 0.22, 0.35), ("l_hip", 0, 0.25), ("r_hip", 0, 0.25),
        ("l_knee", 0, 0.25), ("r_knee", 0, 0.25),
        ("l_shoulder_pitch", 0, 0.25), ("r_shoulder_pitch", 0, 0.25),
        ("head_pan", -15, 0.20), ("head_pan", 15, 0.20), ("head_pan", 0, 0.20),
        ("body_y", 0.0, 0.30),
    ],
}


class AriaSim:
    def __init__(self, robot_id: str, broker: str, port: int) -> None:
        self.robot_id = robot_id
        self.broker = broker
        self.port = port

        self.drive = DriveState()
        self.joints: dict[str, float] = dict(REST_POSE)
        self.joint_target: dict[str, float] = dict(REST_POSE)

        self.state = "idle"
        self.emotion = "neutral"
        self.battery = 1.0
        self.estopped = False

        self.waypoints: list[tuple[float, float]] = []
        self.wp_index = 0
        self.speed = 0.30
        self.current_command_id: str | None = None
        self.turn_target: float | None = None

        self._gesture: list[tuple[str, float, float]] = []
        self._gesture_until = 0.0
        self._hold_until = 0.0
        self._walk_phase = 0.0
        self._seq = 0
        self._running = True
        self._lock = threading.Lock()

        self.client = self._make_client()

    # ── MQTT ──

    def _make_client(self) -> mqtt.Client:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"aria-sim-{self.robot_id}")
        # LWT: the broker announces us offline if we die without saying goodbye,
        # which is how the backend watchdog notices in under 5 s (spec 8.5).
        c.will_set(
            f"room/status/{self.robot_id}",
            json.dumps({"online": False}), qos=1, retain=True,
        )
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        return c

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc != 0:
            log.error("broker refused connection: %s", rc)
            return
        # Subscribe HERE so a reconnect restores everything (spec 18.3).
        client.subscribe(f"room/cmd/{self.robot_id}", qos=1)
        client.subscribe(f"room/cmd/{self.robot_id}/estop", qos=0)
        client.subscribe(f"room/path/{self.robot_id}", qos=1)
        client.publish(
            f"room/status/{self.robot_id}",
            json.dumps({"online": True, "fw": FIRMWARE_VERSION, "caps": CAPABILITIES}),
            qos=1, retain=True,
        )
        log.info("ARIA sim online (broker %s:%s)", self.broker, self.port)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("dropping non-JSON on %s", msg.topic)
            return

        with self._lock:
            if msg.topic.endswith("/estop"):
                # stop=false releases the latch (spec 8.5). Without a release path
                # the robot stays frozen for the rest of the session.
                if payload.get("stop", True):
                    self._handle_estop()
                else:
                    self._clear_estop()
            elif msg.topic == f"room/path/{self.robot_id}":
                self._handle_path(payload)
            else:
                self._handle_command(payload)

    def _ack(self, command_id: str | None, status: str, reason: str = "") -> None:
        if not command_id:
            return
        self.client.publish(
            f"room/ack/{self.robot_id}",
            json.dumps({"command_id": command_id, "status": status, "reason": reason}),
            qos=1,
        )

    def _event(self, type_: str, data: dict) -> None:
        self.client.publish(
            f"room/event/{self.robot_id}",
            json.dumps({"type": type_, "data": data}), qos=1,
        )

    # ── command handling ──

    def _handle_estop(self) -> None:
        self.estopped = True
        self.state = "estop"
        self.emotion = "alert"
        halt(self.drive)
        self.waypoints.clear()
        self.wp_index = 0
        self._gesture.clear()
        self.turn_target = None
        # Servos HOLD their last position - a limp humanoid drops its arms and
        # can strip a gear on the way down (spec P7).
        self.joint_target = dict(self.joints)
        self._ack(self.current_command_id, "failed", "estop")
        self.current_command_id = None
        log.warning("E-STOP - halted, joints holding")

    def _clear_estop(self) -> None:
        if not self.estopped:
            return
        self.estopped = False
        self.state = "idle"
        self.emotion = "neutral"
        # Return to the rest pose rather than resuming: whatever ARIA was mid-way
        # through is stale, and silently continuing an interrupted motion after an
        # emergency stop is exactly the wrong instinct.
        self.joint_target = dict(REST_POSE)
        log.info("e-stop released - returning to rest pose")

    def _handle_path(self, payload: dict) -> None:
        if self.estopped:
            self._ack(payload.get("command_id"), "rejected", "estopped")
            return
        self.waypoints = [(float(x), float(z)) for x, z in payload.get("waypoints", [])]
        self.wp_index = 0
        self.speed = float(payload.get("speed", 0.30))
        self.current_command_id = payload.get("command_id")
        self.state = "driving" if self.waypoints else "idle"
        self._walk_phase = 0.0
        self._ack(self.current_command_id, "accepted")
        log.info("path accepted: %d waypoints @ %.2f m/s",
                 len(self.waypoints), self.speed)

    def _handle_command(self, cmd: dict) -> None:
        action = cmd.get("action")
        cid = cmd.get("id")
        params = cmd.get("params") or {}

        if action == "reset_pose":
            # Internal, not a user capability: switching to a room ARIA has
            # never been given a command in re-parks her at that room's dock
            # instead of leaving her rendered wherever her last command left
            # her in a DIFFERENT room's coordinate space, which lines up with
            # nothing in the new layout. An instant snap, not a walk - there
            # is no "previous position in this room" to walk from.
            x, z = float(params.get("x", 0.0)), float(params.get("z", 0.0))
            yaw = float(params.get("yaw", 0.0))
            halt(self.drive)
            self.drive.x, self.drive.z, self.drive.yaw = x, z, yaw
            self.waypoints.clear()
            self.wp_index = 0
            self.turn_target = None
            self._gesture.clear()
            self.joints = dict(REST_POSE)
            self.joint_target = dict(REST_POSE)
            self.state = "idle"
            return

        if self.estopped and action != "stop":
            self._ack(cid, "rejected", "estopped")
            return
        if action not in CAPABILITIES:
            self._ack(cid, "rejected", "unsupported_capability")
            return

        self.current_command_id = cid
        self._ack(cid, "accepted")

        if action == "stop":
            self._handle_estop()
            return

        # The backend pre-solves joints for look_at/point_at, but the sim solves
        # them itself when given only a raw target - same as the MCU does, so a
        # dropped link can't leave an arm stuck mid-point (spec 12.4 MSG_GAZE).
        if action in ("look_at", "point_at", "locate"):
            joints = params.get("joints")
            if not joints and "point" in params:
                pose = Pose(self.drive.x, 0.0, self.drive.z, self.drive.yaw)
                tgt = tuple(params["point"])
                if action == "look_at":
                    r = solve_look_at(pose, tgt)
                    joints = {"head_pan": r.head_pan, "head_tilt": r.head_tilt}
                else:
                    p = solve_point_at(pose, tgt)
                    joints = dict(p.joints)
                    if p.look:
                        joints |= {"head_pan": p.look.head_pan,
                                   "head_tilt": p.look.head_tilt}
            if joints:
                # Clamp on arrival: never trust the network to respect a limit.
                self.joint_target |= clamp_pose(joints)
                self.state = "pointing" if action == "point_at" else "looking"
            if turn := params.get("base_turn_deg"):
                self.turn_target = wrap(self.drive.yaw + math.radians(turn))
            self._finish_after(1.5)
            return

        if action == "turn":
            deg = float(params.get("degrees", 90))
            self.turn_target = wrap(self.drive.yaw + math.radians(deg))
            self.state = "turning"
            return

        if action == "set_speed":
            self.speed = float(params.get("mps", self.speed))
            self._ack(cid, "done")
            return

        if action == "express":
            self.emotion = params.get("emotion", "neutral")
            self._ack(cid, "done")
            return

        if action in ("wave", "nod", "shake_head", "dance", "gesture", "sit", "jump", "climb"):
            name = params.get("name", action) if action == "gesture" else action
            self._start_gesture(name)
            return

        if action == "report_battery":
            self._event("battery", {"level": self.battery})
            self._ack(cid, "done")
            return

        if action == "photo":
            self._event("photo", {"url": f"/api/v1/robots/{self.robot_id}/photos/sim.jpg"})
            self._ack(cid, "done")
            return

        # Everything else is acknowledged as an immediate no-op in sim.
        self._ack(cid, "done")

    def _start_gesture(self, name: str) -> None:
        keys = GESTURES.get(name)
        if not keys:
            self._ack(self.current_command_id, "rejected", f"unknown gesture '{name}'")
            return
        self._gesture = list(keys)
        self._gesture_until = 0.0
        self.state = "gesturing"

    def _finish_after(self, seconds: float) -> None:
        self._hold_until = time.time() + seconds

    # ── simulation tick ──

    def tick(self, dt: float) -> None:
        with self._lock:
            now = time.time()

            if not self.estopped:
                if self.turn_target is not None:
                    if turn_towards(self.drive, self.turn_target, dt):
                        self.turn_target = None
                        if self.state == "turning":
                            self._done()
                elif self.waypoints:
                    self._drive_tick(dt)

                self._gesture_tick(now)

                if self._hold_until and now >= self._hold_until:
                    self._hold_until = 0.0
                    self._done()

            # Joints always slew toward their target, even while e-stopped (the
            # target is frozen to the current pose, so they simply hold).
            self.joints = slew(self.joints, self.joint_target, dt)

            # Battery drain, expressed per SECOND and integrated with dt.
            # (Multiplying by dt *and* TICK_HZ cancels them out and gives a
            # per-tick drain 50x too fast - that flattened the pack in ~30 min
            # of idling and made ARIA look dead an hour into a work session.)
            per_s = DRAIN_DRIVING_PER_S if self.drive.v > 0.01 else DRAIN_IDLE_PER_S
            self.battery = max(0.0, self.battery - per_s * dt)

    def _drive_tick(self, dt: float) -> None:
        goal = self.waypoints[self.wp_index]
        arrived = step_towards(self.drive, goal, dt, self.speed)
        self._walk_gait_tick(dt)
        if arrived:
            self.wp_index += 1
            if self.wp_index >= len(self.waypoints):
                self.waypoints.clear()
                self.wp_index = 0
                self.state = "idle"
                self._settle_gait()
                self._event("arrived", {"x": round(self.drive.x, 3),
                                        "z": round(self.drive.z, 3)})
                self._done()
        else:
            self.state = "driving"

    def _walk_gait_tick(self, dt: float) -> None:
        """Swing hips/knees/arms in sync with ground speed, so driving reads as
        walking rather than the whole body sliding across the floor with the
        legs frozen in rest pose. A gesture already in flight (sit, climb, ...)
        owns the same joints, so it gets priority - the gait resumes on its own
        the next tick after the gesture releases them."""
        if self._gesture:
            return
        speed = abs(self.drive.v)
        if speed <= WALK_MOVING_THRESHOLD:
            self._settle_gait()
            return
        self._walk_phase = (self._walk_phase + (speed / WALK_STRIDE_M) * dt) % 1.0
        phase = self._walk_phase * 2 * math.pi
        self.joint_target["l_hip"] = HIP_SWING_DEG * math.sin(phase)
        self.joint_target["r_hip"] = -HIP_SWING_DEG * math.sin(phase)
        self.joint_target["l_knee"] = KNEE_LIFT_DEG * max(0.0, math.sin(phase + math.pi))
        self.joint_target["r_knee"] = KNEE_LIFT_DEG * max(0.0, math.sin(phase))
        self.joint_target["l_shoulder_pitch"] = -ARM_SWING_DEG * math.sin(phase)
        self.joint_target["r_shoulder_pitch"] = ARM_SWING_DEG * math.sin(phase)

    def _settle_gait(self) -> None:
        """Ease legs and arms back to the rest pose - used both when she comes
        to a stop mid-tick and right on arrival, so she never freezes mid-stride."""
        for key in ("l_hip", "r_hip", "l_knee", "r_knee",
                    "l_shoulder_pitch", "r_shoulder_pitch"):
            self.joint_target[key] = REST_POSE[key]

    def _gesture_tick(self, now: float) -> None:
        if not self._gesture:
            return
        if now < self._gesture_until:
            return
        joint, deg, hold = self._gesture.pop(0)
        self.joint_target[joint] = deg
        self._gesture_until = now + hold
        if not self._gesture:
            self.joint_target |= {k: REST_POSE[k] for k in REST_POSE}
            self._finish_after(0.4)

    def _done(self) -> None:
        if self.current_command_id:
            self._ack(self.current_command_id, "done")
            self.current_command_id = None
        if self.state != "estop":
            self.state = "idle"

    # ── telemetry ──

    def telemetry(self) -> dict:
        self._seq += 1
        return {
            "robot_id": self.robot_id,
            "ts": time.time(),
            "seq": self._seq,
            "pose": {
                "x": round(self.drive.x, 4), "y": 0.0,
                "z": round(self.drive.z, 4), "yaw": round(self.drive.yaw, 4),
            },
            "vel": {"linear": round(self.drive.v, 4),
                    "angular": round(self.drive.w, 4)},
            "joints": {k: round(v, 2) for k, v in self.joints.items()},
            "emotion": self.emotion,
            "state": self.state,
            "battery": round(self.battery, 4),
            "current_command_id": self.current_command_id,
            "progress": (self.wp_index / len(self.waypoints)) if self.waypoints else 0.0,
            "sensors": {
                "ultrasonic_cm": [120.0, 120.0],
                "ir": [False, False],
                "imu": {"roll": 0.0, "pitch": 0.0, "yaw": round(self.drive.yaw, 4),
                        "ax": 0.0, "ay": 0.0, "az": 9.81},
                "encoders": [0, 0],
            },
            "errors": [],
        }

    # ── main loop ──

    def run(self) -> None:
        self.client.connect(self.broker, self.port, keepalive=15)
        self.client.loop_start()

        tick_dt = 1.0 / TICK_HZ
        telem_every = int(TICK_HZ / TELEMETRY_HZ)
        n = 0
        next_t = time.perf_counter()

        try:
            while self._running:
                self.tick(tick_dt)
                n += 1
                if n % telem_every == 0:
                    self.client.publish(
                        f"room/telemetry/{self.robot_id}",
                        json.dumps(self.telemetry()), qos=0,
                    )
                next_t += tick_dt
                time.sleep(max(0.0, next_t - time.perf_counter()))
        finally:
            self.client.publish(
                f"room/status/{self.robot_id}",
                json.dumps({"online": False}), qos=1, retain=True,
            )
            time.sleep(0.2)
            self.client.loop_stop()
            self.client.disconnect()
            log.info("ARIA sim stopped")

    def stop(self, *_: object) -> None:
        self._running = False


def main() -> int:
    ap = argparse.ArgumentParser(description="ARIA robot simulator")
    ap.add_argument("--robot", default="aria")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--battery", type=float, default=1.0,
                    help="starting charge 0..1 (use 0.15 to rehearse the low-battery path)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    sim = AriaSim(args.robot, args.broker, args.port)
    sim.battery = max(0.0, min(1.0, args.battery))
    signal.signal(signal.SIGINT, sim.stop)
    signal.signal(signal.SIGTERM, sim.stop)
    sim.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
