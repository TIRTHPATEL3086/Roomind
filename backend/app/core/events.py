"""In-process pub/sub (spec 3, 1.4.2).

This is the ONLY upward path in the layered architecture. Orchestration publishes;
Presentation subscribes. A service never calls into the API layer directly.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

log = logging.getLogger("roommind.events")

Handler = Callable[[str, dict], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """`event_type` is a §8.7 type, or '*' for everything."""
        self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if handler in self._subs.get(event_type, []):
            self._subs[event_type].remove(handler)

    async def publish(self, event_type: str, data: dict) -> None:
        """Fan out concurrently. A failing subscriber is logged, never propagated -
        one broken WebSocket must not stop the robot's telemetry reaching the others."""
        handlers = [*self._subs.get(event_type, []), *self._subs.get("*", [])]
        if not handlers:
            return
        results = await asyncio.gather(
            *(h(event_type, data) for h in handlers), return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                log.warning("event subscriber failed for %s: %r", event_type, r)


bus = EventBus()
