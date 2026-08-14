"""Command pipeline tests (spec 14.2).

Runs against the real RobotService with no MQTT broker and no DB - publishes are
no-ops when the client can't connect, which is exactly what we want to test the
orchestration logic in isolation.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.core.errors import UnsupportedCapability, Unsafe
from app.services.robot_service import ACTION_HANDLERS, RobotService
from app.services.safety_service import safety_service

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = json.loads((ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))
SCHEMA = json.loads(
    (ROOT / "contracts" / "command.schema.json").read_text(encoding="utf-8")
)
ALL_ACTIONS = SCHEMA["properties"]["action"]["enum"]


@pytest.fixture
def robot() -> RobotService:
    safety_service.clear_estop()
    r = RobotService()
    r.state["capabilities"] = list(ALL_ACTIONS)
    r.state["online"] = True
    r.set_scene_graph(DEMO)
    return r


async def run(robot: RobotService, cmd: dict) -> dict:
    """enqueue() runs the handler inline, so the record is already resolved."""
    return await robot.enqueue(cmd)


async def test_enqueue_resolves_before_returning(robot: RobotService) -> None:
    """POST /commands must return the real outcome, not 'queued'. A client that
    has to poll to discover its target was unreachable is a broken contract."""
    rec = await robot.enqueue({"action": "navigate", "target": "table_01"})
    assert rec["status"] != "queued"
    assert rec["path"]


# ── the dispatcher must never drift from the frozen enum ──

def test_every_action_in_the_enum_is_handled() -> None:
    missing = [a for a in ALL_ACTIONS if a not in ACTION_HANDLERS]
    assert not missing, f"actions in the schema with no handler: {missing}"


def test_no_handler_for_an_action_outside_the_enum() -> None:
    extra = [a for a in ACTION_HANDLERS if a not in ALL_ACTIONS]
    assert not extra, f"handlers for actions not in the schema: {extra}"


# ── navigation ──

async def test_navigate_plans_a_path(robot: RobotService) -> None:
    rec = await run(robot, {"action": "navigate", "target": "table_01"})
    assert rec["status"] == "dispatched"
    assert rec["path"], "navigate produced no path"
    assert len(rec["path"][0]) == 2


async def test_navigate_stops_short_of_the_target(robot: RobotService) -> None:
    """ARIA comes to rest a safe gap from the furniture's SURFACE.

    Measured against the footprint, not against the centre. The old assertion
    took the distance to the object's centre, which only looked correct because
    the demo table is small: 0.6 m from the centre of the 1.9 m sofa is a third
    of a metre INSIDE it, so the same check would have passed a path that drove
    straight through the arm rest.
    """
    from app.core import spatial
    from app.services.planner_service import approach_distance

    rec = await run(robot, {"action": "navigate", "target": "table_01"})
    table = next(o for o in DEMO["objects"] if o["id"] == "table_01")
    ex, ez = rec["path"][-1]

    stop = {"position": [ex, 0.0, ez], "dimensions": [0.001, 0.001, 0.001],
            "rotation_y": 0.0}
    gap = spatial.surface_gap(stop, table)
    assert gap >= approach_distance() - 0.05, f"stopped {gap:.2f} m from the table"
    assert gap <= 0.90, f"stopped {gap:.2f} m away - too far to be 'at' the table"


async def test_navigate_to_a_waypoint(robot: RobotService) -> None:
    rec = await run(robot, {"action": "navigate", "target": "reading_corner"})
    assert rec["status"] == "dispatched"
    assert rec["path"]


async def test_navigate_to_an_unknown_target_is_rejected(robot: RobotService) -> None:
    """The LLM may only cite ids that exist - a miss must be visible, not silent."""
    rec = await run(robot, {"action": "navigate", "target": "unicorn_99"})
    assert rec["status"] == "rejected"
    assert "unicorn_99" in rec["reason"]


async def test_dock_targets_the_robot_dock(robot: RobotService) -> None:
    import math

    rec = await run(robot, {"action": "dock"})
    assert rec["status"] == "dispatched"
    dock = DEMO["robot_dock"]
    ex, ez = rec["path"][-1]
    assert math.hypot(ex - dock[0], ez - dock[2]) < 0.8


# ── aiming: the signature behaviour ──

async def test_look_at_solves_head_joints(robot: RobotService) -> None:
    rec = await run(robot, {"action": "look_at", "target": "lamp_01"})
    assert rec["status"] == "dispatched"
    joints = rec["params"]["joints"]
    assert set(joints) == {"head_pan", "head_tilt"}


async def test_point_at_solves_an_arm_and_the_head(robot: RobotService) -> None:
    """point_at must always move the head too, or ARIA points one way and faces another."""
    rec = await run(robot, {"action": "point_at", "target": "lamp_01"})
    joints = rec["params"]["joints"]
    assert "head_pan" in joints and "head_tilt" in joints
    assert any(k.endswith("_shoulder_pitch") for k in joints)
    assert any(k.endswith("_elbow") for k in joints)


async def test_point_at_picks_the_correct_side(robot: RobotService) -> None:
    """lamp_01 is at x=-2.10; from the dock facing +Z that is ARIA's left."""
    rec = await run(robot, {"action": "point_at", "target": "lamp_01"})
    assert any(k.startswith("l_") for k in rec["params"]["joints"])


