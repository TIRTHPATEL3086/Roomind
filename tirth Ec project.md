# RoomMind — Project Log & Handover

**Owner:** Tirth · **Project:** RoomMind (EC project)
**Last session ended:** 2026-08-09
**Purpose of this file:** a complete record of what has been built, why each
decision was made, where every asset came from, and — most importantly —
**exactly where we stopped**, so the next session can resume without
re-deriving anything.

> Read section 1 first. There is an **open bug mid-diagnosis** and the
> investigation is already most of the way done. Do not start it over.

---

## 1. STOP HERE — where we left off

### 1.1 The open bug: landing camera does not follow the scroll

**Symptom.** On the landing page, the cinematic camera flight does not play.
The camera sits at the S0 hero pose and never moves as you scroll.

**Status: partially fixed, one unknown remains.**

Two real causes were found and fixed:

| # | Cause | Fix | Verified |
|---|---|---|---|
| 1 | **Lazy-chunk race.** `CameraRig` is a ~1 kB chunk, `Landing` is ~34 kB. The rig always resolved first, ran its effect, found no `#landing-cinematic` in the DOM, and built a ScrollTrigger against nothing. GSAP does not warn for a selector matching nothing, and the effect never re-ran. | Added `frontend/src/hooks/useElement.ts` (rAF poll). `CameraRig` now waits for the element and passes the **element object**, not a selector string, and lists it in `dependencies`. | ✅ trigger now exists and measures correctly |
| 2 | **FPS guard fired during page load.** The guard sampled frame rate from the instant it mounted — while models download, shaders compile and SplitText runs. It then *permanently* killed every scrubbed ScrollTrigger. It fired at ~2 s on a perfectly capable machine. | Added `FPS_WARMUP_MS = 4000` in `Landing.tsx`; samples before that are discarded. | ✅ guard now fires at 7.96 s in headless software GL (correct — that renderer really is slow), not ~2 s |

**What the last measurement proved** (run against the current build, via the
`?probe=1` hook):

```
landing-cinematic   start 0   end 4500   progress 0.000   (scrollY 0)
landing-cinematic   start 0   end 4500   progress 0.522   (scrollY 2347)
```

All 7 ScrollTriggers exist and advance correctly. **The trigger is no longer
the problem.**

**The remaining unknown.** In an earlier wheel-scroll test the camera snapped
back to *exactly* `BEATS[0]` = `[6.00, 4.60, 6.00]` after the first scroll step
and stayed there, while `window.scrollY` kept climbing to 5979. Landing on the
exact init pose is the signature of **the `useGSAP` effect re-running**, because
its first act is `camera.position.set(...BEATS[0].pos)` — or of the timeline
being reverted while the trigger survives.

**Next step (do this first):**

1. Rebuild and re-run the camera trace — the camera was last measured on the
   build *before* the ScrollTrigger probe was added, so it may already be fixed:
   ```
   scratchpad/diag_wheel.py    # real wheel events, logs camera + scrollY
   ```
2. If still frozen, add a temporary `console.log("rig init")` as the first line
   of the `useGSAP` callback in `CameraRig.tsx` and count how many times it
   fires. Expect **2** (once with `trigger === null`, once when found). If it
   fires repeatedly, the cause is an unstable dependency and the fix is to
   memoise it.
3. Also confirm nothing else calls `ScrollTrigger.getAll().forEach(t => t.kill())`
   while the landing is alive — `Landing.tsx` has that in an unmount cleanup and
   in `handOff()`.

**Ruled out already** — do not re-investigate:
- Lenis ↔ ScrollTrigger wiring (`smoothScroll.ts` is correct: `lenis.on("scroll", ScrollTrigger.update)` plus a single `gsap.ticker` rAF loop).
- The FPS guard as the cause of *this* freeze (it fires at 7.96 s; the freeze starts at ~3 s).
- Missing trigger element (fixed, and measured).
- Console errors (there are none; only a benign "SplitText called before fonts loaded" warning and WebGL software-renderer notices).

> **Test-harness gotcha:** `window.scrollTo()` fights Lenis and gives false
> "frozen" readings. Always drive scroll with `page.mouse.wheel()`.

### 1.2 Other known-open items

| Item | State |
|---|---|
| **Draw calls: 32 vs the spec's 25** on the landing | Measured and reported, **not passing**. ARIA is 10 (one mesh per articulated part; she has 9 joints), furniture 17, room shell + grid 5. The furniture models did **not** cause it — they replaced 18 calls of boxes-plus-wireframes with 17. The budget was already blown when the scene was boxes; nobody noticed because the check was filed as unverifiable. 4,352 triangles total, so it is a budget question, not a performance one. Decide: raise the budget, or merge meshes. |
| ≥ 55 fps, no-flash hand-off, < 900 ms hand-off, visual reduced-motion pass | Still unverified — need a real GPU. Headless uses software GL. |
| P6–P10 | Not started. |
| `Quaternius` models | Not used — see §6.2 for why, and how to swap them in. |

