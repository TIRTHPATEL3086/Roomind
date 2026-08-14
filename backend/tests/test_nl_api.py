"""The natural-language command surface, over the real ASGI app.

Covers the seam the unit tests cannot: that a sentence arriving over HTTP ends
with ARIA holding a planned path, or with a question — and never with a silent
guess dressed as success.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.enrich import enrich_graph
from app.services.rag_service import rag_service
from app.services.resolver_service import resolver_service
from app.services.robot_service import robot_service
from app.services.safety_service import safety_service
from app.services.scene_service import scene_service

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROOM = "multi_demo"


@pytest.fixture
async def client():
    from main import app

    graph = enrich_graph(json.loads(
        (ROOT / "contracts" / "demo_room_multi.json").read_text(encoding="utf-8")))
    scene_service._graphs[ROOM] = graph
    rag_service.index_room(graph)
    robot_service.set_scene_graph(graph)
    robot_service.state["capabilities"] = [
        "navigate", "look_at", "point_at", "present", "stop", "dock"]
    robot_service.state["online"] = False      # no simulator in the test run
    safety_service.clear_estop()
    resolver_service.clear_pending(ROOM)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def nl(client, text: str) -> dict:
    r = await client.post("/api/v1/commands/nl",
                          json={"room_id": ROOM, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


# ── resolve, without moving anything ──

async def test_resolve_reads_only(client) -> None:
    r = await client.post("/api/v1/resolve",
                          json={"room_id": ROOM, "text": "go to the red chair"})
    body = r.json()
    assert body["status"] == "resolved"
    assert body["target"] == "chair_02"
    assert robot_service.state["current_command_id"] is None


async def test_resolve_reports_the_constraints_it_understood(client) -> None:
    r = await client.post(
        "/api/v1/resolve",
        json={"room_id": ROOM, "text": "go to the black chair near the bed"})
    q = r.json()["query"]
    assert q["class"] == "chair"
    assert q["colors"] == ["black"]
    assert q["relations"] == [{"rel": "near", "class": "bed", "id": None}]


async def test_an_unknown_room_is_a_404(client) -> None:
    r = await client.post("/api/v1/resolve",
                          json={"room_id": "no_such_room", "text": "go to the chair"})
    assert r.status_code == 404


# ── the full chain ──

async def test_a_resolved_command_plans_and_dispatches(client) -> None:
    body = await nl(client, "go to the red chair")
    assert body["status"] == "resolved"
    assert body["target"] == "chair_02"
    assert body["command_status"] == "dispatched"
    assert body["path"] and len(body["path"][0]) == 2


async def test_an_ambiguous_command_asks_and_dispatches_nothing(client) -> None:
    body = await nl(client, "go to the chair")
    assert body["status"] == "clarify"
    assert body["target"] is None
    assert body.get("path") is None
    assert len(body["options"]) == 3
    assert body["command_id"] is None if "command_id" in body else True


async def test_the_answer_to_the_question_moves_her(client) -> None:
    first = await nl(client, "go to the chair")
    assert first["status"] == "clarify"

    second = await nl(client, "the blue one")
    assert second["status"] == "resolved"
    assert second["target"] == "chair_03"
    assert second["path"]


async def test_a_missing_object_says_what_is_there(client) -> None:
    body = await nl(client, "go to the fridge")
    assert body["status"] == "not_found"
    assert "chair" in body["reply"]


async def test_options_carry_what_the_ui_needs_to_render_them(client) -> None:
    body = await nl(client, "go to the chair")
    for option in body["options"]:
        assert option["id"].startswith("chair_")
        assert option["hint"], "an option with no hint is unanswerable out loud"
        assert option["color"], "the demo chairs differ by colour"
        assert len(option["position"]) == 3


# ── chat carries the same behaviour ──

async def test_chat_asks_rather_than_guessing(client) -> None:
    r = await client.post("/api/v1/chat",
                          json={"room_id": ROOM, "message": "go to the chair"})
    body = r.json()
    assert body["clarification"] is not None
    assert len(body["clarification"]["options"]) == 3
    assert not body["commands"], "a question must not also issue a command"


async def test_chat_executes_a_resolved_command(client) -> None:
    """The words claimed an action; the body has to take it. Until this was
    wired, chat replied 'on my way' and stood still."""
    r = await client.post("/api/v1/chat",
                          json={"room_id": ROOM, "message": "go to the red chair"})
    body = r.json()
    assert body["commands"][0]["target"] == "chair_02"
    executed = [e for e in body["executed"] if e["action"] == "navigate"]
    assert executed and executed[0]["status"] == "dispatched"
    assert executed[0]["path"]


async def test_a_question_about_the_room_is_answered_not_clarified(client) -> None:
    """'How many chairs?' has an exact answer. Replying 'which one do you
    mean?' to it would be absurd."""
    r = await client.post("/api/v1/chat",
                          json={"room_id": ROOM, "message": "how many chairs are there?"})
    body = r.json()
    assert body["clarification"] is None
    assert "Three" in body["reply"]


async def test_a_command_plans_against_the_room_it_names(client) -> None:
    """The robot service holds ONE graph; a command carries the room it was
    issued for, and planning has to use that one.

    This is a regression test for a silent wrong-room bug. Both shipped rooms
    contain a `chair_02`, so a multi_demo command planned against demo_room
    resolved to a real id, routed around a completely different room's
    furniture, and reported success — the exact failure this whole feature
    exists to prevent, hidden inside the feature itself.
    """
    demo = enrich_graph(json.loads(
        (ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8")))
    scene_service._graphs["demo_room"] = demo
    # the active graph is the OTHER room, as it would be after a scan
    robot_service.set_scene_graph(demo)

    body = await nl(client, "go to the bed")
    assert body["status"] == "resolved" and body["target"] == "bed_01"
    assert body["command_status"] == "dispatched", body.get("reason")

    # demo_room has no bed at all, so a path proves the right graph was used
    bed = next(o for o in scene_service.get(ROOM)["objects"]
               if o["id"] == "bed_01")
    end = body["path"][-1]
    assert abs(end[0] - bed["position"][0]) < 2.5
    assert abs(end[1] - bed["position"][2]) < 2.5


# ── detector reporting ──

async def test_detector_endpoint_is_honest_about_what_it_cannot_see(client) -> None:
    body = (await client.get("/api/v1/detector")).json()
    assert "chair" in body["recognised"]
    if body["trained_for_furniture"]:
        assert body["trained_for_furniture"] is True
    else:
        assert {"lamp", "shelf", "door"} <= set(body["size_prior_only"])
        assert body["trained_for_furniture"] is False
