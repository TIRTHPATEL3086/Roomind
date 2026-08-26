"""RoomMind backend entrypoint (spec 9.2).

Run:  cd backend && uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import threading
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.core.events import bus
from app.services.llm_service import llm_service
from app.services.mqtt_service import mqtt_service
from app.services.rag_service import rag_service
from app.services.robot_service import robot_service
from app.services.scene_service import scene_service

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("roommind")


DEFAULT_CAPABILITIES = [
    "navigate", "come_here", "stop", "follow_me", "dock", "turn", "set_speed",
    "look_at", "point_at", "wave", "nod", "shake_head", "gesture", "express",
    "dance", "scan_area", "remember_spot", "locate", "photo", "report_battery",
    "present", "imagine", "sit", "jump", "climb",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("RoomMind starting (env=%s, robot=%s, mode=%s)",
             settings.app_env, settings.robot_id, settings.robot_mode)

    scene = scene_service.load_fixture()
    await robot_service.bootstrap(DEFAULT_CAPABILITIES, scene)
    await mqtt_service.connect()

    # Automatically start ARIA simulator in sim mode so the robot is always online with the website
    sim_instance = None
    if settings.robot_mode == "sim":
        try:
            from pathlib import Path
            sim_dir = Path(__file__).resolve().parents[1] / "firmware" / "sim"
            if str(sim_dir) not in sys.path:
                sys.path.insert(0, str(sim_dir))
            from robot_sim import AriaSim

            sim_instance = AriaSim(
                robot_id=settings.robot_id,
                broker=settings.mqtt_host,
                port=settings.mqtt_port,
            )
            sim_thread = threading.Thread(target=sim_instance.run, daemon=True, name="AriaSimThread")
            sim_thread.start()
            log.info("ARIA background simulator auto-started (robot=%s, broker=%s:%d)",
                     settings.robot_id, settings.mqtt_host, settings.mqtt_port)
        except Exception as e:
            log.warning("Could not auto-start ARIA simulator: %s", e)

    if scene:
        n = rag_service.index_room(scene)
        log.info("indexed %d objects for retrieval (backend=%s)",
                 n, rag_service.backend.name)
    log.info("companion engine: %s",
             "claude" if llm_service.available() else "offline (no key / MOCK_LLM)")

    # Re-index whenever the scene changes (Twin Generator, Imagine commit).
    async def _reindex(_type: str, data: dict) -> None:
        if data.get("room_id"):
            rag_service.index_room(data)

    bus.subscribe("scene.updated", _reindex)

    yield

    if sim_instance:
        sim_instance.stop()
    await robot_service.shutdown()
    await mqtt_service.disconnect()
    log.info("RoomMind shutting down")


app = FastAPI(
    title="RoomMind API",
    version="0.1.0",
    description="Turn any room into an intelligent 3D world.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing_middleware(request, call_next):
    """Report total in-app time as X-Server-Time-Ms.

    Comparing this against a handler's own measurement tells you whether latency
    is your code or the framework - which is how we established that the e-stop
    handler is sub-millisecond and the rest is ASGI/loop overhead.
    """
    t0 = time.perf_counter()
    resp = await call_next(request)
    resp.headers["X-Server-Time-Ms"] = f"{(time.perf_counter() - t0) * 1000:.2f}"
    return resp

app.include_router(api_router)


@app.get("/")
async def root() -> dict:
    return {"name": "RoomMind", "docs": "/docs", "health": "/api/v1/health"}

import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

dist_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(dist_path):
    @app.get("/app")
    @app.get("/app/{full_path:path}")
    async def serve_spa(full_path: str = ""):
        return FileResponse(os.path.join(dist_path, "index.html"))

    app.mount("/", StaticFiles(directory=dist_path, html=True), name="frontend_dist")