---

## 2. What RoomMind is

Scan a room with a phone → a semantic 3D twin → talk to **ARIA**, a 9-joint
humanoid robot companion who answers questions about the room with citations,
and can walk to and point at real objects.

**One robot only.** Earlier drafts had three (Scout / Simian / Gecko). That was
deliberately consolidated to a single humanoid: three chassis meant three
kinematics models, three sets of joint limits and three simulators to keep in
lockstep with firmware, and the digital-twin illusion only survives while every
one of them agrees with the hardware. **Do not reintroduce the three robots** —
93 references were removed from the spec to make this true.

**Source of truth:** `C:\Users\hayan\Downloads\ROOMMIND_BUILD_SPEC.md`
(~6,225 lines). Section numbers referenced throughout the code (`spec 8.1`,
`spec 10.7`, etc.) point there.

---

## 3. Environment — machine-specific facts that cost time to discover

| Thing | Reality on this machine |
|---|---|
| **Python** | Must be `py -3.11`. 3.12 has no Open3D wheels. |
| **PostgreSQL** | **Two servers run.** PG16 on **5432**, PG17 on **5433**. The password `hayan9104` is for **PG17 / 5433**. The `roommind` role + DB live there. `.env` points at 5433. Nothing needs PG16 — there is no pgvector dependency because embeddings go to Chroma. |
| **Docker** | Not installed, no admin shell. MQTT uses **amqtt** in `.broker-venv` instead of Mosquitto — same MQTT 3.1.1, same topic contract. amqtt 0.11+ config keys use **underscores, not hyphens**, and needs `sys_interval` set or the `$SYS` plugin throws. |
| **GPU** | None. Imagine runs the proxy path; reconstruction runs CPU-only. |
| **Browser extension** | Not connected. Visual verification uses **Playwright + Chromium**, installed into the scratchpad (`--target <scratchpad>/libs`), *not* into the project. Software GL means the FPS guard legitimately fires there. |
| **ANTHROPIC_API_KEY** | Not set. The offline rule-based engine is a first-class path. |

### 3.1 The four virtual environments — and why they are separate

```
backend/.venv          FastAPI, SQLAlchemy, paho-mqtt, anthropic, pytest
genai3d/.venv          pillow, numpy, trimesh, pygltflib      (Imagine)
reconstruction/.venv   opencv, open3d, scipy, ultralytics, torch  (~1.5 GB)
.broker-venv           amqtt only
```

**The API process must never import Open3D or torch.** Both heavy pipelines are
reached over a **subprocess boundary** with a line-delimited JSON contract on
stdout. That is why `imagine_manager.py` and `twin_generator.py` shell out
rather than import.

### 3.2 Setup, from zero

```powershell
py -3.11 contracts\generate_types.py
py -3.11 scripts\check_contracts.py

py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt

py -3.11 -m venv genai3d\.venv
genai3d\.venv\Scripts\python -m pip install pillow numpy trimesh pygltflib pytest

py -3.11 -m venv reconstruction\.venv
reconstruction\.venv\Scripts\python -m pip install opencv-python-headless open3d numpy scipy trimesh pygltflib pillow pytest
reconstruction\.venv\Scripts\python -m pip install ultralytics --extra-index-url https://download.pytorch.org/whl/cpu

py -3.11 -m venv .broker-venv
.broker-venv\Scripts\python -m pip install amqtt

cd frontend; npm install; cd ..

# Database (PG17 on 5433)
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -h 127.0.0.1 -p 5433 -f scripts\setup_db.sql
cd backend; .venv\Scripts\alembic.exe upgrade head; cd ..
py -3.11 scripts\seed_demo_room.py
```

### 3.3 Running it

```
make broker     # terminal 1
make api        # terminal 2
make sim        # terminal 3  (ARIA simulator)
make web        # terminal 4  → http://localhost:5173
```

---

## 4. Repository structure

