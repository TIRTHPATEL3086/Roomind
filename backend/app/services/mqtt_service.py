"""MQTT transport (spec 9.3, 8.5). paho-mqtt 2.1.0.

Two rules here are load-bearing and easy to get wrong:
  1. `loop_start()` inside connect() - without it no callback ever fires.
  2. Subscriptions are (re-)registered inside `_on_connect`, NOT after connect().
     Subscribe-after-connect silently loses every subscription on reconnect, and
     you get a robot that works until the Wi-Fi blips once (spec 18.3).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

import paho.mqtt.client as mqtt

from app.config import get_settings

log = logging.getLogger("roommind.mqtt")

Handler = Callable[[str, dict], Awaitable[None]]

# ── topic map (spec 8.5) ──
T_CMD = "room/cmd/{robot_id}"
T_ESTOP = "room/cmd/{robot_id}/estop"
T_PATH = "room/path/{robot_id}"
T_TELEMETRY = "room/telemetry/{robot_id}"
T_STATUS = "room/status/{robot_id}"
T_ACK = "room/ack/{robot_id}"
T_EVENT = "room/event/{robot_id}"
T_SCAN = "room/scan/{room_id}"

SUBSCRIPTIONS: tuple[tuple[str, int], ...] = (
    ("room/telemetry/+", 0),
    ("room/status/+", 1),
    ("room/ack/+", 1),
    ("room/event/+", 1),
)


def _topic_to_regex(pattern: str) -> re.Pattern[str]:
    """MQTT wildcards -> regex. '+' is one level, '#' is the rest."""
    out = []
    for part in pattern.split("/"):
        if part == "+":
            out.append(r"[^/]+")
        elif part == "#":
            out.append(r".*")
        else:
            out.append(re.escape(part))
    return re.compile("^" + "/".join(out) + "$")


class MqttService:
    def __init__(self) -> None:
        self.s = get_settings()
        self._client: mqtt.Client | None = None
        self._handlers: list[tuple[re.Pattern[str], Handler]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.connected = False

    # ── wiring ──

    def on(self, topic_pattern: str, handler: Handler) -> None:
        """Register before connect(). Handlers are async and run on the event loop."""
        self._handlers.append((_topic_to_regex(topic_pattern), handler))

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.s.mqtt_client_id,
            protocol=mqtt.MQTTv311,
        )
        if self.s.mqtt_username:
            client.username_pw_set(self.s.mqtt_username, self.s.mqtt_password)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        self._client = client
        try:
            client.connect_async(self.s.mqtt_host, self.s.mqtt_port, keepalive=15)
            client.loop_start()          # REQUIRED - no callbacks fire without it
            log.info("MQTT connecting to %s:%s", self.s.mqtt_host, self.s.mqtt_port)
        except Exception as e:  # noqa: BLE001
            log.warning("MQTT connect failed (%s) - running without a broker", e)

    async def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self.connected = False

    # ── paho callbacks (these run on paho's thread, NOT the event loop) ──

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code != 0:
            log.error("MQTT connect refused: %s", reason_code)
            return
        self.connected = True
        # Re-subscribe HERE so a reconnect restores every subscription.
        for topic, qos in SUBSCRIPTIONS:
            client.subscribe(topic, qos=qos)
        log.info("MQTT connected; subscribed to %d topics", len(SUBSCRIPTIONS))

    def _on_disconnect(self, client, userdata, *args) -> None:
        self.connected = False
        log.warning("MQTT disconnected - paho will retry automatically")

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("dropping non-JSON message on %s", msg.topic)
            return

        try:
            loop = self._loop or asyncio.get_event_loop()
            if loop and loop.is_running():
                for pattern, handler in self._handlers:
                    if pattern.match(msg.topic):
                        asyncio.run_coroutine_threadsafe(
                            handler(msg.topic, payload), loop
                        )
        except Exception as e:  # noqa: BLE001
            log.debug("error dispatching MQTT message: %s", e)

    # ── publishing ──

    def publish(self, topic: str, payload: dict, qos: int | None = None,
                retain: bool = False) -> None:
        if not self._client:
            log.debug("publish skipped, no MQTT client: %s", topic)
            return
        self._client.publish(
            topic,
            json.dumps(payload, separators=(",", ":")),
            qos=self.s.mqtt_qos if qos is None else qos,
            retain=retain,
        )

    def publish_command(self, robot_id: str, command: dict) -> None:
        self.publish(T_CMD.format(robot_id=robot_id), command, qos=1)

    def publish_path(self, robot_id: str, command_id: str,
                     waypoints: list[tuple[float, float]], speed: float) -> None:
        self.publish(
            T_PATH.format(robot_id=robot_id),
            {"command_id": command_id,
             "waypoints": [[round(x, 4), round(z, 4)] for x, z in waypoints],
             "speed": speed},
            qos=1,
        )

    def publish_estop(self, robot_id: str, ts: float) -> None:
        """QoS 0 on the dedicated topic, for the lowest possible latency.
        The caller MUST invoke this before any DB write (spec 8.5, 9.10)."""
        self.publish(T_ESTOP.format(robot_id=robot_id), {"stop": True, "ts": ts}, qos=0)

    def publish_estop_clear(self, robot_id: str, ts: float) -> None:
        """Release the robot's e-stop latch.

        The robot latches on stop and refuses everything until released - correct
        and deliberate. But without this the latch is one-way: clearing only the
        backend's flag leaves ARIA frozen forever while the API cheerfully reports
        her ready. Uses the same topic with stop=false, so the topic map is
        unchanged. QoS 1: unlike the stop itself, this must not be lost.
        """
        self.publish(T_ESTOP.format(robot_id=robot_id), {"stop": False, "ts": ts}, qos=1)


mqtt_service = MqttService()
