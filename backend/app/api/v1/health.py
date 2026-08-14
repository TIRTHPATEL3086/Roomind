"""Health endpoint with REAL liveness probes (spec 8.6, Phase 0 item 6).

Each dependency is actually contacted. A hard-coded {"db":"ok"} is a lie that costs
you an hour of debugging on demo day, so every probe here really connects.
"""
from __future__ import annotations

import asyncio
import socket

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings

router = APIRouter()

VERSION = "0.1.0"
PROBE_TIMEOUT_S = 2.0


async def _probe_db() -> str:
    try:
        from app.db.session import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as e:  # noqa: BLE001 - a health probe must never raise
        return f"down: {type(e).__name__}"


async def _probe_redis() -> str:
    s = get_settings()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(s.redis_url, socket_connect_timeout=PROBE_TIMEOUT_S)
        try:
            await client.ping()
            return "ok"
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001
        return f"down: {type(e).__name__}"


def _probe_tcp(host: str, port: int) -> str:
    """Plain TCP reachability - used for MQTT, where a full CONNECT handshake
    would be slower than the whole rest of this endpoint."""
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_S):
            return "ok"
    except Exception as e:  # noqa: BLE001
        return f"down: {type(e).__name__}"


async def _probe_mqtt() -> str:
    s = get_settings()
    return await asyncio.to_thread(_probe_tcp, s.mqtt_host, s.mqtt_port)


async def _probe_chroma() -> str:
    s = get_settings()
    try:
        import httpx

        url = f"http://{s.chroma_host}:{s.chroma_port}/api/v1/heartbeat"
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            r = await client.get(url)
        return "ok" if r.status_code == 200 else f"down: HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return f"down: {type(e).__name__}"


@router.get("/health")
async def health() -> dict:
    db, redis_, mqtt, chroma = await asyncio.gather(
        _probe_db(), _probe_redis(), _probe_mqtt(), _probe_chroma()
    )
    services = {"db": db, "redis": redis_, "mqtt": mqtt, "chroma": chroma}
    status = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": status, "version": VERSION, "services": services}