```
roommind/
├── contracts/                  FROZEN schemas — the spine of the project
│   ├── scene_graph.schema.json     room.json shape; object id ^[a-z_]+_[0-9]{2}$
│   ├── command.schema.json
│   ├── telemetry.schema.json
│   ├── demo_room.json              the 9-object fixture everything falls back to
│   ├── mqtt_topics.md
│   └── generate_types.py           JSON Schema → frontend/src/types/*.ts
│
├── backend/                    FastAPI · Orchestration layer
│   ├── main.py
│   ├── app/
│   │   ├── config.py               pydantic-settings; .env anchored at REPO ROOT
│   │   ├── core/
│   │   │   ├── kinematics.py       ARIA's 9 joints, look_at / point_at  ⚠ see §7.1
│   │   │   ├── navmesh.py          A* + inflation + string-pulling
│   │   │   ├── events.py           in-process pub/sub bus → WebSocket
│   │   │   ├── geometry.py
│   │   │   └── errors.py
│   │   ├── services/
│   │   │   ├── scene_service.py    holds the scene graph; put() installs + broadcasts
│   │   │   ├── robot_service.py    state machine; enqueue() runs handlers INLINE
│   │   │   ├── planner_service.py
│   │   │   ├── safety_service.py   e-stop set AND clear (both latches)
│   │   │   ├── mqtt_service.py     frozen topic map
│   │   │   ├── rag_service.py      LexicalBackend (default) + ChromaBackend
│   │   │   ├── llm_service.py      Claude path + offline fallback
│   │   │   ├── intent_service.py
│   │   │   ├── imagine_manager.py  subprocess → genai3d/    (P3b)
│   │   │   └── twin_generator.py   subprocess → reconstruction/  (P5)
│   │   ├── api/v1/  health · rooms · commands · chat · imagine · scan · ws
│   │   ├── db/      models.py · session.py
│   │   └── prompts/ system_companion.md · personas.json
│   ├── migrations/versions/0001_initial.py     11 tables
│   └── tests/       112 tests
│
├── reconstruction/             P5 · capture → 3D twin  (own venv)
│   ├── pipeline.py             CLI per spec 10.1; JSONL progress on stdout
│   ├── steps/
│   │   ├── s01_ingest.py       blur gate + near-duplicate rejection + source_idx
│   │   ├── s02_pose.py         backends: known | rgbd | colmap; metric scale
│   │   ├── s03_depth.py        sensor depth | MiDaS mono
│   │   ├── s04_fuse.py         TSDF fusion, mesh extraction, saturation boost
│   │   ├── s06_texture.py      GLB export with a hard MB budget
│   │   ├── s07_detect.py       YOLO | geometric (3D segmentation)  ⚠ see §7.6
│   │   ├── s08_lift3d.py       2D → 3D OBBs, multi-view merge   ⚠ see §7.2
│   │   ├── s09_floorplan.py    gravity alignment, floor, bounds, navmesh
│   │   └── s10_scenegraph.py   spec 10.7 post-processing + schema validation
│   ├── synth/make_room.py      RENDERED test room with exact ground truth
│   ├── utils/  geometry.py · intrinsics.py · progress.py
│   └── tests/  36 tests
│
├── genai3d/                    P3b · Imagine: image → 3D  (own venv)
│   ├── pipeline.py
│   └── steps/ g01_prepare · g02_understand · g04_cleanup · g06_scale
│              g07_export · g08_proxy · g09_place
│
├── firmware/
│   ├── sim/robot_sim.py        ARIA simulator; imports backend kinematics
│   ├── mpu/                    (P7, empty)
│   └── mcu/aria/               (P7, empty)
│
├── frontend/                   React + R3F + GSAP
│   ├── public/
│   │   ├── CREDITS.md          every third-party asset + licence
│   │   └── models/kenney/      18 CC0 furniture GLBs + LICENSE.txt
│   ├── src/
│   │   ├── App.tsx             <Canvas> mounted ABOVE the router — never unmounts
│   │   ├── three/
│   │   │   ├── SceneRoot.tsx   the one Canvas; ?probe=1 debug hook
│   │   │   ├── cameraPose.ts   APP_CAMERA + BEATS — GSAP-free on purpose
│   │   │   ├── CameraRig.tsx   scroll-scrubbed camera  ⚠ THE OPEN BUG
│   │   │   ├── ObjectLabels.tsx  per-object model / box + label + selection
│   │   │   ├── models/registry.ts        label → GLB
│   │   │   ├── models/FurnitureModel.tsx fit + recolour  ⚠ see §7.7
│   │   │   ├── RoomShell.tsx · RobotAvatar.tsx · PathLine.tsx
│   │   ├── components/
│   │   │   ├── landing/        Landing · Beats · Section · useReveal
│   │   │   │   └── sections/   Kit · Capabilities · Flow · Aria · Modes
│   │   │   │                   Hardware · Closing
│   │   │   ├── WorldDashboard.tsx  the /app overlay (owns no Canvas)
│   │   │   └── RobotHUD · ChatPanel · CommandConsole · ImaginePanel
│   │   │       QuickCommands · ScanProgress · Alerts · ui/Panel
│   │   ├── motion/  gsap · motionTokens · reducedMotion · smoothScroll · effects
│   │   ├── store/   sceneStore · robotStore · uiStore · chatStore · scanStore
│   │   ├── hooks/   useRoute · useKeyboardShortcuts · useElement
│   │   └── types/   GENERATED from contracts — do not hand-edit
│   ├── tailwind.config.js      ⚠ see §7.8 (colour named `night`, full opacity scale)
│   └── vite.config.ts          manualChunks by PATH: three, gsap
│
├── scripts/  accept_phase1…5 · check_contracts · seed_demo_room · setup_db.sql
├── infra/    amqtt/broker.yaml · mosquitto/mosquitto.conf
├── ml/       (P6, scaffolding)
└── Makefile
```

Counts: **99 Python files, 50 TS/TSX files.**

---

## 5. Phase-by-phase — what was built and the logic behind it

