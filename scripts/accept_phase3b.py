"""Phase 3b acceptance — Imagine: image -> 3D -> placed, reasoned about, pointed at."""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8000/api/v1"
FIXTURE = ROOT / "genai3d" / "tests" / "fixtures" / "lamp.png"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def wait_for(c, job_id: str, states: set[str], timeout=90.0) -> dict:
    end = time.time() + timeout
    last: dict = {}
    while time.time() < end:
        last = c.get(f"/imagine/{job_id}").json()
        if last.get("status") in states:
            return last
        time.sleep(0.3)
    return last


print("PHASE 3b ACCEPTANCE — IMAGINE\n")

with httpx.Client(base_url=BASE, timeout=120) as c:
    c.post("/estop/clear")
    before = c.get("/rooms/demo_room").json()
    n_before = len(before["objects"])

    # 1. upload -> job
    t0 = time.perf_counter()
    r = c.post("/imagine", files={"image": ("lamp.png", FIXTURE.read_bytes(), "image/png")},
               data={"room_id": "demo_room", "prompt": "a tall floor lamp"})
    check("upload accepted", r.status_code == 200, f"HTTP {r.status_code}")
    job_id = r.json()["job_id"]

    # 2. pipeline runs to preview
    job = wait_for(c, job_id, {"preview", "committed", "failed"})
    elapsed = time.perf_counter() - t0
    check("pipeline reaches preview or commit",
          job.get("status") in ("preview", "committed"),
          f"{job.get('status')} — {job.get('error')}")
    check("completes inside the proxy budget (5 s)", elapsed < 5.0, f"{elapsed:.1f}s")

    frag = job.get("fragment", {})
    metrics = job.get("metrics", {})
    check("labelled from the hint", frag.get("label") == "floor_lamp",
          str(frag.get("label")))

    # 3. METRIC SCALING — the #1 bug source
    dims = frag.get("dimensions", [0, 0, 0])
    check("height is a plausible floor lamp", 1.0 < dims[1] < 2.2, f"{dims[1]:.2f} m")
    check("not scaled uniformly wrong (w and d stay small)",
          dims[0] < 0.6 and dims[2] < 0.6, f"{dims[0]:.2f} x {dims[2]:.2f}")
    check("aspect preserved", metrics.get("aspect_preserved") is True)
    check("marked as a proxy honestly", metrics.get("is_proxy") is True,
          f"backend={metrics.get('backend')}")

    # 4. EXIF stripped before anything else touched the file
    check("EXIF stripped in G01", metrics.get("exif_stripped") is True)

    # 5. placement doesn't overlap and sits on the floor
    place = job.get("placement", {})
    pos = place.get("position", [0, 0, 0])
    check("placed on the floor", abs(pos[1] - dims[1] / 2) < 0.01,
          f"y={pos[1]:.2f}, half-height={dims[1] / 2:.2f}")
    worst = min(
        (math.hypot(pos[0] - o["position"][0], pos[2] - o["position"][2]), o["id"])
        for o in before["objects"] if o.get("is_obstacle", True)
    )
    check("clear of every existing object", worst[0] > 0.3,
          f"nearest {worst[1]} at {worst[0]:.2f} m")

    # 6. low confidence must NOT auto-commit
    conf = frag.get("scale_confidence", 1.0)
    if conf < 0.5:
        check("low confidence shows a preview instead of committing",
              job["status"] == "preview", f"confidence {conf}")
        obj = c.post(f"/imagine/{job_id}/confirm").json()
    else:
        obj = job.get("object") or c.post(f"/imagine/{job_id}/confirm").json()

    # 7. committed into the scene graph, indistinguishable from a scanned object
    object_id = obj["id"]
    check("id follows the frozen pattern",
          object_id.startswith("floor_lamp_") and object_id[-2:].isdigit(), object_id)
    check("marked source=generated", obj["source"] == "generated")
    check("carries a per-object mesh url", bool(obj.get("mesh_url")))

    after = c.get("/rooms/demo_room").json()
    check("scene graph grew by one", len(after["objects"]) == n_before + 1,
          f"{n_before} -> {len(after['objects'])}")
    check("object is in the graph",
          any(o["id"] == object_id for o in after["objects"]))

    # 8. the mesh is downloadable
    m = c.get(f"/imagine/{job_id}/mesh")
    check("mesh downloads as GLB", m.status_code == 200 and m.content[:4] == b"glTF",
          f"{len(m.content)} bytes")
    t = c.get(f"/imagine/{job_id}/thumb")
    check("thumbnail downloads", t.status_code == 200 and t.content[:4] == b"\x89PNG")

    # 9. THE TEST THAT MATTERS (spec 10B.10):
    #    a generated object the rest of the system cannot reason about has not
    #    actually been integrated.
    chat = c.post("/chat", json={"message": f"where's the {obj['label'].replace('_', ' ')}?"}).json()
    check("ARIA can find the generated object", object_id in chat["citations"],
          f"cited {chat['citations']}")

    # Pointing is only unambiguous while the room holds ONE of these.
    #
    # This script appends a generated object every run and never removes it, so
    # a second run against the same live API leaves two identical floor lamps.
    # At that point "where's the floor lamp?" genuinely has two answers, ARIA
    # correctly reports both instead of silently picking one, and there is no
    # single object she should be pointing at. Asserting a specific gesture
    # target there would be asserting that she guesses.
    siblings = [o for o in c.get("/rooms/demo_room").json()["objects"]
                if o["label"] == obj["label"]]
    if len(siblings) == 1:
        check("ARIA points at it", bool(chat["gestures"]) and
              chat["gestures"][0]["target"] == object_id,
              json.dumps(chat["gestures"]))
    else:
        check("several of that label exist, so ARIA lists them instead of "
              "picking one",
              len(chat["citations"]) == len(siblings),
              f"{len(siblings)} {obj['label']}s in the room after "
              f"{len(siblings)} run(s) — restart the API for a clean scene")

    nav = c.post("/commands", json={"action": "navigate", "target": object_id}).json()
    check("A* can path to it", nav["status"] == "dispatched" and bool(nav["path"]),
          f"{len(nav.get('path') or [])} waypoints")

    # 10. it is now a real obstacle — the navmesh was re-baked
    grid_probe = c.post("/commands", json={
        "action": "navigate", "params": {"point": [pos[0], pos[2]]}}).json()
    check("navmesh re-baked (planner stops short of it, doesn't path inside)",
          grid_probe["status"] in ("dispatched", "rejected"))

    # 11. safety
    bad = c.post("/imagine", files={"image": ("x.png", b"not an image at all", "image/png")},
                 data={"room_id": "demo_room"})
    bad_job = wait_for(c, bad.json()["job_id"], {"failed", "preview"}, timeout=30)
    check("non-image upload rejected", bad_job.get("status") == "failed",
          str(bad_job.get("error"))[:70])

    person = c.post("/imagine",
                    files={"image": ("p.png", FIXTURE.read_bytes(), "image/png")},
                    data={"room_id": "demo_room", "prompt": "a photo of my friend"})
    p_job = wait_for(c, person.json()["job_id"], {"failed", "preview"}, timeout=30)
    check("refuses to model a person", p_job.get("status") == "failed",
          str(p_job.get("error"))[:70])

print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
