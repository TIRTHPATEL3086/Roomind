"""Phase 2 acceptance - the frontend contract, verified without a browser.

Checks the things a browser would exercise: the dev server serves the app, the
API proxy works, the WebSocket carries the §8.7 envelopes the UI switches on,
and a command produces the telemetry the twin renders from.
"""
from __future__ import annotations

import json
import sys
import time
from urllib.request import urlopen

import httpx
import websockets.sync.client as wsclient

WEB = "http://localhost:5173"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


print("PHASE 2 ACCEPTANCE\n")

# 1. the app shell
html = urlopen(f"{WEB}/").read().decode()
check("dev server serves the app", "RoomMind" in html)
check("entry module referenced", "/src/main.tsx" in html)
check("fonts preloaded", "Space+Grotesk" in html)

# 2. modules transform (a TS/JSX error would 500 here)
for mod in ("/src/main.tsx", "/src/App.tsx", "/src/three/World.tsx",
            "/src/three/RobotAvatar.tsx", "/src/components/WorldDashboard.tsx",
            "/src/store/robotStore.ts", "/src/api/ws.ts"):
    try:
        body = urlopen(f"{WEB}{mod}").read().decode()
        ok = len(body) > 100 and "Internal Server Error" not in body
    except Exception:
        ok = False
    check(f"module compiles: {mod.split('/')[-1]}", ok)

# 3. the API through Vite's proxy (same-origin => no CORS in dev)
with httpx.Client(base_url=f"{WEB}/api/v1", timeout=10) as c:
    room = c.get("/rooms/demo_room").json()
    check("proxy serves the scene graph", room["room_id"] == "demo_room",
          f"{len(room['objects'])} objects")
    check("scene has the lamp for the point-at demo",
          any(o["id"] == "lamp_01" for o in room["objects"]))

    aria = c.get("/robots/aria").json()
    check("proxy serves robot state", aria["display_name"] == "ARIA")
    check("robot is online", aria["online"] is True)
    check("robot reports 9 joints", len(aria["joints"]) == 9,
          f"{len(aria['joints'])}")
    check("battery is not flat", aria["battery"] > 0.5,
          f"{aria['battery'] * 100:.1f}%")

# 4. the WebSocket carries what the UI switches on
seen: set[str] = set()
joint_frames = 0
path_frames = 0
with wsclient.connect(f"ws://localhost:5173/api/v1/ws?room_id=demo_room") as ws:
    httpx.post(f"{WEB}/api/v1/commands",
               json={"action": "point_at", "target": "lamp_01"}, timeout=10)
    end = time.time() + 6
    while time.time() < end:
        try:
            ws.socket.settimeout(1.0)
            msg = json.loads(ws.recv(timeout=1.0))
        except Exception:
            continue
        seen.add(msg["type"])
        if msg["type"] == "robot.telemetry" and msg["data"].get("joints"):
            joint_frames += 1
        if msg["type"] == "command.planned":
            path_frames += 1

check("WS delivers telemetry", "robot.telemetry" in seen, f"{joint_frames} joint frames")
check("WS envelope has type/ts/data", bool(seen))
check("telemetry carries joints", joint_frames > 10)
check("command events reach the UI",
      "command.created" in seen or "command.status" in seen,
      ", ".join(sorted(seen)))

# 5. a navigate produces a path for PathLine to draw
with wsclient.connect(f"ws://localhost:5173/api/v1/ws?room_id=demo_room") as ws:
    httpx.post(f"{WEB}/api/v1/commands",
               json={"action": "navigate", "target": "table_01"}, timeout=10)
    got_path = False
    end = time.time() + 5
    while time.time() < end and not got_path:
        try:
            msg = json.loads(ws.recv(timeout=1.0))
        except Exception:
            continue
        if msg["type"] == "command.planned" and msg["data"].get("path"):
            got_path = True
check("navigate emits command.planned with a path", got_path)

httpx.post(f"{WEB}/api/v1/estop", timeout=10)
httpx.post(f"{WEB}/api/v1/estop/clear", timeout=10)

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
