# RoomMind

### Turn any room into an intelligent 3D world.

Scan a real room with a phone or webcam, and RoomMind reconstructs it as a textured 3D digital
twin with a **semantic scene graph**. **ARIA**, a humanoid AI robot, lives inside that world: she
knows where everything is, answers questions grounded in the actual room, turns her head to look
at what she's talking about, and physically drives over and points at it.

Hand her an image and she'll build it in 3D, size it correctly, and place it in your room —
and from that moment she can navigate to it and point at it like anything she scanned.

Full build manual: **`ROOMMIND_BUILD_SPEC.md`** — start at §20 Phase 0, one phase per session.

---

## Status

| Phase | Name | State |
|---|---|---|
| **P0** | Foundation & frozen contracts | ✅ done *(except DB — needs `scripts/setup_db.sql`)* |
| **P1** | Orchestration core + ARIA simulator | ✅ **done — 18/18 acceptance checks** |
| **P2** | Presentation: live 3D app + rigged twin | ✅ **done — 21/21 acceptance checks** |
| **P3** | AI Services: companion + embodied grounding | ✅ **done — 19/19 acceptance checks** |
| **P3b** | Imagine: image → 3D | ✅ **done — 25/25 acceptance checks** |
| **P4** | Cinematic layer (GSAP) | ✅ **done — 31/31 static + bundle checks** *(4 runtime criteria need a browser — see below)* |
| **P5** | Twin Generator: reconstruction | ✅ **done — 30/30 acceptance checks** *(validated on rendered capture; see caveats)* |
| P6 | Detection & segmentation training | ⬜ not started |
| P7 | Execution: ARIA on the UNO Q | ⬜ not started |
| P8 | Deployment Manager + on-device inference | ⬜ not started |
| P9 | RL Manager *(optional)* | ⬜ not started |
| P10 | Gestures, modes, safety, polish | ⬜ not started |

**194 unit tests (112 backend + 46 genai3d + 36 reconstruction) + 144 acceptance
checks, all green.**

> **P5 caveat, stated plainly:** no real phone footage was available here, so the
> reconstruction is validated end-to-end on a **rendered** room whose every
> dimension is known exactly — a stricter geometric test than the spec's
> tape-measured ±15% (5 of 6 recovered objects land within 3% on every axis),
> but it proves nothing about real sensor noise, lighting or rolling shutter.
> Three further gaps: labels come from a **size-prior classifier**, not
> recognition (YOLO has no furniture weights until P6); camera **poses were
> supplied**, as ARKit/ARCore captures provide them, because the RGBD-odometry
> backend diverges on this fixture's wide baselines; and **COLMAP** — the
> monocular path — is not installed here. `make accept5` prints all four as
> CAVEATS rather than counting them as passes.

> **P4 caveat, stated plainly:** four of the spec's P4 criteria — ≥ 55 fps, ≤ 25
> draw calls, no white flash across the hand-off, and the < 900 ms hand-off
> timing — need a browser painting real frames. No browser was available in this
> environment, so they are **unverified, not passed**. `make accept4` prints them
> as `TODO` rather than silently counting them. Everything measurable without a
> GPU (code splitting, transfer budgets, ScrollTrigger count, single-Canvas
> wiring, reduced-motion coverage, attribution) is enforced.

---

## Quick start (Windows)

```powershell
# 0. Python 3.11 is REQUIRED (3.12 has no Open3D wheels - spec 2.1).
#    This machine has several; always call it explicitly:
py -3.11 --version

# 1. Contracts + generated TypeScript types
py -3.11 contracts\generate_types.py
py -3.11 scripts\check_contracts.py        # the contract gate - must be green

# 2. Backend venv
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt

# 3. Imagine venv (image -> 3D). Proxy path only: no torch, no downloads.
py -3.11 -m venv genai3d\.venv
genai3d\.venv\Scripts\python -m pip install pillow numpy trimesh pygltflib pytest

# 3b. Reconstruction venv (capture -> 3D twin). Its OWN venv on purpose: Open3D
#     and torch must never be importable from the API process. ~1.5 GB.
py -3.11 -m venv reconstruction\.venv
reconstruction\.venv\Scripts\python -m pip install opencv-python-headless open3d ^
    numpy scipy trimesh pygltflib pillow pytest
reconstruction\.venv\Scripts\python -m pip install ultralytics ^
    --extra-index-url https://download.pytorch.org/whl/cpu

# 4. MQTT broker. Docker isn't installed and there's no admin shell here, so we
#    use amqtt - a pip-installable stand-in for Mosquitto. Same MQTT 3.1.1, same
#    topic contract. Swap to the docker-compose Mosquitto for the demo.
py -3.11 -m venv .broker-venv
.broker-venv\Scripts\python -m pip install amqtt
.broker-venv\Scripts\amqtt.exe -c infra\amqtt\broker.yaml       # terminal 1

# 5. Backend + simulator
copy .env.example .env
cd backend; .venv\Scripts\uvicorn.exe main:app --port 8000      # terminal 2
backend\.venv\Scripts\python.exe firmware\sim\robot_sim.py      # terminal 3

# 6. Frontend
cd frontend; npm install; npm run dev                           # terminal 4
#    -> http://localhost:5173   (Vite proxies /api to :8000, so no CORS in dev)

# 7. Verify the whole loop
backend\.venv\Scripts\python.exe scripts\accept_phase1.py    # 18 checks
backend\.venv\Scripts\python.exe scripts\accept_phase2.py    # 21 checks (needs the frontend)
backend\.venv\Scripts\python.exe scripts\accept_phase3.py    # 19 checks
backend\.venv\Scripts\python.exe scripts\accept_phase3b.py   # 25 checks

# 8. Database (OPTIONAL — the scene graph, planner and companion all run off
#    the fixture). Uses your existing local PostgreSQL 16. Prompts for the password.
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -p 5432 -f scripts\setup_db.sql
cd backend; .venv\Scripts\alembic.exe upgrade head; cd ..
py -3.11 scripts\seed_demo_room.py
```

