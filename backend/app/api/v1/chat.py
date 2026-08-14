"""Chat endpoint + embodied grounding (spec 8.6, P3 item 7)."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.errors import RoomMindError
from app.core.events import bus
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.services.robot_service import robot_service
from app.services.scene_service import scene_service

log = logging.getLogger("roommind.chat")
router = APIRouter()

# In-memory transcript. Postgres persistence lands with the DB (Phase 5).
_history: dict[str, list[dict]] = {}
MAX_HISTORY = 200

# Phrasings that mean "where is it", so ARIA points rather than just looking.
POINT_TRIGGERS = ("where", "which one", "show me", "point")


class ChatIn(BaseModel):
    room_id: str = "demo_room"
    message: str
    mode: str = "design"
    params: dict = Field(default_factory=dict)


@router.post("/chat")
async def chat(body: ChatIn) -> dict:
    try:
        scene_service.get(body.room_id)
    except RoomMindError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    t0 = time.perf_counter()
    _append(body.room_id, "user", body.message, {})

    result = await llm_service.chat(body.room_id, body.message, body.mode)
    executed = await _execute(body.room_id, result)
    gestures = await _ground(body.room_id, body.message, result)

    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    result["executed"] = executed
    result["gestures"] = gestures
    # Always present, null when there is nothing to ask. A key that only exists
    # on some turns makes every client branch on its presence before it can
    # branch on its value.
    result.setdefault("clarification", None)
    _append(body.room_id, "assistant", result["reply"], {
        "citations": result["citations"],
        "commands": result["commands"],
        "engine": result["engine"],
    })

    await bus.publish("chat.message", {
        "room_id": body.room_id, "role": "assistant",
        "content": result["reply"], "citations": result["citations"],
        "commands": result["commands"],
        # Present only when ARIA needs to know WHICH object before she can act.
        # The frontend turns the options into one-tap chips; answering is an
        # ordinary chat turn, so the resolver picks it up as a reply.
        "clarification": result.get("clarification"),
    })
    await bus.publish("companion.speak", {
        "room_id": body.room_id, "text": result["reply"], "voice": "aria",
    })
    return result


async def _execute(room_id: str, result: dict) -> list[dict]:
    """Actually carry out the commands the turn produced.

    Both engines emit a `commands` list — the offline intent path from a
    resolved target, the Claude path from `issue_command` — and until now
    nothing dispatched them. ARIA would answer "on my way to the chair" and
    stand perfectly still, which is the one failure a companion cannot have:
    the words claimed an action the body never took.

    Every target has already been checked against the scene graph before it
    reaches here (the resolver for the offline path, `_run_tool` for Claude),
    so a rejection at this point is a real planning failure — no route, an
    e-stop latched — and is reported rather than swallowed.
    """
    out: list[dict] = []
    for cmd in result.get("commands") or []:
        try:
            rec = await robot_service.enqueue(
                {"action": cmd.get("action"), "target": cmd.get("target"),
                 "params": cmd.get("params") or {}},
                room_id=room_id, source="chat")
        except RoomMindError as e:
            log.info("chat command rejected: %s", e)
            out.append({"action": cmd.get("action"), "target": cmd.get("target"),
                        "status": "rejected", "reason": str(e)})
            continue
        out.append({
            "action": rec["action"], "target": rec["target"],
            "status": rec["status"], "reason": rec.get("reason"),
            "path": rec.get("path"),
        })
    return out


async def _ground(room_id: str, user_message: str, result: dict) -> list[dict]:
    """Embodied grounding — the signature behaviour of Phase 3.

    When ARIA cites an object she looks at it; when the user asked *where*
    something is she points. The user never has to ask her to do this, and the
    LLM is never relied on to remember: grounding a sentence in a gesture is
    the default, enforced here.

    Skipped when the model already issued its own aiming command for that
    object, so she doesn't point twice at the same thing.
    """
    citations = result.get("citations") or []
    if not citations:
        return []

    already = {c.get("target") for c in result.get("commands", [])
               if c.get("action") in ("look_at", "point_at", "present")}
    target = citations[0]
    if target in already:
        return []

    lowered = user_message.lower()
    action = "point_at" if any(w in lowered for w in POINT_TRIGGERS) else "look_at"

    try:
        rec = await robot_service.enqueue(
            {"action": action, "target": target}, room_id=room_id, source="chat"
        )
        return [{"action": action, "target": target, "status": rec["status"]}]
    except RoomMindError as e:
        # A gesture failing must never fail the answer — the words are the
        # deliverable, the movement is the flourish.
        log.info("grounding gesture skipped: %s", e)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("grounding gesture error: %r", e)
        return []


@router.get("/chat/{room_id}/history")
async def history(room_id: str) -> list[dict]:
    return _history.get(room_id, [])


@router.delete("/chat/{room_id}/history")
async def clear_history(room_id: str) -> dict:
    _history.pop(room_id, None)
    return {"cleared": True}


@router.get("/chat/{room_id}/suggestions")
async def suggestions(room_id: str) -> list[str]:
    """Quick-ask chips. Built from the actual room so they always work — a
    suggestion that references an object this room doesn't have is a trap on
    stage."""
    objs = rag_service.all_objects(room_id)
    if not objs:
        return ["What can you see?"]
    labels = sorted({o["label"] for o in objs})
    out = ["What's in this room?"]
    if labels:
        out.append(f"How many {labels[0].replace('_', ' ')}s are there?")
    for label in labels[:2]:
        out.append(f"Where's the {label.replace('_', ' ')}?")
    if len(objs) > 1:
        out.append(f"Take me to the {objs[0]['label'].replace('_', ' ')}")
    return out[:5]


def _append(room_id: str, role: str, content: str, meta: dict) -> None:
    log_ = _history.setdefault(room_id, [])
    log_.append({
        "id": str(uuid.uuid4()), "role": role, "content": content,
        "meta": meta, "ts": time.time(),
    })
    if len(log_) > MAX_HISTORY:
        del log_[: len(log_) - MAX_HISTORY]
