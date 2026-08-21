"""Rooms API (spec 8.6).

Reads go through scene_service, which serves the in-memory graph and falls back
to nothing rather than requiring a database. Persistence is Phase 5's concern.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.errors import NotFound
from app.services.robot_service import robot_service
from app.services.scene_service import scene_service

router = APIRouter()


@router.get("/rooms")
async def list_rooms() -> list[dict]:
    return scene_service.list_rooms()


@router.get("/rooms/{room_id}")
async def get_room(room_id: str) -> dict:
    """Returns the full scene graph (spec 8.2)."""
    try:
        return scene_service.get(room_id)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/rooms/{room_id}/reset")
async def reset_room(room_id: str) -> dict:
    """Reset the room back to its default demo fixture.

    The frontend calls this on every room switch (not just an explicit
    "rescan"), which makes it the right place to re-park ARIA too - see
    robot_service.reset_pose_for_room.
    """
    try:
        graph = scene_service.reset_room(room_id)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await robot_service.reset_pose_for_room(room_id, graph)
    return graph


@router.get("/rooms/{room_id}/objects/{object_id}")
async def get_object(room_id: str, object_id: str) -> dict:
    try:
        obj = scene_service.find_object(room_id, object_id)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if obj is None:
        raise HTTPException(status_code=404, detail=f"object '{object_id}' not found")
    return obj
