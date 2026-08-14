"""Twin Generator — Orchestration wrapper around the reconstruction pipeline
(spec 9, 10.1, 20/P5).

Shells out to reconstruction/pipeline.py in ITS OWN venv, exactly as
imagine_manager does for genai3d, and for the same reason: that pipeline pulls
in Open3D, OpenCV and torch, and none of them belong in the API process. The
only contract across the boundary is line-delimited JSON on stdout.

On completion it writes the room into the scene graph, re-indexes it for
retrieval, re-bakes the navmesh, and publishes scene.updated — the same
sequence Imagine uses when it commits an object, because a newly scanned room
and a newly generated object have the same downstream consequences.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import time
import uuid
from pathlib import Path

from app.config import get_settings
from app.core.errors import InvalidCommand, NotFound
from app.core.events import bus
from app.services.rag_service import rag_service
from app.services.robot_service import robot_service
from app.services.scene_service import scene_service

log = logging.getLogger("roommind.twin")

ROOT = Path(__file__).resolve().parents[3]
RECON = ROOT / "reconstruction"
PIPELINE = RECON / "pipeline.py"

# Exit codes the pipeline uses (see its module docstring).
EXIT_OK = 0
EXIT_DEGRADED = 3


def _venv_python() -> Path:
    """reconstruction's own interpreter, falling back to ours if unbuilt."""
    for rel in ("Scripts/python.exe", "bin/python"):
        p = RECON / ".venv" / rel
        if p.exists():
            return p
    log.warning("reconstruction venv missing — falling back to the API interpreter")
    return Path(sys.executable)


def _storage(*parts: str) -> Path:
    """Absolute path under STORAGE_ROOT, anchored at the repo root.

    STORAGE_ROOT is relative ('./storage'), the API runs from backend/ and the
    pipeline subprocess runs with cwd=ROOT, so a relative path resolves to two
    different directories and the child writes where the parent cannot find it.
    Same trap as imagine_manager._out_root.
    """
    base = Path(get_settings().storage_root)
    base = base if base.is_absolute() else (ROOT / base)
    return base.resolve().joinpath(*parts)


