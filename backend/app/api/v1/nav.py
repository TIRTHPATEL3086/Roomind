"""Targeted navigation: one endpoint for the whole natural-language chain.

    POST /commands/nl     "go to the red chair near the table" -> ARIA moves
    POST /resolve         the same resolution, with nothing dispatched
    GET  /detector        what the recogniser can actually recognise

The chain is the four steps from the design, each of which already exists and
none of which is a language model:

    intent      -> is this even a navigation request?      intent_service
    target      -> what constraints did they state?        core.query_parse
    instance    -> which physical object is that?          resolver_service
    motion      -> where do I stop, and how do I get       planner_service
                   there without hitting anything?         core.navmesh

`/resolve` exists because the interesting half of this feature is invisible
once the robot starts moving. It answers exactly what `/commands/nl` would
have targeted, with no side effects, which is what the tests assert on and
what the UI uses to preview a command before committing to it.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.errors import RoomMindError
from app.core.events import bus
from app.services.resolver_service import resolver_service
from app.services.robot_service import robot_service
from app.services.scene_service import scene_service

log = logging.getLogger("roommind.nav")
router = APIRouter()


class NLCommandIn(BaseModel):
    room_id: str = "demo_room"
    text: str
    action: str = "navigate"
    params: dict = Field(default_factory=dict)


class ResolveIn(BaseModel):
    room_id: str = "demo_room"
    text: str


def viewer_pose() -> dict:
    """ARIA's own point of view, for "the chair on the left".

    `known` is the load-bearing field. With no telemetry her pose is the
    default zero pose, which is a real position she is probably not standing
    at, and treating it as a viewpoint would answer a question about her left
    using a direction she is not facing. The resolver falls back to the room
    frame instead and says which frame it used.
    """
    pose = robot_service.state.get("pose") or {}
    return {
        "known": bool(robot_service.state.get("online")),
        "x": float(pose.get("x", 0.0)),
        "z": float(pose.get("z", 0.0)),
        "yaw": float(pose.get("yaw", 0.0)),
    }


def _graph(room_id: str) -> dict:
    try:
        return scene_service.get(room_id)
    except RoomMindError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/resolve")
async def resolve(body: ResolveIn) -> dict:
    """Resolve a phrase to one object. Reads only - nothing is dispatched."""
    resolution = resolver_service.resolve(
        _graph(body.room_id), body.text, viewer=viewer_pose(),
        room_id=body.room_id)
    return resolution.as_dict()


@router.post("/commands/nl")
async def nl_command(body: NLCommandIn) -> dict:
    """Natural language -> a resolved target -> a planned, dispatched move."""
    graph = _graph(body.room_id)
    resolution = resolver_service.resolve(graph, body.text,
                                          viewer=viewer_pose(),
                                          room_id=body.room_id)
    out = resolution.as_dict()

    if resolution.status != "resolved":
        # Ambiguous, missing, or too uncertain to act on. The question goes to
        # the UI as a chat turn so answering it is a reply, not a new command.
        out["reply"] = resolution.question or resolution.message
        if resolution.status in ("clarify", "confirm"):
            await bus.publish("chat.message", {
                "room_id": body.room_id, "role": "assistant",
                "content": out["reply"], "citations": [],
                "commands": [],
                "clarification": {"options": resolution.options,
                                  "question": resolution.question},
            })
        return out

    target = resolution.object_id
    try:
        rec = await robot_service.enqueue(
            {"action": body.action, "target": target, "params": body.params},
            room_id=body.room_id, source="nl")
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code,
                            detail={"reason": e.reason, "message": str(e)}) from e

    out.update({
        "command_id": rec["id"],
        "command_status": rec["status"],
        "reason": rec.get("reason"),
        "path": rec.get("path"),
    })

    if rec["status"] == "rejected":
        out["reply"] = (f"I found {target}, but I can't get to it: "
                        f"{rec.get('reason')}")
        return out

    # Arrive facing the thing she was sent to. Without this she stops at the
    # right spot with her back to it, which reads as having gone to the wrong
    # place even though the navigation was correct. A failed gesture must never
    # fail the move, so this is best-effort exactly like chat's grounding.
    if body.action == "navigate":
        try:
            await robot_service.enqueue(
                {"action": "look_at", "target": target},
                room_id=body.room_id, source="nl")
        except RoomMindError as e:
            log.info("arrival look_at skipped: %s", e)

    label = (resolution.object or {}).get("label", target)
    out["reply"] = f"On my way to the {label.replace('_', ' ')}. [{target}]"
    return out


@router.get("/detector")
async def detector() -> dict:
    """What the recogniser supports, reported rather than assumed.

    Answered from the API process, which must never import torch or
    ultralytics (spec rule 3) - so this reports what the RECONSTRUCTION venv
    would use, derived from what is on disk, not from importing it.
    """
    from pathlib import Path

    from app.config import get_settings

    s = get_settings()
    root = Path(__file__).resolve().parents[4]
    weights = root / s.yolo_weights.lstrip("./")
    recon_venv = root / "reconstruction" / ".venv"
    have_ultralytics = any(
        (recon_venv / rel).exists()
        for rel in ("Lib/site-packages/ultralytics", "lib/python3.11/site-packages/ultralytics")
    )

    # COCO's furniture-relevant classes, and the ones a room needs that COCO
    # simply does not have. Kept in sync with reconstruction/steps/s07_detect.py.
    recognised = ["bed", "bench", "book", "bottle", "chair", "clock", "fridge",
                  "laptop", "microwave", "oven", "potted_plant", "sink", "sofa",
                  "table", "toilet", "tv", "vase"]
    size_prior_only = ["cabinet", "desk", "door", "lamp", "monitor", "rug",
                       "shelf", "wardrobe", "window"]

    return {
        "backend": "fusion" if have_ultralytics else "geometric",
        "weights": (str(weights) if weights.exists()
                    else "yolov8n.pt (pretrained COCO)"),
        "trained_for_furniture": weights.exists(),
        "recognised": recognised if have_ultralytics else [],
        "size_prior_only": size_prior_only if not weights.exists() else [],
        "note": (
            "Classes under size_prior_only are NOT recognised by the detector. "
            "They are inferred from 3D dimensions and carry "
            "label_source='size_prior' in the scene graph."
        ),
    }
