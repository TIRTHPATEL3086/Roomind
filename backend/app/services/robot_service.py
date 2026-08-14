"""Robot Manager (spec 9.9): ARIA's state machine, command queue and dispatch.

Lifecycle: queued -> planning -> dispatched -> executing -> succeeded|failed|cancelled|rejected

`stop` is priority 10: it clears the queue and goes straight out on the e-stop topic,
bypassing everything below.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.config import get_settings
from app.core.errors import NoPathFound, NotFound, RoomMindError, Unsafe
from app.core.events import bus
from app.core.kinematics import Pose, solve_look_at, solve_point_at
from app.services.mqtt_service import mqtt_service
from app.services.planner_service import planner_service
from app.services.safety_service import safety_service
from app.services.scene_service import scene_service

log = logging.getLogger("roommind.robot")

WATCHDOG_TIMEOUT_S = 3.0
TELEMETRY_STALE_S = 3.0

# Which actions need a path planned before dispatch.
NAVIGATING = {"navigate", "come_here", "dock", "present"}
# Which actions aim a joint at a target.
AIMING = {"look_at", "point_at", "present", "locate"}

# Every action in the frozen enum must appear here, or test_every_action_is_handled
# fails. That test exists to stop the schema and the dispatcher drifting apart.
ACTION_HANDLERS: dict[str, str] = {
    "navigate": "_do_navigate",
    "come_here": "_do_navigate",
    "dock": "_do_navigate",
    "present": "_do_present",
    "stop": "_do_stop",
    "follow_me": "_do_simple",
    "turn": "_do_simple",
    "set_speed": "_do_simple",
    "look_at": "_do_aim",
    "point_at": "_do_aim",
    "locate": "_do_aim",
    "wave": "_do_simple",
    "nod": "_do_simple",
    "shake_head": "_do_simple",
    "gesture": "_do_simple",
    "express": "_do_simple",
    "dance": "_do_simple",
    "scan_area": "_do_simple",
    "remember_spot": "_do_simple",
    "photo": "_do_simple",
    "report_battery": "_do_simple",
    "imagine": "_do_imagine",
}


class RobotService:
    def __init__(self) -> None:
        s = get_settings()
        self.robot_id = s.robot_id
        self.state: dict = {
            "id": s.robot_id,
            "display_name": s.robot_display_name,
            "accent_color": s.robot_accent,
            "kind": "humanoid",
            "online": False,
            "battery": 1.0,
            "pose": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0},
            "joints": {},
            "emotion": "neutral",
            "state": "idle",
            "current_command_id": None,
            "capabilities": [],
        }
        self.commands: dict[str, dict] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._last_telemetry: float | None = None
        self._scene_graph: dict | None = None
        self._seq = 0
        self._worker: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None

    # ── lifecycle ──

    async def bootstrap(self, capabilities: list[str], scene_graph: dict | None = None) -> None:
        self.state["capabilities"] = capabilities
        self._scene_graph = scene_graph
        mqtt_service.on("room/telemetry/+", self.on_telemetry)
        mqtt_service.on("room/status/+", self.on_status)
        mqtt_service.on("room/ack/+", self.on_ack)
        mqtt_service.on("room/event/+", self.on_event)
        self._watchdog = asyncio.create_task(self.watchdog_loop())

    async def shutdown(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()

    def set_scene_graph(self, graph: dict) -> None:
        self._scene_graph = graph

    def graph_for(self, room_id: str | None) -> dict | None:
        """The scene graph a command should be planned against.

        A command carries the room it was issued for, and planning has to use
        THAT room. This service holds one graph — whichever was installed at
        bootstrap or by the last scan — and using it unconditionally means a
        command for a second room plans against the first one's furniture.

        That failure is silent and worse than a crash: two rooms both contain a
        `chair_02`, so "go to the red chair" in the multi-instance room resolved
        correctly, planned a route through a completely different room's
        obstacles, and reported success. Nothing anywhere said the two graphs
        disagreed.

        Falls back to the installed graph when the room is unknown, so
        single-room callers and commands with no room_id behave exactly as
        before.
        """
        if room_id:
            try:
                return scene_service.get(room_id)
            except RoomMindError:
                log.warning("command names room '%s', which is not loaded - "
                            "planning against the active graph instead", room_id)
        return self._scene_graph

    # ── public API ──

    def get(self) -> dict:
        return dict(self.state)

    def all(self) -> list[dict]:
        """Array of one. Kept plural so the frontend shape never has to change."""
        return [self.get()]

    async def enqueue(self, command: dict, room_id: str | None = None,
                      source: str = "api") -> dict:
        action = command.get("action")
        if action not in ACTION_HANDLERS:
            raise NotFound(f"unknown action '{action}'")

        safety_service.check_not_estopped(action)
        safety_service.check_capability(action, self.state["capabilities"])

        self._seq += 1
        record = {
            "id": command.get("id") or str(uuid.uuid4()),
            "room_id": room_id,
            "robot_id": self.robot_id,
            "action": action,
            "target": command.get("target"),
            "params": command.get("params") or {},
            "priority": 10 if action == "stop" else command.get("priority", 5),
            "seq": self._seq,
            "status": "queued",
            "reason": None,
            "path": None,
            "source": source,
            "issued_at": time.time(),
        }
        self.commands[record["id"]] = record

        await bus.publish("command.created", {
            "command_id": record["id"], "action": action,
            "target": record["target"], "robot_id": self.robot_id,
            "room_id": room_id,
        })

        # Run the handler INLINE rather than via the background worker.
        #
        # Planning is sub-millisecond, and doing it synchronously means the caller
        # learns immediately whether the target was reachable - POST /commands
        # returns the actual path, and an unknown id comes back as a rejection
        # instead of a 200 the client has to poll to discover was a lie.
        #
        # FIFO order still holds: handlers are awaited sequentially on one event
        # loop. Serialising *robot* execution is the ack cycle's job, not ours.
        handler = getattr(self, ACTION_HANDLERS[action])
        try:
            await handler(record)
        except RoomMindError as e:
            await self._set_status(record, "rejected", f"{e.reason}: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("command handler failed: %s", action)
            await self._set_status(record, "failed", repr(e))
        return record

    async def cancel(self, command_id: str) -> None:
        cmd = self.commands.get(command_id)
        if not cmd:
            raise NotFound(f"unknown command '{command_id}'")
        if cmd["status"] in ("succeeded", "failed", "cancelled"):
            return
        await self._set_status(cmd, "cancelled")

    async def estop(self) -> float:
        """Publish the stop, then return. Bookkeeping happens off the response path.

        Everything after the publish - cancelling queued commands, WebSocket
        fan-out - is observability, not safety. Awaiting it inline cost ~64 ms on
        Windows (four event-loop yields at the 15.6 ms timer granularity), which
        blew the 50 ms budget on POST /estop for work the robot never waits on.
        """
        latency = safety_service.estop(self.robot_id)   # QoS 0 publish, ~0.3 ms
        self.state["state"] = "estop"
        asyncio.create_task(self._estop_aftermath())
        return latency

    async def _estop_aftermath(self) -> None:
        """Cancel anything pending and tell the UI. Never on the critical path."""
        for cmd in self.commands.values():
            if cmd["status"] in ("queued", "planning", "dispatched", "executing"):
                await self._set_status(cmd, "cancelled", "estop")
        await bus.publish("robot.status", {
            "robot_id": self.robot_id, "state": "estop",
            "online": self.state["online"], "battery": self.state["battery"],
        })
        await bus.publish("alert", {"level": "warn", "message": "Emergency stop engaged"})

    # ── action handlers ──

    async def _do_navigate(self, cmd: dict) -> None:
        graph = self.graph_for(cmd.get("room_id"))
        if not graph:
            raise Unsafe("no scene graph loaded - cannot plan")
        await self._set_status(cmd, "planning")

        pose = self.state["pose"]
        start = (pose["x"], pose["z"])
        target, params = cmd["target"], cmd["params"]
        if cmd["action"] == "dock":
            dock = graph.get("robot_dock", [0, 0, 0])
            params = {"point": [dock[0], dock[2]]}
            target = None
        elif cmd["action"] == "come_here" and "user_pos" in params:
            params = {"point": params["user_pos"]}
            target = None

        try:
            path = planner_service.plan_path(
                graph, start, target, params, self.robot_id
            )
        except (NoPathFound, NotFound) as e:
            await self._set_status(cmd, "rejected", str(e))
            return

        cmd["path"] = [[round(x, 4), round(z, 4)] for x, z in path]
        await bus.publish("command.planned", {
            "command_id": cmd["id"], "robot_id": self.robot_id,
            "path": cmd["path"], "room_id": cmd["room_id"],
        })

        speed = safety_service.clamp_speed(cmd["params"].get("speed", 0.30))
        mqtt_service.publish_path(self.robot_id, cmd["id"], path, speed)
        await self._set_status(cmd, "dispatched")

    async def _do_aim(self, cmd: dict) -> None:
        """look_at / point_at / locate - solve the joints, then dispatch them."""
        graph = self.graph_for(cmd.get("room_id"))
        if not graph:
            raise Unsafe("no scene graph loaded - cannot aim")
        tx, ty, tz = planner_service.resolve_target(
            graph, cmd["target"], cmd["params"]
        )
        p = self.state["pose"]
        pose = Pose(p["x"], p["y"], p["z"], p["yaw"])

        if cmd["action"] == "look_at":
            r = solve_look_at(pose, (tx, ty, tz))
            joints = {"head_pan": r.head_pan, "head_tilt": r.head_tilt}
            base_turn = r.base_turn_needed
        else:
            r2 = solve_point_at(pose, (tx, ty, tz))
            joints = dict(r2.joints)
            if r2.look:
                joints["head_pan"] = r2.look.head_pan
                joints["head_tilt"] = r2.look.head_tilt
                base_turn = r2.look.base_turn_needed
            else:
                base_turn = 0.0

        cmd["params"] = {**cmd["params"], "joints": joints, "base_turn_deg": base_turn}
        mqtt_service.publish_command(self.robot_id, {
            "id": cmd["id"], "action": cmd["action"], "target": cmd["target"],
            "params": cmd["params"], "robot_id": self.robot_id, "seq": cmd["seq"],
        })
        await self._set_status(cmd, "dispatched")

    async def _do_present(self, cmd: dict) -> None:
        """The signature composite (spec 8.3.1): navigate -> face -> look -> point -> speak.
        Sequenced here on the orchestration side so the MCU loop stays simple."""
        await self._do_navigate(cmd)
        if cmd["status"] == "rejected":
            return
        await self._do_aim({**cmd, "action": "point_at"})
        await bus.publish("companion.speak", {
            "text": f"Here it is - {cmd['target']}.", "room_id": cmd["room_id"],
        })

    async def _do_stop(self, cmd: dict) -> None:
        await self.estop()
        # Mark succeeded directly: _estop_aftermath cancels everything *else*, and
        # racing it would flip this command to "cancelled" a moment after it won.
        cmd["status"] = "succeeded"
        await bus.publish("command.status", {
            "command_id": cmd["id"], "status": "succeeded", "room_id": cmd.get("room_id"),
        })

    async def _do_simple(self, cmd: dict) -> None:
        """Pass-through actions the MCU executes directly."""
        if cmd["action"] == "set_speed":
            cmd["params"]["mps"] = safety_service.clamp_speed(
                float(cmd["params"].get("mps", 0.30))
            )
        mqtt_service.publish_command(self.robot_id, {
            "id": cmd["id"], "action": cmd["action"], "target": cmd["target"],
            "params": cmd["params"], "robot_id": self.robot_id, "seq": cmd["seq"],
        })
        await self._set_status(cmd, "dispatched")

    async def _do_imagine(self, cmd: dict) -> None:
        """Hands off to the Imagine Manager (Phase 3b). Acks immediately; the result
        arrives later as imagine.completed."""
        await self._set_status(cmd, "dispatched", "handed to imagine manager")

    # ── MQTT inbound ──

    async def on_telemetry(self, topic: str, payload: dict) -> None:
        self._last_telemetry = time.time()
        self.state["online"] = True
        for k in ("pose", "joints", "state", "battery", "emotion"):
            if k in payload:
                self.state[k] = payload[k]
        await bus.publish("robot.telemetry", payload)
        if "joints" in payload:
            await bus.publish("robot.joints", {
                "joints": payload["joints"], "emotion": payload.get("emotion", "neutral"),
            })

    async def on_status(self, topic: str, payload: dict) -> None:
        self.state["online"] = bool(payload.get("online", False))
        if caps := payload.get("caps"):
            self.state["capabilities"] = caps
        await bus.publish("robot.status", {
            "robot_id": self.robot_id,
            "online": self.state["online"],
            "battery": self.state["battery"],
        })

    async def on_ack(self, topic: str, payload: dict) -> None:
        cmd = self.commands.get(payload.get("command_id", ""))
        if not cmd:
            return
        mapping = {
            "accepted": "executing", "done": "succeeded",
            "failed": "failed", "rejected": "rejected",
        }
        if new := mapping.get(payload.get("status", "")):
            await self._set_status(cmd, new, payload.get("reason"))

    async def on_event(self, topic: str, payload: dict) -> None:
        await bus.publish("alert", {
            "level": "info", "message": f"{payload.get('type')}: {payload.get('data')}"
        })

    # ── watchdog ──

    async def watchdog_loop(self) -> None:
        """No telemetry for 3 s -> mark offline, cancel the running command, alert."""
        while True:
            await asyncio.sleep(1.0)
            if not self.state["online"] or self._last_telemetry is None:
                continue
            if time.time() - self._last_telemetry > TELEMETRY_STALE_S:
                self.state["online"] = False
                self.state["state"] = "error"
                log.warning("watchdog: no telemetry for %.1fs - ARIA marked offline",
                            TELEMETRY_STALE_S)
                cid = self.state.get("current_command_id")
                if cid and (c := self.commands.get(cid)):
                    await self._set_status(c, "failed", "robot went offline")
                await bus.publish("robot.status", {
                    "robot_id": self.robot_id, "online": False,
                    "battery": self.state["battery"],
                })
                await bus.publish("alert", {
                    "level": "error", "message": "ARIA is offline (no telemetry)"
                })

    # ── helpers ──

    async def _set_status(self, cmd: dict, status: str, reason: str | None = None) -> None:
        cmd["status"] = status
        if reason:
            cmd["reason"] = reason
        if status in ("dispatched", "executing"):
            self.state["current_command_id"] = cmd["id"]
        elif status in ("succeeded", "failed", "cancelled", "rejected"):
            if self.state.get("current_command_id") == cmd["id"]:
                self.state["current_command_id"] = None
        await bus.publish("command.status", {
            "command_id": cmd["id"], "status": status,
            "reason": reason, "room_id": cmd.get("room_id"),
        })


robot_service = RobotService()
