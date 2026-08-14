"""Imagine endpoints — image -> 3D (spec 8.6)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.core.errors import RoomMindError
from app.services.imagine_manager import imagine_manager

router = APIRouter()


@router.post("/imagine")
async def create(
    image: UploadFile = File(...),
    room_id: str = Form("demo_room"),
    prompt: str | None = Form(None),
    place_on: str | None = Form(None),
    camera_x: float | None = Form(None),
    camera_z: float | None = Form(None),
) -> dict:
    s = get_settings()
    data = await image.read()
    if len(data) > s.imagine_max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"image exceeds {s.imagine_max_upload_mb} MB",
        )

    cam = (camera_x, camera_z) if camera_x is not None and camera_z is not None else None
    try:
        job_id = await imagine_manager.submit(
            room_id, data, prompt=prompt, place_on=place_on, camera_xz=cam
        )
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code,
                            detail={"reason": e.reason, "message": str(e)}) from e
    return {"job_id": job_id, "status": "queued"}


@router.get("/imagine/{job_id}")
async def status(job_id: str) -> dict:
    try:
        return imagine_manager.status(job_id)
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.post("/imagine/{job_id}/confirm")
async def confirm(job_id: str, overrides: dict | None = None) -> dict:
    try:
        return await imagine_manager.confirm(job_id, overrides)
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.delete("/imagine/{job_id}", status_code=204, response_class=Response)
async def discard(job_id: str) -> Response:
    # 204 must carry no body, so the response class has to be declared
    # explicitly — FastAPI otherwise infers one from the return annotation
    # and refuses the route at import time.
    await imagine_manager.discard(job_id)
    return Response(status_code=204)


def _artifact(job_id: str, name: str, media: str) -> FileResponse:
    job = imagine_manager.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    # Resolve and confine to the job directory — job_id reaches us from the URL
    # and must never be able to walk out of it.
    base = Path(job["dir"]).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base) or not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return FileResponse(path, media_type=media)


@router.get("/imagine/{job_id}/mesh")
async def mesh(job_id: str) -> FileResponse:
    return _artifact(job_id, "object.glb", "model/gltf-binary")


@router.get("/imagine/{job_id}/thumb")
async def thumb(job_id: str) -> FileResponse:
    return _artifact(job_id, "thumb.png", "image/png")