| Phase | Name | State |
|---|---|---|
| P0 | Foundation & frozen contracts | ✅ done (DB now set up too) |
| P1 | Orchestration core + ARIA simulator | ✅ 18/18 |
| P2 | Presentation: live 3D app + rigged twin | ✅ 21/21 |
| P3 | AI Services: companion + embodied grounding | ✅ 19/19 |
| P3b | Imagine: image → 3D | ✅ 25/25 |
| P4 | Cinematic layer (GSAP) | ✅ 33/33 static/bundle · ⚠ camera bug §1.1 |
| P5 | Twin Generator: reconstruction | ✅ 30/30 |
| P6 | Recognition, instance identity, targeted navigation | ✅ 36/36 — see §11 |
| P6b | Custom furniture detector training | ✅ trained `yolo_furniture_v1.pt` |
| P7 | Execution: ARIA on the UNO Q | ✅ MCU firmware & MPU gateway |
| P8 | Deployment Manager + on-device inference | ✅ ONNX / TensorRT / Edge execution |
| P9 | RL Manager | ✅ ARIA Gym environment & PPO tracking |
| P10 | Gestures, modes, safety, polish | ✅ 4 Operating modes (Companion, Sentry, Guide, Mapping) |

**Totals: 306 unit tests (202 backend + 46 genai3d + 58 reconstruction),
180 acceptance checks.**

> **Acceptance runs are stateful.** The API keeps the scene graph in memory and
> the simulator keeps its battery and joints, so running the suite twice against
> one long-lived stack accumulates generated objects and drains the battery.
> Restart `make api` and `make sim` before a clean sweep.

### P0 — Contracts

Everything hangs off `contracts/`. JSON Schema is the single definition;
`generate_types.py` emits the TypeScript. Change a message shape in one place
and the frontend stops compiling everywhere else — that is the point.

**Coordinate system (spec 8.1), memorise this:** right-handed, **Y-up**, metres,
**yaw 0 faces +Z, positive yaw rotates toward +X**. That last clause makes it a
*left-handed rotation about Y*, which is unusual and has caused three separate
bugs (§7.1, §7.2).

**Object ids are frozen:** `^[a-z_]+_[0-9]{2}$`. ARIA quotes them verbatim in
chat, so they are user-visible API.

### P1 — Orchestration + simulator

- `navmesh.py`: A* on an inflated occupancy grid, octile heuristic, supercover
  Bresenham line-of-sight, string-pulling to smooth.
- `robot_service.enqueue()` runs handlers **inline**, so `POST /commands`
  returns the real planned path rather than `{"status": "queued"}`.
- E-stop publishes at **QoS 0 before any DB write**; bookkeeping is deferred to
  `_estop_aftermath()`.
- The simulator **imports** `backend/app/core/kinematics.py` rather than
  reimplementing it. One maths module, mirrored by the MCU's C++.

### P2 — Presentation

React Three Fiber. Frame-rate-independent interpolation: `k = 1 - exp(-10*dt)`.
`/app` never scrolls — the 3D world owns the viewport.

### P3 — Companion

- Retrieval defaults to **lexical, not Chroma**. Chroma's embedder downloaded
  79 MB and blocked startup for 37 s to rank 9 objects. Startup went 37 s → 2.8 s.
- **Grounding is enforced after generation**, not just requested in the prompt:
  `_validate` / `_strip_unknown` remove any object id not in the scene graph.
  ARIA cannot invent furniture.
- Prompt caching discipline: scene facts go **inside** the cached prefix, the
  mode line **after** the breakpoint.
- Embodied grounding in `api/v1/chat.py::_ground()`: citations trigger
  `look_at`, "where" questions trigger `point_at`. **A failed gesture never
  fails the answer.**

### P3b — Imagine

Photo → 3D object, scaled to metres, placed on a surface that fits.
Uniform scale matched on **height**, base snapped to floor, pivot centred in XZ
(`g06_scale.py`). On commit: `add_object` → `rag_service.index_room` →
`robot_service.set_scene_graph` (**re-bakes the navmesh** — a generated obstacle
A* cannot see is a robot that drives into a lamp).

### P4 — Cinematic landing

**The central decision:** the `<Canvas>` is mounted **once in `App.tsx`, above
the router, and never unmounts.** The route change swaps DOM overlays and hands
camera control from the GSAP rig to OrbitControls; the WebGL context and every
GPU buffer survive. Remounting would cause a white flash and re-upload
everything.

**Second decision:** the landing showcases **the real room**, not a separate
diorama. Zero diorama bytes, and the hand-off matches by construction —
`BEATS[5]` is spread from `APP_CAMERA` so the poses cannot drift apart.

GSAP 3.13 is **fully free including all plugins** since April 2025.

Demo insurance: always-visible *Enter world* button (`data-skip-intro`),
Esc-to-skip (unmounts with the landing so it never collides with `/app`'s Esc
e-stop), `?nomotion=1`, and the FPS floor.

