"""WebSocket hub (spec 8.7).

Every frame is exactly {"type": ..., "ts": ..., "data": {...}}. No other shape is
permitted - the frontend switch in api/ws.ts depends on it byte-for-byte.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.events import bus

log = logging.getLogger("roommind.ws")
router = APIRouter()


class WSHub:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, room_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms[room_id].add(ws)
        log.info("ws connected room=%s (%d client(s))", room_id, len(self._rooms[room_id]))

    def disconnect(self, room_id: str, ws: WebSocket) -> None:
        self._rooms[room_id].discard(ws)

    def client_count(self, room_id: str) -> int:
        return len(self._rooms.get(room_id, ()))

    async def broadcast(self, room_id: str, type_: str, data: dict) -> None:
        msg = {"type": type_, "ts": time.time(), "data": data}
        dead: list[WebSocket] = []
        for ws in list(self._rooms.get(room_id, ())):
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001 - a dead socket must not stop the others
                dead.append(ws)
        for ws in dead:
            self.disconnect(room_id, ws)

    async def broadcast_all(self, type_: str, data: dict) -> None:
        for room_id in list(self._rooms):
            await self.broadcast(room_id, type_, data)


ws_hub = WSHub()


async def _relay(event_type: str, data: dict) -> None:
    """Bridge the in-process bus to every connected browser."""
    room_id = data.get("room_id")
    if room_id:
        await ws_hub.broadcast(room_id, event_type, data)
    else:
        await ws_hub.broadcast_all(event_type, data)


bus.subscribe("*", _relay)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, room_id: str = Query(...)) -> None:
    await ws_hub.connect(room_id, ws)
    try:
        while True:
            await ws.receive_text()      # keepalive pings from the client
    except WebSocketDisconnect:
        ws_hub.disconnect(room_id, ws)
    except Exception as e:  # noqa: BLE001
        log.warning("ws error room=%s: %r", room_id, e)
        ws_hub.disconnect(room_id, ws)
