"""Imagine Manager — Orchestration layer for image -> 3D (spec 9.12.1, 10B).

Shells out to genai3d/pipeline.py in ITS OWN venv. It must never import genai3d
directly: the two environments have deliberately different dependency sets
(genai3d grows torch/diffusers when a neural backend is installed), and a
subprocess boundary is what keeps that from leaking into the API process.

On commit it writes the object into the scene graph, re-embeds it for
retrieval, and RE-BAKES THE NAVMESH. That last step is not optional — a
generated obstacle A* cannot see is a robot that drives into a lamp.
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

log = logging.getLogger("roommind.imagine")

ROOT = Path(__file__).resolve().parents[3]
GENAI3D = ROOT / "genai3d"
PIPELINE = GENAI3D / "pipeline.py"

# Below this the object is NOT auto-committed — we show a preview and let the
# user confirm or resize (spec 10B.5). An honest "does this look right?" beats
# a confidently wrong sofa.
AUTO_COMMIT_CONFIDENCE = 0.5


def _out_root() -> Path:
    """Absolute output directory, anchored at the repo root.

    IMAGINE_OUT_DIR is relative ('./storage/generated'), but the API process
    runs from backend/ while the pipeline subprocess runs with cwd=ROOT — so a
    relative path resolves to two different directories and the child cannot
    find the image the parent just wrote. Resolve once, here, and pass absolute
    paths across the process boundary.
    """
    p = Path(get_settings().imagine_out_dir)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _venv_python() -> Path:
    """genai3d's own interpreter, falling back to ours if it isn't built yet."""
    for rel in ("Scripts/python.exe", "bin/python"):
        p = GENAI3D / ".venv" / rel
        if p.exists():
            return p
    log.warning("genai3d venv missing — falling back to the API interpreter")
    return Path(sys.executable)


class ImagineManager:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    # ── submit ──

    async def submit(self, room_id: str, image_bytes: bytes,
                     prompt: str | None = None,
                     place_on: str | None = None,
                     camera_xz: tuple[float, float] | None = None) -> str:
        s = get_settings()
        if not s.imagine_enabled:
            raise InvalidCommand("Imagine is disabled (IMAGINE_ENABLED=false)")
        scene_service.get(room_id)          # 404s early if the room is unknown

        job_id = str(uuid.uuid4())
        out = _out_root() / job_id
        out.mkdir(parents=True, exist_ok=True)
        src = out / "input.png"
        src.write_bytes(image_bytes)

        job = {
            "id": job_id, "room_id": room_id, "status": "queued",
            "progress": 0.0, "stage": "queued", "prompt": prompt,
            "place_on": place_on, "camera_xz": camera_xz,
            "dir": str(out), "created_at": time.time(),
            "error": None, "object_id": None,
        }
        self.jobs[job_id] = job
        asyncio.create_task(self._run(job, src))
        return job_id

    # ── pipeline subprocess ──

    async def _run(self, job: dict, src: Path) -> None:
        s = get_settings()
        cmd = [
            str(_venv_python()), str(PIPELINE),
            "--image", str(src), "--out", job["dir"],
            "--backend", s.imagine_backend, "--device", s.imagine_device,
            "--timeout", str(s.imagine_timeout_s),
            "--size-estimator", s.imagine_size_estimator,
            "--max-tris", str(s.imagine_max_tris),
            "--max-upload-mb", str(s.imagine_max_upload_mb),
        ]
        if job.get("prompt"):
            cmd += ["--hint", job["prompt"]]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(ROOT),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:  # noqa: BLE001
            await self._fail(job, f"could not start pipeline: {e}")
            return

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

        # Give the process a hard ceiling so a wedged backend can't hang the job.
        try:
            await asyncio.wait_for(proc.wait(),
                                   timeout=s.imagine_timeout_s + 30)
        except TimeoutError:
            proc.kill()
            await self._fail(job, "pipeline timed out")
            return

        stderr = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""

        # 0 = generated, 3 = proxy fallback (still a usable object).
        if proc.returncode not in (0, 3):
            await self._fail(job, job.get("error") or stderr.strip()[-300:]
                             or f"pipeline exited {proc.returncode}")
            return

        await self._preview(job)

    async def _on_progress(self, job: dict, evt: dict) -> None:
        stage = evt.get("stage", "")
        if stage == "failed":
            job["error"] = evt.get("error")
            return
        job["stage"] = stage
        job["progress"] = float(evt.get("progress", job["progress"]))
        job["status"] = "running"
        for k in ("label", "est_dims_m", "scale_confidence", "backend", "note"):
            if k in evt:
                job[k] = evt[k]
        await bus.publish("imagine.progress", {
            "room_id": job["room_id"], "job_id": job["id"],
            "stage": stage, "progress": job["progress"],
            "note": evt.get("note"), "label": evt.get("label"),
        })

    # ── preview ──

    async def _preview(self, job: dict) -> None:
        out = Path(job["dir"])
        obj_path = out / "object.json"
        if not obj_path.exists():
            await self._fail(job, "pipeline produced no object.json")
            return

        fragment = json.loads(obj_path.read_text(encoding="utf-8"))
        metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))

        graph = scene_service.get(job["room_id"])
        placement = self._solve_placement(graph, fragment, job)

        job.update({
            "status": "preview", "progress": 1.0, "stage": "preview",
            "fragment": fragment, "metrics": metrics,
            "placement": {
                "position": list(placement.position),
                "rotation_y": placement.rotation_y,
                "on": placement.on,
                "needs_review": placement.needs_review,
                "reasons": placement.reasons,
            },
        })

        conf = float(fragment.get("scale_confidence", 0.0))
        auto = conf >= AUTO_COMMIT_CONFIDENCE and not placement.needs_review

        await bus.publish("imagine.preview", {
            "room_id": job["room_id"], "job_id": job["id"],
            "label": fragment["label"], "dimensions": fragment["dimensions"],
            "position": list(placement.position),
            "mesh_url": f"/api/v1/imagine/{job['id']}/mesh",
            "thumb_url": f"/api/v1/imagine/{job['id']}/thumb",
            "scale_confidence": conf,
            "proxy": bool(metrics.get("is_proxy")),
            "auto_commit": auto,
            "reasons": placement.reasons,
        })

        if auto:
            await self.confirm(job["id"], None)

    def _solve_placement(self, graph: dict, fragment: dict, job: dict):
        sys.path.insert(0, str(GENAI3D))
        try:
            from steps.g09_place import solve
        finally:
            if str(GENAI3D) in sys.path:
                sys.path.remove(str(GENAI3D))

        return solve(
            graph, fragment["dimensions"],
            placement=fragment.get("attributes", {}).get("placement", "floor"),
            place_on=job.get("place_on"),
            camera_xz=job.get("camera_xz"),
        )

    # ── commit ──

    async def confirm(self, job_id: str, overrides: dict | None) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise NotFound(f"unknown imagine job '{job_id}'")
        if job["status"] == "committed":
            return job["object"]
        if job["status"] != "preview":
            raise InvalidCommand(f"job is '{job['status']}', not ready to commit")

        room_id = job["room_id"]
        fragment = dict(job["fragment"])
        placement = dict(job["placement"])
        overrides = overrides or {}

        if "dimensions" in overrides:
            fragment["dimensions"] = list(overrides["dimensions"])
            # The user resized it, so their number is now the source of truth.
            fragment["scale_confidence"] = 1.0
        if "position" in overrides:
            placement["position"] = list(overrides["position"])
        if "rotation_y" in overrides:
            placement["rotation_y"] = float(overrides["rotation_y"])

        # Ids follow the SAME frozen rule as detected objects (spec 8.2), so
        # nothing downstream can tell a generated object from a scanned one.
        object_id = scene_service.next_object_id(room_id, fragment["label"])

        obj = {
            **fragment,
            "id": object_id,
            "position": [round(float(v), 4) for v in placement["position"]],
            "rotation_y": placement["rotation_y"],
            "mesh_url": f"/api/v1/imagine/{job_id}/mesh",
            "origin_image": f"/api/v1/imagine/{job_id}/thumb",
        }
        obj.pop("surface_height", None) if obj.get("surface_height") is None else None

        await scene_service.add_object(room_id, obj)

        graph = scene_service.get(room_id)
        rag_service.index_room(graph)      # ARIA can now talk about it
        robot_service.set_scene_graph(graph)  # A* re-bakes off the new graph

        job.update({"status": "committed", "object_id": object_id, "object": obj})
        await bus.publish("imagine.completed", {
            "room_id": room_id, "job_id": job_id,
            "object_id": object_id, "mesh_url": obj["mesh_url"],
        })
        log.info("imagine committed %s (%s) at %s",
                 object_id, job.get("backend", "?"), obj["position"])
        return obj

    async def discard(self, job_id: str) -> None:
        job = self.jobs.pop(job_id, None)
        if job:
            shutil.rmtree(job["dir"], ignore_errors=True)

    def status(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise NotFound(f"unknown imagine job '{job_id}'")
        return {k: v for k, v in job.items() if k != "camera_xz"}

    async def _fail(self, job: dict, reason: str) -> None:
        job.update({"status": "failed", "error": reason, "stage": "failed"})
        log.warning("imagine job %s failed: %s", job["id"], reason)
        await bus.publish("imagine.failed", {
            "room_id": job["room_id"], "job_id": job["id"],
            "reason": reason, "fell_back_to_proxy": False,
        })


imagine_manager = ImagineManager()