class TwinGenerator:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    # ── submit ──

    async def submit(self, room_id: str, scan_dir: Path | str | None = None,
                     video_bytes: bytes | None = None, filename: str = "scan.mp4",
                     name: str | None = None, quality: str = "medium",
                     detector: str = "auto", pose_backend: str = "auto",
                     target_width: int | None = None) -> str:
        if video_bytes is None and scan_dir is None:
            raise InvalidCommand("a scan needs either an uploaded video or a scan_dir")

        scan_id = f"scan_{uuid.uuid4().hex[:12]}"
        work = _storage("scans", scan_id)
        work.mkdir(parents=True, exist_ok=True)

        if video_bytes is not None:
            src = work / filename
            src.write_bytes(video_bytes)
            input_path = src
        else:
            input_path = Path(scan_dir)
            if not input_path.exists():
                raise NotFound(f"scan_dir does not exist: {input_path}")

        job = {
            "id": scan_id, "room_id": room_id, "status": "queued",
            "progress": 0.0, "stage": "queued", "note": "",
            "input": str(input_path), "out": str(_storage("meshes", room_id)),
            "created_at": time.time(), "error": None, "warnings": [],
            "objects": None, "elapsed_s": None,
        }
        self.jobs[scan_id] = job
        asyncio.create_task(self._run(job, name, quality, detector, pose_backend,
                                      target_width))
        await bus.publish("scan.started", {"room_id": room_id, "scan_id": scan_id})
        return scan_id

    # ── the subprocess ──

    async def _run(self, job: dict, name, quality, detector, pose_backend,
                   target_width) -> None:
        s = get_settings()
        out_dir = Path(job["out"])
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(_venv_python()), str(PIPELINE),
            "--input", job["input"], "--out", str(out_dir),
            "--room-id", job["room_id"], "--scan-id", job["id"],
            "--quality", quality, "--detector", detector,
            "--pose-backend", pose_backend,
            "--mesh-max-mb", str(s.mesh_max_mb),
        ]
        intr = Path(job["input"])
        intr = (intr if intr.is_dir() else intr.parent) / "intrinsics.json"
        if intr.exists():
            cmd += ["--intrinsics", str(intr)]
        if name:
            cmd += ["--name", name]
        if target_width:
            cmd += ["--target-width", str(target_width)]
        weights = ROOT / s.yolo_weights.lstrip("./")
        if weights.exists():
            cmd += ["--weights", str(weights)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(ROOT),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except Exception as e:  # noqa: BLE001
            await self._fail(job, f"could not start the reconstruction: {e}")
            return

        self._procs[job["id"]] = proc
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            await self._on_progress(job, evt)

        await proc.wait()
        self._procs.pop(job["id"], None)
        stderr = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""

        if job["status"] == "cancelled":
            return
        if proc.returncode not in (EXIT_OK, EXIT_DEGRADED):
            await self._fail(job, job.get("error") or stderr.strip()[-400:]
                             or f"reconstruction exited {proc.returncode}")
            return

        await self._commit(job, degraded=proc.returncode == EXIT_DEGRADED)

    async def _on_progress(self, job: dict, evt: dict) -> None:
        if evt.get("error"):
            job["error"] = evt["error"]
        stage = evt.get("stage", job["stage"])
        job.update(stage=stage, status="running",
                   progress=float(evt.get("progress", job["progress"])),
                   note=evt.get("note", ""))
        if evt.get("warnings"):
            job["warnings"] = evt["warnings"]

        await bus.publish("scan.progress", {
            "room_id": job["room_id"], "scan_id": job["id"],
            "stage": stage, "progress": job["progress"],
            "note": evt.get("note", ""),
            "elapsed_s": evt.get("elapsed_s"),
        })

    # ── commit ──

    async def _commit(self, job: dict, degraded: bool) -> None:
        room_json = Path(job["out"]) / "room.json"
        if not room_json.exists():
            await self._fail(job, "the pipeline produced no room.json")
            return

        graph = json.loads(room_json.read_text(encoding="utf-8"))

        # Point the mesh at the API rather than at a path on disk: the browser
        # fetches it over HTTP and knows nothing about storage layout.
        graph.setdefault("mesh", {})["url"] = f"/api/v1/rooms/{job['room_id']}/mesh"

        # put() installs the graph and publishes scene.updated itself.
        await scene_service.put(graph)
        rag_service.index_room(graph)          # ARIA can talk about the new room
        robot_service.set_scene_graph(graph)   # A* re-bakes against the new navmesh

        job.update(status="completed", progress=1.0, stage="completed",
                   objects=len(graph.get("objects", [])),
                   degraded=degraded,
                   elapsed_s=round(time.time() - job["created_at"], 1))

        await bus.publish("scan.completed", {
            "room_id": job["room_id"], "scan_id": job["id"],
            "objects": job["objects"], "mesh_url": graph["mesh"]["url"],
            "warnings": job["warnings"], "degraded": degraded,
            "elapsed_s": job["elapsed_s"],
        })
        log.info("scan %s built room %s: %d objects in %.1fs%s",
                 job["id"], job["room_id"], job["objects"], job["elapsed_s"],
                 " (degraded)" if degraded else "")

    # ── control ──

    async def cancel(self, scan_id: str) -> None:
        job = self.jobs.get(scan_id)
        if not job:
            raise NotFound(f"unknown scan '{scan_id}'")
        proc = self._procs.get(scan_id)
        job.update(status="cancelled", stage="cancelled")
        if proc and proc.returncode is None:
            proc.kill()
        await bus.publish("scan.failed", {
            "room_id": job["room_id"], "scan_id": scan_id, "reason": "cancelled"})

    def status(self, scan_id: str) -> dict:
        job = self.jobs.get(scan_id)
        if not job:
            raise NotFound(f"unknown scan '{scan_id}'")
        return dict(job)

    def list_jobs(self) -> list[dict]:
        return sorted(self.jobs.values(), key=lambda j: -j["created_at"])

    async def discard(self, scan_id: str) -> None:
        job = self.jobs.pop(scan_id, None)
        if job:
            shutil.rmtree(_storage("scans", scan_id), ignore_errors=True)

    async def _fail(self, job: dict, reason: str) -> None:
        job.update(status="failed", error=reason, stage="failed")
        log.warning("scan %s failed: %s", job["id"], reason)
        await bus.publish("scan.failed", {
            "room_id": job["room_id"], "scan_id": job["id"], "reason": reason})


twin_generator = TwinGenerator()