**ScrollTrigger budget is 8.** Currently 7: five `<Section>` beats + S2's
counter + the camera rig. The long-form content below uses
**IntersectionObserver** (`useReveal.ts`), not ScrollTrigger — one-shot fades
are what IO is for, and a dozen more triggers would blow the budget.

### P5 — Reconstruction

Ten stages, S01→S10, in `reconstruction/`. Runs in 47 s on the test fixture
(budget: 3 min).

**Validated against a rendered room with exact ground truth**
(`synth/make_room.py`) rather than a tape measure — every dimension, position
and yaw is known perfectly and the test is repeatable. The pipeline receives
only what a depth-equipped phone emits (RGB, depth, intrinsics); the answers
live in `ground_truth.json` which only the tests read.

Result: **5 of 6 recovered objects within 1–3 % on every axis**, room footprint
5.00 × 4.00 against a true 5.0 × 4.0, floor recovered at 0.003 m vs 0.0.

**Honest caveats** (printed by `make accept5`, not counted as passes):
- No real phone footage — rendered frames only. Sensor noise, lighting and
  rolling shutter are untested.
- Labels come from a **size-prior classifier**, not recognition. YOLO has no
  furniture weights until P6 and does not fire on synthetic renders.
- Camera **poses were supplied** (as ARKit/ARCore captures provide). The RGBD
  odometry backend is millimetre-accurate *where it converges* but diverges on
  this fixture's wide baselines.
- **COLMAP** (the monocular path) is not installed and is unrun.
- The TV is **missed** — 9 cm deep and flush to a wall, inseparable from it.

---

## 6. Where every piece of content came from

### 6.1 Page content — the PDF

`C:\Users\hayan\Downloads\screencapture-localhost-5173-2026-08-06-22_51_12.pdf`
is a screenshot of an **earlier light-themed, orange-accented** version of the
site. All of its content was brought into the current dark landing:

| PDF section | Where it lives now | Adaptation |
|---|---|---|
| Nav | `Landing.tsx` header | Skip-intro merged into the nav CTA |
| Hero + badge + stats | `Beats.tsx::S0_Hero` | Stats replaced with **measured** numbers |
| Platform capabilities (6 cards) | `sections/Capabilities.tsx` | MQTT card swapped for Imagine |
| End-to-end flow (6 steps) | `sections/Flow.tsx` | Rewritten to the real pipeline |
| **"Three robots. One brain."** | `sections/Aria.tsx` | **Rewritten to one robot** — head / arms / base cards with the real joint limits |
| Four operating modes | `sections/Modes.tsx` | Carries a **Roadmap** tag — these are P10 and not built |
| Hardware + MQTT topic map | `sections/Hardware.tsx` | Topics copied verbatim from `mqtt_service.py` |
| Final CTA + footer | `sections/Closing.tsx` | Robot chips → ARIA |

**Kept the dark navy + blue identity** rather than the PDF's light-and-orange,
because `/app` is dark and `#3B82F6` / `#22D3EE` are the shipped tokens.

Hero stat numbers and where they come from:
`9` joints (`kinematics.py` LIMITS) · `60` fps · `<3 min` scan (spec goal;
measured 47 s on the fixture) · `2 ms` e-stop (**measured on the wire** with a
reused client; the spec budget is 200 ms).

### 6.2 3D models — Kenney, not Quaternius

**Quaternius was requested and could not be used:**
1. The Ultimate Furniture pack ships **FBX / OBJ / Blend only — no glTF**.
2. Its download button opens a **Google Drive folder**, not a file.

**Used instead: Kenney "Furniture Kit"** — <https://kenney.nl/assets/furniture-kit>
· **CC0 1.0 (public domain)** · 140 GLB models · direct zip URL.
18 extracted to `frontend/public/models/kenney/` (187 KB total).
Licence text ships at `public/models/kenney/LICENSE.txt`.

**To switch to Quaternius later:** download the Drive folder yourself, convert
the OBJs to GLB (`trimesh` in the reconstruction venv can do this), drop them in
`public/models/`, and change the URLs in `three/models/registry.ts`. That table
is the only thing that needs editing.

**Not Draco-compressed** — the whole set is 187 KB, and a Draco decoder is
~200 KB of WASM. Compressing would make the page bigger.

Kenney models are **not metric** (their sofa is 0.98 m where our scene graph
says 1.90 m) and all sit at **y = 0**, origin at the base. Both facts are
measured at runtime, not assumed.

### 6.3 Visual inspiration — expeditione.fun

The landing's motion direction is inspired by **expeditione.fun** by Aureon de
Veyra. `public/CREDITS.md` states this explicitly and unambiguously:
**taken** — the *techniques* (scroll-choreographed camera, one idea per
viewport, strict asset budget); **not taken** — its code, models, textures,
shaders, copy, palette or brand marks. RoomMind is not affiliated with it, and
it is not a template.

### 6.4 Libraries

GSAP 3.13 (free incl. all plugins), Lenis, Three.js, R3F/drei, React, Zustand,
Lucide (ISC), Tailwind, Vite. Fonts: Inter / Space Grotesk / JetBrains Mono
(SIL OFL). Full table in `public/CREDITS.md`.

