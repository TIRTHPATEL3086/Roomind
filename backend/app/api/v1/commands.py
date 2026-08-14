"""Commands, robots and e-stop endpoints (spec 8.6)."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.errors import RoomMindError
from app.services.robot_service import robot_service

router = APIRouter()


class CommandIn(BaseModel):
    """Mirrors contracts/command.schema.json. Kept permissive on `action` so the
    service layer owns validation and returns a proper domain reason."""

    id: str | None = None
    action: str
    target: str | None = None
    params: dict = Field(default_factory=dict)
    robot_id: str = "aria"
    priority: int = 5


@router.post("/commands")
async def create_command(body: CommandIn, room_id: str | None = None) -> dict:
    try:
        cmd = await robot_service.enqueue(body.model_dump(), room_id=room_id, source="api")
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code,
                            detail={"reason": e.reason, "message": str(e)}) from e
    return {
        "command_id": cmd["id"],
        "status": cmd["status"],
        "reason": cmd.get("reason"),
        "path": cmd.get("path"),
    }


@router.get("/commands/{command_id}")
async def get_command(command_id: str) -> dict:
    cmd = robot_service.commands.get(command_id)
    if not cmd:
        raise HTTPException(status_code=404, detail="unknown command")
    return cmd


@router.post("/commands/{command_id}/cancel", status_code=202)
async def cancel_command(command_id: str) -> dict:
    try:
        await robot_service.cancel(command_id)
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return {"command_id": command_id, "status": "cancelled"}


@router.get("/robots")
async def list_robots() -> list[dict]:
    """Array of one. The shape stays plural so the frontend never has to change."""
    return robot_service.all()


@router.get("/robots/{robot_id}")
async def get_robot(robot_id: str) -> dict:
    if robot_id != robot_service.robot_id:
        raise HTTPException(status_code=404, detail=f"unknown robot '{robot_id}'")
    return robot_service.get()


@router.post("/estop")
async def estop(response: Response) -> dict:
    """Must respond in under 50 ms (spec 8.6). Publishes at QoS 0 before any DB write."""
    t0 = time.perf_counter()
    publish_ms = await robot_service.estop()
    total_ms = (time.perf_counter() - t0) * 1000.0
    response.headers["X-Estop-Latency-Ms"] = f"{total_ms:.2f}"
    return {"stopped": True, "publish_ms": round(publish_ms, 2),
            "total_ms": round(total_ms, 2)}


@router.post("/estop/clear")
async def clear_estop() -> dict:
    """Release the latch on BOTH the backend and the robot."""
    from app.services.safety_service import safety_service

    safety_service.clear_estop(robot_service.robot_id)
    robot_service.state["state"] = "idle"
    return {"stopped": False}
