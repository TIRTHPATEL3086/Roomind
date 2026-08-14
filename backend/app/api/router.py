from fastapi import APIRouter

from app.api.v1 import chat, commands, health, imagine, nav, rooms, scan, ws

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(rooms.router, tags=["rooms"])
api_router.include_router(commands.router, tags=["commands"])
api_router.include_router(nav.router, tags=["nav"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(imagine.router, tags=["imagine"])
api_router.include_router(scan.router, tags=["scan"])
api_router.include_router(ws.router, tags=["ws"])