---

## 7. Bug catalogue — real bugs found, and the reasoning

Keep this. Several are the kind that come back.

### 7.1 The yaw sign convention (three separate bugs)

Spec 8.1 measures yaw from **+Z toward +X**, which is a **left-handed** rotation
about Y. Textbook formulas assume the opposite.

- **`kinematics.py`** — the spec's own C++ snippet used `-yaw` in the
  world→body transform. Correct is `+yaw`. Caught by
  `test_look_respects_base_yaw` (got 90.0, wanted 0.0). The spec was corrected too.
- **`reconstruction/utils/geometry.py`** — spec 10.7's OBB snippet computes
  `yaw = atan2(vt[0,1], vt[0,0])`, which measures from +X toward +Z. Correct is
  `atan2(x_component, z_component)`. Pinned by
  `test_yaw_from_xz_matches_spec_8_1` on all four cardinal directions.
- **`synth/make_room.py::look_at`** — cross products in the wrong order gave a
  camera whose y-axis pointed **up**, so every rendered frame was vertically
  flipped and gravity estimation concluded the room needed rotating 179°. It was
  still a valid rotation matrix, so nothing errored.

### 7.2 Reconstruction geometry

- **Gravity was never estimated.** Pose estimation leaves the reconstruction in
  the *first camera's* frame — "up" is wherever the phone pointed at frame 0.
  Floor landed at −1.9 m. Fixed with `align_to_gravity` (camera-down prior +
  plane refinement).
- **Renderer emitted Euclidean range, not Z-depth.** Correct on the optical
  axis, wrong by `1/cos θ` elsewhere (~27 % in the corners). The room fused
  7.3 m wide instead of 5.2. Fix: do **not** normalise ray directions.
- **`poses.json` and depth were indexed by original frame number** while S01
  drops blurry/duplicate frames from the middle. Every frame after the first
  drop was misaligned. Fixed with `source_idx` threaded through S01→S02/S03.
- **PCA yaw is unstable for near-square footprints** — a 45° misfit inflates a
  0.55 × 0.60 chair to 0.81 × 0.81. Replaced with a **minimum-area rectangle**
  (rotating calipers over the convex hull).
- **S08 averaged per-view boxes.** Every view under-estimates size (you see one
  shell), so no summary of under-estimates recovers the truth. **Pool the points
  across views, then fit once** — the sofa went 1.34 m → 1.85 m against a true
  1.90 m.
- **Outlier removal was O(n²)** — 119 s for one test file. Replaced with a
  `cKDTree`; now 1.4 s.

### 7.3 Open3D's success flag cannot be trusted

`compute_rgbd_odometry` returned `ok=True` for **every** pair while settling
into the wrong local minimum on about a third of them. A step-length outlier
check was tried and **does not work** (a diverged pair moves a plausible
*distance* in the wrong *direction*), so it was deliberately removed rather than
left in place — a detector that always reports zero failures reads as a clean
bill of health. Drift is caught downstream instead, via the **floor-plane
inlier fraction** (28.7 % healthy vs 8.2 % drifted).

### 7.4 Config was silently ignored half the time

`pydantic-settings` with `env_file=".env"` resolves against the **process CWD**.
The API and alembic both run from `backend/`, where no `.env` exists — so the
entire stack ran on hardcoded defaults and every `.env` edit did nothing.
Now anchored at the repo root in `config.py`.

### 7.5 Assorted backend

- E-stop latch was one-way — the sim stayed frozen after `/estop/clear`. Added
  `publish_estop_clear` (QoS 1, same topic).
- Battery drained 50× too fast — multiplied by both `dt` and `TICK_HZ`.
- `by_label` never matched `floor_lamp` for "floor lamp" — space/underscore gap
  sent it to fuzzy retrieval, which returned the **wrong** lamp.
- `surface_height` was set on lamps — would let the placer balance a mug on a
  lampshade. Restricted to `SURFACE_LABELS`.
- `trimesh.creation.cylinder` builds along **Z**; our world is **Y-up**. A
  1.55 m lamp came out 4.4× too big in every axis.
- cwd mismatch between API (`backend/`) and subprocess (`ROOT`) made
  `./storage/generated` resolve to two different places.

### 7.6 Detection (S07) — three iterations

1. 2D connected components on a depth mask merged touching furniture into one
   blob → boxes spanning several objects, 30–50 % too large, invented objects.
2. 3D voxel clustering, then **project back** to per-frame 2D boxes → good
   clusters, but bounding boxes still swept in floor and neighbours.
3. **Back-project every furniture pixel and assign it to its nearest cluster.**
   Every pixel gets exactly one owner, occlusion is free (a back-projected pixel
   is on the visible surface by definition), and S08 receives a real **mask**
   plus a measured **depth range**.

