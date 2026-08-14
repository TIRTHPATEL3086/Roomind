"""Scan endpoints — capture -> 3D twin (spec 8.7, 10.1).

POST /scan            start a reconstruction from an uploaded video, or from a
                      directory of frames already on disk
GET  /scan/{id}       poll status (the WebSocket is the primary channel)
POST /scan/{id}/progress   sink for the pipeline's --progress-url
POST /scan/{id}/cancel
GET  /rooms/{id}/mesh      the reconstructed .glb
GET  /rooms/{id}/navmesh   the occupancy grid
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.core.errors import RoomMindError
from app.core.events import bus
from app.services.twin_generator import _storage, twin_generator

router = APIRouter()

MAX_UPLOAD_MB = 512


@router.post("/scan")
async def create(
    video: UploadFile | None = File(None),
    scan_dir: str | None = Form(None),
    room_id: str = Form("demo_room"),
    name: str | None = Form(None),
    quality: str = Form("medium"),
    detector: str = Form("auto"),
    pose_backend: str = Form("auto"),
    target_width: int | None = Form(None),
) -> dict:
    data = await video.read() if video is not None else None
    if data is not None and len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413,
                            detail=f"video exceeds {MAX_UPLOAD_MB} MB")
    try:
        scan_id = await twin_generator.submit(
            room_id, scan_dir=scan_dir, video_bytes=data,
            filename=video.filename if video else "scan.mp4",
            name=name, quality=quality, detector=detector,
            pose_backend=pose_backend, target_width=target_width)
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code,
                            detail={"reason": e.reason, "message": str(e)}) from e
    return {"scan_id": scan_id, "status": "queued"}


@router.get("/scan")
async def list_scans() -> list[dict]:
    return twin_generator.list_jobs()


@router.get("/scan/{scan_id}")
async def status(scan_id: str) -> dict:
    try:
        return twin_generator.status(scan_id)
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.post("/scan/{scan_id}/progress", status_code=204,
             response_class=Response)
async def progress_sink(scan_id: str, payload: dict) -> Response:
    """Receives progress from a pipeline run started OUTSIDE this process.

    The in-process path reads the subprocess's stdout directly and never uses
    this; it exists so the CLI's --progress-url works when someone runs a
    reconstruction by hand against a live server. Unknown scan ids are relayed
    anyway rather than 404'd -- a progress report is not worth failing a
    three-minute job over.
    """
    job = twin_generator.jobs.get(scan_id)
    if job is not None:
        job.update(stage=payload.get("stage", job["stage"]),
                   progress=float(payload.get("progress", job["progress"])),
                   note=payload.get("note", ""))
        room_id = job["room_id"]
    else:
        room_id = payload.get("room_id", "demo_room")

    await bus.publish("scan.progress", {
        "room_id": room_id, "scan_id": scan_id,
        "stage": payload.get("stage"), "progress": payload.get("progress", 0.0),
        "note": payload.get("note", ""), "elapsed_s": payload.get("elapsed_s"),
    })
    return Response(status_code=204)


@router.post("/scan/{scan_id}/cancel", status_code=204, response_class=Response)
async def cancel(scan_id: str) -> Response:
    try:
        await twin_generator.cancel(scan_id)
    except RoomMindError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return Response(status_code=204)


# ── reconstructed assets ──

def _asset(room_id: str, filename: str, media_type: str) -> FileResponse:
    path = _storage("meshes", room_id, filename)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"no {filename} for room '{room_id}' - has it been scanned?")
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/rooms/{room_id}/mesh")
async def mesh(room_id: str) -> FileResponse:
    return _asset(room_id, "room.glb", "model/gltf-binary")


@router.get("/rooms/{room_id}/navmesh")
async def navmesh(room_id: str) -> FileResponse:
    return _asset(room_id, "navmesh.npy", "application/octet-stream")


@router.get("/rooms/{room_id}/preview")
async def preview(room_id: str) -> FileResponse:
    return _asset(room_id, "preview.png", "image/png")