### Try it

```powershell
# Ask ARIA about the room — she looks at what she cites
curl -X POST localhost:8000/api/v1/chat -H "Content-Type: application/json" ^
     -d "{\"message\":\"how many chairs are there?\"}"

# Ask where something is — she turns her head AND points
curl -X POST localhost:8000/api/v1/chat -H "Content-Type: application/json" ^
     -d "{\"message\":\"where is the lamp?\"}"

# Imagine: turn a photo into a real object in the room
curl -F image=@genai3d/tests/fixtures/chair.png -F room_id=demo_room ^
     -F "prompt=a wooden chair" localhost:8000/api/v1/imagine

# Emergency stop - reaches the robot in ~2 ms
curl -X POST localhost:8000/api/v1/estop
curl -X POST localhost:8000/api/v1/estop/clear
```

### Rebuild a room from a capture (P5)

```powershell
# Render the synthetic test room (RGB + depth + intrinsics, plus ground truth
# that only the tests read). A real phone video works the same way.
make synth

# Reconstruct it. ScanProgress in the browser renders the stages live.
curl -F scan_dir=./storage/scans/synth_demo -F room_id=demo_room ^
     -F detector=geometric -F pose_backend=known localhost:8000/api/v1/scan

# Or run the pipeline directly, outside the API:
make recon
```

The pipeline runs in its own venv and talks to the API over line-delimited JSON
on stdout — the same subprocess boundary Imagine uses, so Open3D and torch stay
out of the web process. It emits `room.glb`, `room.json` (schema-validated),
`navmesh.npy` and `preview.png` into `storage/meshes/<room_id>/`.

Or just open <http://localhost:5173> and **drag an image onto the 3D world**.

### The landing (P4)

<http://localhost:5173> opens the cinematic landing; scrolling S0 → S5 flies the
camera into the dashboard. Two things are worth knowing before demoing it:

| | |
|---|---|
| **Skip Intro / `Esc`** | Jumps straight to `/app` from any beat. Always visible — never make an audience wait for a scroll story. |
| **`?nomotion=1`** | Forces the reduced-motion path (no scrub, no camera flight, all copy readable). Same code path as `prefers-reduced-motion: reduce`. |
| **`/app`** | Loads the dashboard standalone, with the whole GSAP chunk code-split out of it. |

The `<Canvas>` is mounted **once**, in `App.tsx`, above the router, and never
unmounts — that is what makes the hand-off seamless. The landing also showcases
the *real* room rather than a separate diorama, so the last beat's camera pose is
literally the dashboard's (`BEATS[5]` is spread from `APP_CAMERA`) and nothing can
drift. Attribution for the visual technique is in `frontend/public/CREDITS.md`.

## Architecture

Four layers, downward calls only. Results travel back up as events, never as blocking
return values across a layer boundary. See spec §1.4.

```
Presentation    Web dashboard, GSAP cinematic landing, REST + WebSocket API
      |
Orchestration   Capture / Twin Generator / Imagine / RL / Deployment / Robot managers
      |
AI Services     Detection, Segmentation, Depth, Generative 3D, Speech, Intent, Reasoning
      |
Execution       React Three Fiber, QAIRT / ONNX / TFLite, Arduino UNO Q
```

## The frozen contracts

`contracts/` is the single source of truth. Both sides of every boundary must match it
byte-for-byte. After ANY change there, run:

```powershell
py -3.11 contracts\generate_types.py
py -3.11 scripts\check_contracts.py
```

- `scene_graph.schema.json` — the room: objects, ids, poses, sizes
- `command.schema.json` — everything ARIA can be told to do
- `telemetry.schema.json` — pose + **joints** + emotion coming back at 10 Hz
- `mqtt_topics.md` — the backend <-> robot transport map

## Notable engineering decisions

Each of these was a measurement, not a preference — the reasoning lives in the code:

| Decision | Why | Where |
|---|---|---|
| Lexical retrieval, not Chroma, by default | Chroma downloaded 79 MB and blocked startup 37 s to rank 9 objects. Startup went 37 s -> 2.8 s. | `rag_service._pick_backend` |
| Proxy path built and shipped first | A correctly-sized stand-in the robot can navigate to beats a spinner in front of judges. | `g08_proxy.py` |
| `+yaw`, not `-yaw`, in world->body | This project measures yaw from +Z *toward* +X — a left-handed rotation. Using `-yaw` makes ARIA point at empty space whenever her base turns. | `kinematics.world_to_body` |
| E-stop publishes before any bookkeeping | 2 ms to the wire; the WebSocket fan-out is observability, not safety. | `robot_service.estop` |
| Grounding enforced in three places | The prompt asks, the tool boundary rejects, and post-generation validation strips. A rule only requested is not a rule. | `llm_service` |