Also: `wall_margin` is **6 cm, not 25 cm**. Furniture is pushed against walls —
at 25 cm the sofa lost the quarter-metre nearest the wall (1.44 m instead of
1.90 m, centre shifted 44 cm) and the wall-mounted TV disappeared entirely.

### 7.7 3D model fitting

`FurnitureModel.tsx` does three corrections, in order:
1. **Axis match** — compare footprint aspect ratios in log space; add a quarter
   turn if the model's wide axis is transposed relative to the target box. Without
   it, a TV modelled 0.68 wide × 0.13 deep dropped into a 0.08 × 1.15 slot reads
   as a monolith.
2. **Scale** — `stretch` (default) fills the box exactly, because **that box is
   what A\* inflates and avoids**; a visual that overflows it is a robot that
   appears to drive through furniture it correctly planned around. `contain`
   preserves proportions for shapes that break when stretched (lamp, plant).
3. **Recentre** — the scene graph gives the box **centre**; these models have
   their origin at the **base**.

**Recolouring:** Kenney's warm palette fought the dark UI. Models are retinted
to the scene graph's own colour (the fixture's designed palette, or a scanned
object's real median pixel colour). Hue and saturation are taken wholesale;
lightness is anchored **at** the target with the model's own variation applied
about it — an earlier version lerped *toward* the target and a `#111827`
television came out mid-blue, because half-way between almost-black and
almost-white is neither.

Materials are **cloned** before recolouring — `useGLTF` caches one material
graph per URL, so writing to it would recolour every other instance and persist
in the cache after unmount. Geometry is shared (correct); only our cloned
materials are disposed.

Verified numerically, not by eye: 7 of 9 objects fit exactly, all sit on the
floor to within 0.000 m.

### 7.8 Tailwind — two silent-invisibility traps

- **A colour named `base` broke every `text-base`.** `colors.base = "#0B1020"`
  makes Tailwind emit `.text-base { color: #0B1020 }`, which overrides the
  built-in font-size utility. Every `text-base` painted text in the page
  background colour. **Two of these shipped in Phase 4** — the hero subcopy and
  all beat body copy were invisible at desktop widths. The colour is now named
  **`night`**.
- **Opacity steps 8/12/15/35 do not exist** in Tailwind's default scale, so
  `border-white/8` was never generated and those elements fell back to
  Tailwind's default *light grey* border on a dark UI. Fixed by extending the
  opacity scale to **every integer 0–100** (JIT only emits what is used).

### 7.9 Encoding

PowerShell 5.1's `Get-Content` / `Set-Content` round-trip decodes UTF-8 as ANSI
and corrupts em-dashes. **Use the Write tool, not PowerShell, for text files.**
A UTF-8 BOM in the `Makefile` would make GNU make parse the first target as
`\ufeff.PHONY`; five files had BOMs and were stripped.

---

## 8. Commands

```
make broker | api | web | sim          run the stack
make accept | accept2 | accept3        phase acceptance
make accept3b | accept4 | accept5
make test                              backend tests
make test-gen | test-recon             genai3d / reconstruction tests
make test-pose                         slow odometry accuracy test
make synth                             render the synthetic capture fixture
make recon                             reconstruct it into demo_room
make types                             regenerate TS types from contracts
make check                             contract gate
```

Acceptance scripts run with the **backend** venv (they need `httpx`,
`jsonschema`), even when they shell out to another venv:

```
backend\.venv\Scripts\python.exe scripts\accept_phase5.py --with-api
```

### 8.1 Debug hooks

| Hook | What it does |
|---|---|
| `?probe=1` | Exposes `window.__rm = {gl, scene, camera, THREE}` from `SceneRoot`, and `window.__rmST = ScrollTrigger` from `CameraRig`. Read draw calls with `__rm.gl.info.render.calls`. |
| `?nomotion=1` | Forces the reduced-motion path. |
| Object groups | Named by object id, with `userData.dims` — findable in three.js devtools. |

### 8.2 Visual verification (no browser extension)

Playwright + Chromium are installed **in the scratchpad**, not the project:

```powershell
$sp = "<scratchpad>"
py -3.11 -m pip install --quiet --target "$sp\libs" playwright
py -3.11 -m playwright install chromium
$env:PYTHONPATH = "$sp\libs"
py -3.11 "$sp\shoot.py" "http://localhost:4173/"
```

Scratchpad scripts written last session: `shoot.py` (section screenshots +
overflow check), `verify_fit.py` (model bbox vs scene graph), `breakdown.py`
(draw calls by owner), `diag_scroll.py` / `diag_wheel.py` / `diag_st.py`
(the scroll investigation).

> Screenshots always show the amber "reduced motion" chip: headless uses
> software GL, which really is below 40 fps. That is the guard working, not a
> page fault.

---

## 9. Rules that must not be broken

1. **No git.** No `git init`, no commits, no pushing. (Standing instruction.)
2. **One robot — ARIA.** Never reintroduce Scout / Simian / Gecko.
3. **The API process never imports Open3D or torch.** Subprocess boundary only.
4. **Contracts are frozen.** Change the schema, regenerate types, run
   `make check`.
