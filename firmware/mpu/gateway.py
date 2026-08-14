"""MPU Serial/MQTT Gateway (Phase 7).

Bridges MQTT telemetry & commands between backend broker and Arduino MCU over Serial.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional
import paho.mqtt.client as mqtt

log = logging.getLogger("aria.mpu.gateway")

class AriaMpuGateway:
    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883, serial_port: Optional[str] = None):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.serial_port = serial_port
        self.client = mqtt.Client(client_id="aria-mpu-gateway", protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.running = False

    def _on_connect(self, client, userdata, flags, rc):
        log.info(f"Connected to MQTT broker with rc={rc}")
        self.client.subscribe("roommind/aria/commands/+")
        self.client.subscribe("roommind/aria/estop")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode("utf-8"))
            if topic == "roommind/aria/estop":
                self._send_serial("ESTOP\n")
            elif "joint_target" in payload:
                # Forward to MCU
                joints = payload["joint_target"]
                cmd = f"SET_JOINTS {joints.get('head_pan', 0)} {joints.get('head_tilt', 0)}\n"
                self._send_serial(cmd)
        except Exception as e:
            log.error(f"Error handling message on {msg.topic}: {e}")

    def _send_serial(self, data: str):
        log.info(f"[Serial TX]: {data.strip()}")

    def start(self):
        self.running = True
        self.client.connect(self.broker_host, self.broker_port, 60)
        self.client.loop_start()

    def stop(self):
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gw = AriaMpuGateway()
    gw.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gw.stop()
