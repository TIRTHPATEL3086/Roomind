"""Watch the MQTT bus for a few seconds and report what ARIA is publishing."""
import json
import sys
import time
from collections import Counter

import paho.mqtt.client as mqtt

seen = Counter()
last_telem = {}
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0


def on_connect(c, u, f, rc, p=None):
    c.subscribe("room/#", qos=0)


def on_message(c, u, msg):
    seen[msg.topic] += 1
    if "telemetry" in msg.topic:
        last_telem.update(json.loads(msg.payload))


cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sniffer")
cl.on_connect = on_connect
cl.on_message = on_message
cl.connect("localhost", 1883, 15)
cl.loop_start()
time.sleep(DURATION)
cl.loop_stop()

print(f"--- topics seen in {DURATION:.0f}s ---")
for t, n in sorted(seen.items()):
    rate = n / DURATION
    print(f"  {t:<34} {n:4d} msgs  ({rate:5.1f} Hz)")

if last_telem:
    p = last_telem["pose"]
    print("\n--- latest telemetry ---")
    print(f"  state    {last_telem['state']}")
    print(f"  pose     x={p['x']:+.3f}  z={p['z']:+.3f}  yaw={p['yaw']:+.3f} rad")
    print(f"  battery  {last_telem['battery']*100:.2f}%")
    print(f"  emotion  {last_telem['emotion']}")
    print("  joints   " + "  ".join(
        f"{k}={v:+.1f}" for k, v in list(last_telem["joints"].items())[:4]))
    print("           " + "  ".join(
        f"{k}={v:+.1f}" for k, v in list(last_telem["joints"].items())[4:]))
else:
    print("\nNO TELEMETRY RECEIVED")