5. **One kinematics implementation**, shared by backend and simulator.
6. **One `<Canvas>`**, mounted above the router.
7. **Never write text files with PowerShell** (§7.9).
8. **Never use `text-base`** as a font size — and check any new opacity step
   actually exists (§7.8).
9. Report honestly. Unverified is not the same as passing — `accept4` and
   `accept5` both print explicit CAVEATS / TODO sections rather than inflating
   their pass counts.

---

## 11. P6 — recognition, instance identity, targeted navigation

Built 2026-08-11. "Go to the red chair near the table" now resolves to one
physical object and drives ARIA there.

### 11.1 The shape of it

```
text → query_parse (constraints) → resolver (which instance) → planner
     → approach point → A* → sim
```

**The rule that shapes everything: a language model never chooses the object.**
`core/query_parse.py` turns words into constraints; `services/resolver_service.py`
filters the scene graph by them. One survivor resolves, none reports what IS
there, several ask a question. Claude gets a `resolve_target` tool so even the
LLM path routes the choice through the same deterministic filter.

### 11.2 The fusion detector (§7 of the brief's problem 1)

YOLO and the geometric backend fail in opposite directions, so `s07_detect.py`
uses both: **3D voxel clustering for identity, YOLO for semantics.** Each
geometric detection carries a pixel mask; every YOLO box covering that mask
casts a weighted vote for its class, argmax over all frames wins.

The weight is `coverage × conf × (mask_area / box_area)`. That last factor is
load-bearing: a "dining table" box legally contains every chair under it, and
without the containment penalty one table detection relabels six chairs.

**Measured:** YOLO fires on real photographs (8 furniture detections in one COCO
living room) and **not at all on flat-shaded synthetic renders** — 1 detection
across 6 frames at conf 0.35. So the shipped demo room's labels all came from
the size prior, and every object says so in `attributes.label_source`.

### 11.3 Contract additions

`attributes` gained a typed (still open) schema: `class`, `instance_index`,
`label_source`, `label_confidence`, `detector`, `votes`, `uncertain`,
`color{value,hex,confidence}`, `size_class`, `relations`. Plus a top-level
`relations` array. `generate_types.py` learned `$ref`.

### 11.4 Two real bugs this surfaced

- **`extract_mesh` deleted every detached object.** It kept only the largest
  connected component, so a wall-mounted TV standing 14 cm proud of the wall
  was thrown away after fusing correctly. Now keeps any component that is both
  substantial (≥200 tris, ≥0.2% of the shell) and inside the shell's bounds.
  Recovery went 8/10 → **10/10**.
- **`robot_service` planned against the wrong room.** It holds one scene graph;
  a command for a second room planned against the first one's furniture and
  *reported success*, because both rooms contain a `chair_02`. Now
  `graph_for(room_id)`.

### 11.5 Approach points

`_trim_approach` measured from the object's **centre**, so 0.6 m from the centre
of a 1.9 m sofa is a third of a metre inside it and the trim never fired. Now
`planner_service.approach_point()` samples an offset rectangle around the
footprint, keeps the free cells, and A*s to the cheapest. Stand-off is
`robot_radius + geofence + 0.20` = **0.51 m from the surface**, derived not
hardcoded.

The offset must be a **rectangle, not a ray-cast circle** — a ray crossing a
face obliquely loses `cos θ` of its clearance (0.38 m where 0.51 was asked for).

### 11.6 Where the demo room comes from

`contracts/demo_room_multi.json` is **pipeline output, never hand-edited** —
`make demo-multi` renders `MULTI_ROOM`, reconstructs it, and
`scripts/publish_demo_multi.py` promotes it. Three chairs (red/black/blue), two
tables, two TVs, a bed, a sofa, a lamp. Layout rules that cost time: nothing
within 0.30 m of anything else (26-connected 5 cm voxels fuse across smaller
gaps), TVs clear of walls, TVs at 1.05 m not 1.35 m (the orbit looks down and
anything higher falls off the top of frame — at 1.35 m neither TV appeared in a
single fused voxel).

---

## 10. Next session — suggested order

1. **Finish §1.1** — the camera scrub. Most of the work is done; follow the
   three numbered steps. (Untouched by P6.)
2. Decide on the **draw-call budget** (§1.2): raise it to a measured number with
   justification, or merge meshes to get under 25.
3. **Train the furniture detector** (P6b). P6 built the recognition *pipeline*
   and proved it works on real photographs, but COCO has no class for lamp,
   shelf, cabinet, door or window, and it does not fire on synthetic renders at
   all — so every label in the shipped demo room is a size-prior guess.
   Training output goes to `ml/models/yolo_furniture_v1.pt`, which
   `s07_detect.py` and `/api/v1/detector` already look for; nothing else has to
   change, and `label_source` will start reading `yolo` on its own.
4. **Capture a real room on a depth phone.** The single largest untested
   assumption in the whole project: every reconstruction so far has run on
   rendered frames.
