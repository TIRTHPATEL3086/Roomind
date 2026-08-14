"""Phase 1 acceptance test - backend + broker + simulator, end to end."""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import httpx
import paho.mqtt.client as mqtt

BASE = "http://localhost:8000/api/v1"
telem: dict = {}
acks: list[dict] = []
estop_on_bus: list[float] = []
failures: list[str] = []


def on_connect(c, u, f, rc, p=None):
    c.subscribe("room/#", qos=0)


def on_message(c, u, msg):
    if msg.topic.endswith("/estop"):
        estop_on_bus.append(time.perf_counter())
    elif "telemetry" in msg.topic:
        telem.update(json.loads(msg.payload))
    elif "/ack/" in msg.topic:
        acks.append(json.loads(msg.payload))


cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="p1-accept")
cl.on_connect = on_connect
cl.on_message = on_message
cl.connect("localhost", 1883, 15)
cl.loop_start()
time.sleep(1.0)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def wait_until(pred, timeout: float, poll: float = 0.1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(poll)
    return False


print("PHASE 1 ACCEPTANCE\n")

# 1. telemetry at ~10 Hz with joints
n0 = telem.get("seq", 0)
time.sleep(2.0)
rate = (telem.get("seq", 0) - n0) / 2.0
check("telemetry arrives at ~10 Hz", 8 <= rate <= 12, f"{rate:.1f} Hz")
check("telemetry carries all 9 joints", len(telem.get("joints", {})) == 9)
check("robot reports online", telem.get("state") is not None)

# 2. navigate returns a real path
r = httpx.post(f"{BASE}/commands",
               json={"action": "navigate", "target": "table_01"}, timeout=10)
body = r.json()
check("POST /commands -> 200", r.status_code == 200)
check("navigate returns a path", bool(body.get("path")), f"{len(body.get('path') or [])} waypoints")
cid = body["command_id"]

# 3. the sim accepts it and drives
check("sim acked 'accepted'",
      wait_until(lambda: any(a["command_id"] == cid and a["status"] == "accepted"
                             for a in acks), 5))
check("ARIA starts driving",
      wait_until(lambda: telem.get("state") == "driving", 5),
      f"state={telem.get('state')}")

# 4. she arrives
arrived = wait_until(lambda: any(a["command_id"] == cid and a["status"] == "done"
                                 for a in acks), 40)
check("command completes", arrived)
# Measured from the table's SURFACE, not its centre.
#
# The old check took the distance to the centre and required it under 1.1 m.
# That only looked right because the demo table is small: the same rule applied
# to the 1.9 m sofa would demand ARIA stop a metre INSIDE it. Phase 6 gave the
# planner real stand-off points computed from each object's footprint, so she
# now parks 0.51 m clear of the table's edge - which is 1.2-1.3 m from its
# centre on the diagonal, and correct.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
from app.core import spatial                        # noqa: E402
from app.core.spatial import world_to_body          # noqa: E402
from app.services.planner_service import approach_distance   # noqa: E402

DEMO = json.loads((_ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))

TABLE = {"position": [0.85, 0.37, -0.90], "dimensions": [1.20, 0.74, 0.70],
         "rotation_y": 0.0}
px, pz = telem["pose"]["x"], telem["pose"]["z"]
gap = spatial.surface_gap(
    {"position": [px, 0.0, pz], "dimensions": [1e-3, 1e-3, 1e-3],
     "rotation_y": 0.0}, TABLE)
check("ARIA stopped clear of the table's surface",
      approach_distance() - 0.10 <= gap <= 0.95,
      f"{gap:.2f} m from the edge (target {approach_distance():.2f} m)")

# 5. backend mirrors the robot's live state
rob = httpx.get(f"{BASE}/robots/aria", timeout=10).json()
check("backend mirrors the pose",
      abs(rob["pose"]["x"] - px) < 0.3, f"api x={rob['pose']['x']:.2f} mqtt x={px:.2f}")
check("backend marks ARIA online", rob["online"] is True)

# 6. point_at moves the head AND an arm on the real sim
before = dict(telem["joints"])
httpx.post(f"{BASE}/commands", json={"action": "point_at", "target": "lamp_01"}, timeout=10)
moved = wait_until(
    lambda: abs(telem["joints"]["head_pan"] - before["head_pan"]) > 5.0, 6)
check("point_at turns ARIA's head", moved,
      f"head_pan {before['head_pan']:.1f} -> {telem['joints']['head_pan']:.1f} deg")
# Asserted as an END STATE, not as a change.
#
# The old form required the left shoulder to have MOVED by 5 degrees, which
# quietly assumed two things: that the lamp is on ARIA's left (it depends on
# where she parked, and Phase 6 changed where that is), and that her arm
# started down (it does not, on a simulator that has already run this script
# once - the arm is still up from the previous run, the delta is zero, and a
# correct point registers as a failure).
#
# What actually has to be true is that the arm on the TARGET'S side is
# extended. That is checkable from her live pose without assuming either.
lamp = next(o for o in DEMO["objects"] if o["id"] == "lamp_01")["position"]
pose_now = telem["pose"]
side, _ = world_to_body(lamp[0] - pose_now["x"], lamp[2] - pose_now["z"],
                        pose_now["yaw"])
arm = "r_shoulder_pitch" if side > 0 else "l_shoulder_pitch"
raised = wait_until(lambda: abs(telem["joints"][arm]) > 20.0, 6)
check("point_at raises the arm on the target's side", raised,
      f"lamp is {'right' if side > 0 else 'left'} of her, "
      f"{arm}={telem['joints'][arm]:.0f} deg")

# 7. e-stop halts her mid-drive within budget
#
# Measure request-start -> stop-observed-ON-THE-BUS. Waiting for telemetry to
# *report* state=estop instead adds up to a full 100 ms telemetry period of
# quantisation noise, which measures our own sampling rate, not the stop path.
httpx.post(f"{BASE}/commands", json={"action": "navigate", "target": "shelf_01"}, timeout=10)
wait_until(lambda: telem.get("state") == "driving", 6)

# Reuse one connection. A fresh TCP connect per request is client-side setup cost
# the robot never experiences, and on Windows the localhost IPv6->IPv4 fallback
# alone can add seconds - which would measure httpx, not the e-stop path.
with httpx.Client(base_url=BASE, timeout=10) as hc:
    hc.get("/health")                      # warm the pool
    estop_on_bus.clear()
    t0 = time.perf_counter()
    resp = hc.post("/estop")
    post_ms = (time.perf_counter() - t0) * 1000
    on_bus = wait_until(lambda: bool(estop_on_bus), 2, poll=0.001)
    latency_ms = (estop_on_bus[0] - t0) * 1000 if on_bus else float("inf")
    handler_ms = resp.json()["total_ms"]

check("e-stop reaches the bus", on_bus)
check("e-stop within the 200 ms budget", latency_ms < 200,
      f"{latency_ms:.1f} ms on the wire | handler {handler_ms:.2f} ms | POST {post_ms:.1f} ms")
check("robot enters estop state",
      wait_until(lambda: telem.get("state") == "estop", 2, poll=0.01))
check("velocity is zero after e-stop", abs(telem["vel"]["linear"]) < 0.01)
check("servos HOLD, they do not go limp",
      abs(telem["joints"]["l_shoulder_pitch"] - 0.0) > 1.0
      or abs(telem["joints"]["head_pan"]) > 1.0,
      "joints retained their last commanded pose")

httpx.post(f"{BASE}/estop/clear", timeout=10)
cl.loop_stop()

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
