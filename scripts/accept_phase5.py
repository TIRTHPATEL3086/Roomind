"""Phase 5 acceptance — Twin Generator: 3D reconstruction.

The spec asks for object dimensions "within +/-15% of tape-measured ground
truth for 3 objects". This checks all seven, against RENDERED ground truth
rather than a tape measure: reconstruction/synth/make_room.py builds a room
whose every dimension, position and yaw is known exactly, then emits only what
a depth-equipped phone emits (RGB frames, depth frames, intrinsics). The
pipeline never sees the answers.

That is a stricter test than the spec asks for, and a repeatable one. What it
is NOT is a test on real footage -- see the CAVEATS section printed at the end.

Usage:
    python scripts/accept_phase5.py              # pipeline + scene graph only
    python scripts/accept_phase5.py --with-api   # also exercise POST /scan
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECON = ROOT / "reconstruction"
SCAN = ROOT / "storage" / "scans" / "synth_demo"
OUT = ROOT / "storage" / "meshes" / "accept5"
BASE = "http://localhost:8000/api/v1"

DIM_TOLERANCE = 0.15          # spec: +/-15%
POS_TOLERANCE_M = 0.25
TIME_BUDGET_S = 180.0         # spec: < 3 min

failures: list[str] = []
total = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global total
    total += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def venv_python(sub: str) -> Path:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = ROOT / sub / ".venv" / rel
        if p.exists():
            return p
    return Path(sys.executable)


def aabb(dims, yaw_rad):
    """World-axis extents of a yaw-rotated box, so orientation conventions
    cannot make a correct box look wrong."""
    c, s = abs(math.cos(yaw_rad)), abs(math.sin(yaw_rad))
    return (dims[0] * c + dims[2] * s, dims[1], dims[0] * s + dims[2] * c)


print("PHASE 5 ACCEPTANCE — TWIN GENERATOR\n")

ap = argparse.ArgumentParser()
ap.add_argument("--with-api", action="store_true")
ap.add_argument("--skip-run", action="store_true",
                help="reuse the previous output in storage/meshes/accept5")
args = ap.parse_args()

# ─────────────────────────────── 0. fixture ────────────────────────────────
print("0. fixture")
truth_path = SCAN / "ground_truth.json"
if not truth_path.exists():
    print(f"  FAIL  synthetic capture missing. Build it with:\n"
          f"        cd reconstruction && .venv/Scripts/python synth/make_room.py "
          f"--out ../storage/scans/synth_demo --frames 40 --write-poses")
    sys.exit(1)
truth = json.loads(truth_path.read_text(encoding="utf-8"))
n_frames = len(list((SCAN / "frames").iterdir()))
check("synthetic capture present", n_frames >= 30, f"{n_frames} frames")
check("ground truth has objects", len(truth["objects"]) >= 5,
      f"{len(truth['objects'])} objects")

# ────────────────────────────── 1. the run ─────────────────────────────────
print("\n1. pipeline")
elapsed = 0.0
if not args.skip_run:
    cmd = [
        str(venv_python("reconstruction")), str(RECON / "pipeline.py"),
        "--input", str(SCAN), "--out", str(OUT),
        "--room-id", "accept5", "--scan-id", "accept5",
        "--intrinsics", str(SCAN / "intrinsics.json"),
        "--pose-backend", "known", "--detector", "geometric",
        "--quality", "medium", "--quiet",
    ]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    check("pipeline exits cleanly", r.returncode in (0, 3),
          f"exit {r.returncode}: {r.stderr.strip()[-200:]}")
    check(f"completes in under {TIME_BUDGET_S:.0f}s", elapsed < TIME_BUDGET_S,
          f"{elapsed:.1f}s")

room_json = OUT / "room.json"
if not room_json.exists():
    print("  FAIL  no room.json produced")
    sys.exit(1)
graph = json.loads(room_json.read_text(encoding="utf-8"))

# ──────────────────────────── 2. the artefacts ─────────────────────────────
print("\n2. emitted artefacts (spec 10.1)")
for name in ("room.glb", "room.json", "navmesh.npy"):
    p = OUT / name
    check(f"{name} exists", p.exists(),
          f"{p.stat().st_size / 1e6:.2f} MB" if p.exists() else "")

glb_mb = (OUT / "room.glb").stat().st_size / 1e6
check("mesh is inside MESH_MAX_MB (25)", glb_mb <= 25, f"{glb_mb:.2f} MB")
check("mesh is under the 150k triangle budget",
      graph["mesh"]["tri_count"] <= 150_000, f"{graph['mesh']['tri_count']} tris")

# ───────────────────────── 3. schema and id contract ───────────────────────
print("\n3. contract (spec 8.2)")
sys.path.insert(0, str(RECON))
import jsonschema  # noqa: E402

schema = json.loads((ROOT / "contracts" / "scene_graph.schema.json")
                    .read_text(encoding="utf-8"))
errors = list(jsonschema.Draft202012Validator(schema).iter_errors(graph))
check("room.json validates with ZERO errors", not errors,
      "; ".join(str(e.message)[:80] for e in errors[:3]))

import re  # noqa: E402
bad_ids = [o["id"] for o in graph["objects"]
           if not re.fullmatch(r"^[a-z_]+_[0-9]{2}$", o["id"])]
check("every object id matches the frozen pattern", not bad_ids, ", ".join(bad_ids))
check("units are metres and up-axis is Y",
      graph["units"] == "meters" and graph.get("up_axis") == "Y")

# ────────────────────────── 4. geometry vs truth ───────────────────────────
print("\n4. geometry against exact ground truth")
tolerance = POS_TOLERANCE_M
matched, unmatched = [], []
remaining = list(graph["objects"])

for gt in truth["objects"]:
    gp = gt["position"]
    best, best_d = None, 1e9
    for obj in remaining:
        d = math.dist(obj["position"], gp)
        if d < best_d:
            best, best_d = obj, d
    if best is not None and best_d <= tolerance:
        remaining.remove(best)
        matched.append((gt, best, best_d))
    else:
        unmatched.append(gt)

check(f"at least 5 of {len(truth['objects'])} objects found",
      len(matched) >= 5, f"{len(matched)} matched, "
      f"missed: {', '.join(o['label'] for o in unmatched) or 'none'}")
check("no phantom objects invented", len(remaining) == 0,
      f"{len(remaining)} extra: {', '.join(o['id'] for o in remaining)}")

print(f"\n     {'object':<14} {'pos err':>8}  {'W':>14} {'H':>14} {'D':>14}")
within = 0
for gt, obj, d in sorted(matched, key=lambda m: m[0]["label"]):
    want = aabb(gt["dimensions"], math.radians(gt["rotation_y_deg"]))
    got = aabb(obj["dimensions"], obj.get("rotation_y", 0.0))
    errs = [abs(g - w) / w for g, w in zip(got, want)]
    ok = max(errs) <= DIM_TOLERANCE
    within += ok
    cells = " ".join(f"{g:.2f}/{w:.2f} {e*100:4.0f}%" for g, w, e in
                     zip(got, want, errs))
    print(f"     {gt['label']:<14} {d*100:6.1f}cm  {cells}  {'OK' if ok else 'OVER'}")

check(f"at least 3 objects within +/-{DIM_TOLERANCE*100:.0f}% on EVERY axis",
      within >= 3, f"{within} of {len(matched)}")
check("all matched objects within 25 cm",
      all(d <= POS_TOLERANCE_M for _, _, d in matched),
      f"worst {max((d for _, _, d in matched), default=0)*100:.0f} cm")

# ───────────────────────── 5. the floor-snap rule ──────────────────────────
print("\n5. post-processing rules (spec 10.7)")
floor_y = graph["floor_y"]
check("floor plane recovered", abs(floor_y - truth["floor_y"]) < 0.05,
      f"{floor_y:.3f} vs {truth['floor_y']:.3f}")

floating = [
    f"{o['id']} {o['position'][1] - o['dimensions'][1] / 2 - floor_y:+.3f}m"
    for o in graph["objects"]
    if o["label"] in {"chair", "table", "sofa", "shelf", "desk", "potted_plant",
                      "bed", "bench", "stool", "object"}
    and abs((o["position"][1] - o["dimensions"][1] / 2) - floor_y) > 0.02
]
check("no floor-standing object floats or sinks", not floating,
      ", ".join(floating))

check("is_obstacle set for everything over 10 cm tall",
      all(o.get("is_obstacle") for o in graph["objects"]
          if o["dimensions"][1] > 0.10))
lampshades = [o["id"] for o in graph["objects"]
              if "surface_height" in o and not o.get("is_climbable")]
check("surface_height only on climbable surfaces", not lampshades,
      ", ".join(lampshades))

# room bounds
bx = graph["bounds"]["max"][0] - graph["bounds"]["min"][0]
bz = graph["bounds"]["max"][2] - graph["bounds"]["min"][2]
tx, _, tz = truth["room_size"]
check("room footprint within 10% of truth",
      abs(bx - tx) / tx < 0.10 and abs(bz - tz) / tz < 0.10,
      f"{bx:.2f}x{bz:.2f} vs {tx}x{tz}")

# ───────────────────────────── 6. navmesh ──────────────────────────────────
print("\n6. navmesh")
import numpy as np  # noqa: E402

grid = np.load(OUT / "navmesh.npy")
nav = graph["navmesh"]
check("navmesh matches its declared shape",
      grid.shape == (nav["height"], nav["width"]),
      f"{grid.shape} vs ({nav['height']}, {nav['width']})")
check("navmesh resolution is 5 cm", abs(nav["resolution"] - 0.05) < 1e-9)
blocked = float(grid.mean())
check("navmesh is neither empty nor solid", 0.01 < blocked < 0.6,
      f"{blocked*100:.1f}% blocked")

dock = graph["robot_dock"]
gx = int((dock[0] - nav["origin"][0]) / nav["resolution"])
gz = int((dock[2] - nav["origin"][1]) / nav["resolution"])
in_grid = 0 <= gx < nav["width"] and 0 <= gz < nav["height"]
check("robot dock is inside the grid and unobstructed",
      in_grid and grid[gz, gx] == 0,
      f"cell ({gx},{gz})" + ("" if in_grid else " OUT OF GRID"))

# ─────────────────────── 7. drift detector calibration ─────────────────────
print("\n7. drift detection")
scan_meta = graph.get("scan", {})
check("scan provenance recorded in room.json",
      bool(scan_meta.get("pose_backend")) and bool(scan_meta.get("detector")),
      f"{scan_meta.get('pose_backend')} / {scan_meta.get('detector')}")
check("a healthy reconstruction is NOT flagged as drifted",
      not any("drifted" in w for w in scan_meta.get("warnings", [])),
      "; ".join(scan_meta.get("warnings", []))[:120])

# ────────────────────────────── 8. the API ─────────────────────────────────
if args.with_api:
    print("\n8. API (needs `make api`)")
    import httpx  # noqa: E402

    try:
        with httpx.Client(base_url=BASE, timeout=300) as c:
            r = c.post("/scan", data={
                "scan_dir": str(SCAN), "room_id": "accept5_api",
                "detector": "geometric", "pose_backend": "known"})
            check("POST /scan accepted", r.status_code == 200,
                  f"HTTP {r.status_code}")
            scan_id = r.json()["scan_id"]

            deadline = time.time() + 300
            job = {}
            while time.time() < deadline:
                job = c.get(f"/scan/{scan_id}").json()
                if job["status"] in ("completed", "failed", "cancelled"):
                    break
                time.sleep(1.0)
            check("scan reaches completed", job.get("status") == "completed",
                  f"{job.get('status')}: {job.get('error')}")
            check("the room reaches the scene graph",
                  c.get("/rooms/accept5_api").status_code == 200)
            check("GET /rooms/{id}/mesh serves the glb",
                  c.get("/rooms/accept5_api/mesh").status_code == 200)
            check("GET /rooms/{id}/navmesh serves the grid",
                  c.get("/rooms/accept5_api/navmesh").status_code == 200)
    except Exception as e:  # noqa: BLE001
        check("API reachable", False, str(e)[:160])
else:
    print("\n8. API — skipped (pass --with-api with the server running)")

# ────────────────────────────── verdict ────────────────────────────────────
print("\n" + "-" * 66)
print("CAVEATS — what this run does NOT prove:")
for line in (
        "no real phone footage was available, so the whole chain is validated",
        "  on rendered frames; lighting, rolling shutter and real sensor noise",
        "  are untested",
        "labels come from the SIZE-PRIOR classifier, not recognition: YOLO has",
        "  no furniture weights until Phase 6 and does not fire on synthetic",
        "  renders, so semantic accuracy is unvalidated",
        "poses were supplied (as ARKit/ARCore captures do). The RGBD odometry",
        "  backend is millimetre-accurate where it converges but diverges on",
        "  this capture's wide baselines - see tests/test_pose_accuracy.py",
        "COLMAP (the monocular path) is not installed here and is unrun"):
    print(f"  * {line}" if not line.startswith("  ") else f"    {line.strip()}")
print("-" * 66)

if failures:
    print(f"\n{len(failures)}/{total} FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"\nPHASE 5 ACCEPTED — {total}/{total} checks"
      + (f" in {elapsed:.0f}s" if elapsed else ""))