async def test_all_dispatched_joints_are_within_limits(robot: RobotService) -> None:
    from app.core.kinematics import LIMITS

    for obj in DEMO["objects"]:
        rec = await run(robot, {"action": "point_at", "target": obj["id"]})
        for name, v in rec["params"]["joints"].items():
            lo, hi = LIMITS[name]
            assert lo <= v <= hi, f"{obj['id']}: {name}={v} outside [{lo},{hi}]"


# ── safety ──

async def test_stop_is_priority_10(robot: RobotService) -> None:
    rec = await robot.enqueue({"action": "stop"})
    assert rec["priority"] == 10
    assert rec["status"] == "succeeded"      # executed immediately, never queued


async def test_estop_latches_and_blocks_other_commands(robot: RobotService) -> None:
    await robot.enqueue({"action": "stop"})
    with pytest.raises(Unsafe):
        await robot.enqueue({"action": "navigate", "target": "table_01"})
    safety_service.clear_estop()
    rec = await run(robot, {"action": "navigate", "target": "table_01"})
    assert rec["status"] == "dispatched"


async def test_stop_is_allowed_while_already_estopped(robot: RobotService) -> None:
    await robot.enqueue({"action": "stop"})
    rec = await robot.enqueue({"action": "stop"})     # must not raise
    assert rec["status"] == "succeeded"


def test_clearing_estop_also_releases_the_robot(monkeypatch) -> None:
    """Regression: the latch used to be one-way.

    clear_estop() cleared only the backend flag, so the robot stayed frozen while
    the API reported it ready - indistinguishable from dead hardware. The release
    MUST go out on the wire as stop=false.
    """
    from app.services import safety_service as ss

    published: list[tuple[str, dict, int]] = []
    monkeypatch.setattr(
        ss.mqtt_service, "publish",
        lambda topic, payload, qos=None, retain=False:
            published.append((topic, payload, qos)),
    )

    ss.safety_service.estop("aria")
    ss.safety_service.clear_estop("aria")

    assert len(published) == 2, "clear_estop published nothing to the robot"
    stop_topic, stop_payload, stop_qos = published[0]
    clear_topic, clear_payload, clear_qos = published[1]

    assert stop_payload["stop"] is True
    assert stop_qos == 0, "the stop itself must be QoS 0 for lowest latency"
    assert clear_topic == stop_topic, "release must use the same topic (spec 8.5)"
    assert clear_payload["stop"] is False
    assert clear_qos == 1, "the release must not be lost - QoS 1"
    assert ss.safety_service.estopped is False


async def test_missing_capability_is_rejected(robot: RobotService) -> None:
    robot.state["capabilities"] = ["navigate"]
    with pytest.raises(UnsupportedCapability):
        await robot.enqueue({"action": "dance"})


async def test_set_speed_is_clamped(robot: RobotService) -> None:
    from app.config import get_settings

    rec = await run(robot, {"action": "set_speed", "params": {"mps": 99.0}})
    assert rec["params"]["mps"] == get_settings().max_speed_mps


# ── telemetry ingest ──

async def test_telemetry_updates_pose_and_joints(robot: RobotService) -> None:
    await robot.on_telemetry("room/telemetry/aria", {
        "robot_id": "aria", "ts": 1.0,
        "pose": {"x": 1.0, "y": 0.0, "z": 2.0, "yaw": 0.5},
        "joints": {"head_pan": 12.0},
        "state": "driving", "battery": 0.87, "emotion": "curious",
    })
    assert robot.state["online"] is True
    assert robot.state["pose"]["x"] == 1.0
    assert robot.state["joints"]["head_pan"] == 12.0
    assert robot.state["emotion"] == "curious"


async def test_aiming_accounts_for_the_current_pose(robot: RobotService) -> None:
    """After ARIA moves, the same target must resolve to different joint angles."""
    before = await run(robot, {"action": "look_at", "target": "lamp_01"})
    await robot.on_telemetry("room/telemetry/aria", {
        "robot_id": "aria", "ts": 2.0,
        "pose": {"x": -2.0, "y": 0.0, "z": 1.0, "yaw": 0.0},
        "state": "idle",
    })
    after = await run(robot, {"action": "look_at", "target": "lamp_01"})
    assert before["params"]["joints"]["head_pan"] != after["params"]["joints"]["head_pan"]


async def test_ack_advances_the_command_lifecycle(robot: RobotService) -> None:
    rec = await run(robot, {"action": "navigate", "target": "table_01"})
    await robot.on_ack("room/ack/aria", {"command_id": rec["id"], "status": "accepted"})
    assert robot.commands[rec["id"]]["status"] == "executing"
    await robot.on_ack("room/ack/aria", {"command_id": rec["id"], "status": "done"})
    assert robot.commands[rec["id"]]["status"] == "succeeded"
    assert robot.state["current_command_id"] is None
