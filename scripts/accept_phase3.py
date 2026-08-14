"""Phase 3 acceptance — companion, grounding, embodied gestures."""
from __future__ import annotations

import json
import sys
import time

import httpx
import paho.mqtt.client as mqtt

BASE = "http://localhost:8000/api/v1"
telem: dict = {}
failures: list[str] = []


def on_connect(c, u, f, rc, p=None):
    c.subscribe("room/#", qos=0)


def on_message(c, u, msg):
    if "telemetry" in msg.topic:
        telem.update(json.loads(msg.payload))


cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="p3-accept")
cl.on_connect = on_connect
cl.on_message = on_message
cl.connect("localhost", 1883, 15)
cl.loop_start()
time.sleep(1.0)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def wait_until(pred, timeout=6.0, poll=0.05) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(poll)
    return False


print("PHASE 3 ACCEPTANCE\n")

with httpx.Client(base_url=BASE, timeout=30) as c:
    c.post("/estop/clear")
    c.delete("/chat/demo_room/history")

    # 1. counting is grounded and cites real ids
    r = c.post("/chat", json={"message": "How many chairs are there?"}).json()
    check("counting question answered", "two" in r["reply"].lower(), r["reply"][:60])
    check("cites both chairs", set(r["citations"]) == {"chair_01", "chair_02"},
          str(r["citations"]))
    check("engine reported", bool(r["engine"]), r["engine"])

    # 2. hallucination is impossible — asking for something absent
    r = c.post("/chat", json={"message": "How many pianos are there?"}).json()
    check("absent object denied, not invented",
          "don't see" in r["reply"].lower() and not r["citations"], r["reply"][:60])

    # 3. embodied grounding — "where" makes her POINT without being asked
    before = dict(telem.get("joints", {}))
    r = c.post("/chat", json={"message": "Where's the lamp?"}).json()
    check("locate question cites the lamp", r["citations"] == ["lamp_01"])
    check("gesture issued automatically", bool(r["gestures"]),
          json.dumps(r["gestures"]))
    check("gesture is point_at (not just look_at)",
          r["gestures"] and r["gestures"][0]["action"] == "point_at")
    moved = wait_until(
        lambda: abs(telem["joints"]["head_pan"] - before.get("head_pan", 0)) > 3
    )
    check("ARIA physically turns her head", moved,
          f"head_pan {before.get('head_pan', 0):.1f} -> {telem['joints']['head_pan']:.1f}")

    # Either arm — which one is correct depends on ARIA's current pose, which
    # carries over between runs. Side selection is asserted from a known pose in
    # test_kinematics.py; here the claim is just "an arm came up".
    ARM = ("l_shoulder_pitch", "l_shoulder_roll", "r_shoulder_pitch", "r_shoulder_roll")
    arm_moved = wait_until(
        lambda: any(abs(telem["joints"][k] - before.get(k, 0)) > 3 for k in ARM), 4
    )
    delta = {k: round(telem["joints"][k] - before.get(k, 0), 1) for k in ARM}
    check("ARIA raises an arm toward it", arm_moved, str(delta))

    # 4. a mention (not a "where") looks rather than points
    c.post("/estop/clear")
    r = c.post("/chat", json={"message": "What's in this room?"}).json()
    check("room summary cites many objects", len(r["citations"]) >= 5,
          f"{len(r['citations'])} citations")
    check("mention triggers look_at, not point_at",
          r["gestures"] and r["gestures"][0]["action"] == "look_at",
          json.dumps(r["gestures"]))

    # 5. chat -> command pipeline
    r = c.post("/chat", json={"message": "go to the table and point at the lamp"}).json()
    actions = [x["action"] for x in r["commands"]]
    check("two commands in sentence order", actions == ["navigate", "point_at"],
          str(actions))
    check("targets resolved to real ids",
          [x["target"] for x in r["commands"]] == ["table_01", "lamp_01"])

    # 6. synonyms
    r = c.post("/chat", json={"message": "where's the couch?"}).json()
    check("synonym 'couch' resolves to sofa_01", r["citations"] == ["sofa_01"],
          str(r["citations"]))

    # 7. history + suggestions
    h = c.get("/chat/demo_room/history").json()
    check("history records both sides", len(h) >= 12, f"{len(h)} messages")
    s = c.get("/chat/demo_room/suggestions").json()
    check("suggestions reference real objects", len(s) >= 3, s[0])

    # 8. latency budget (spec 14.3: < 1.5 s)
    t0 = time.perf_counter()
    r = c.post("/chat", json={"message": "How many chairs?"}).json()
    ms = (time.perf_counter() - t0) * 1000
    check("chat latency under 1.5 s", ms < 1500, f"{ms:.0f} ms round trip")

    # 9. e-stop must not be blocked by a chat gesture
    c.post("/estop")
    r = c.post("/chat", json={"message": "where's the tv?"}).json()
    check("answer still works while e-stopped", bool(r["reply"]))
    check("gesture suppressed while e-stopped", not r["gestures"],
          "words are the deliverable, movement is the flourish")
    c.post("/estop/clear")

cl.loop_stop()
print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
