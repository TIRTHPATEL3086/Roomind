.PHONY: up down broker api web seed migrate rev test types fmt sim imagine flash check accept \
        accept2 accept3 accept3b accept4 accept5 accept6 test-gen test-recon test-pose \
        synth recon synth-multi demo-multi

# On Windows use:  py -3.11   (3.12 breaks Open3D wheels - spec 2.1)
PY   ?= py -3.11
VENV ?= backend/.venv/Scripts/python.exe

up:        ; docker compose up -d postgres redis mosquitto chroma
down:      ; docker compose down

# Dev MQTT broker - a pip-installable stand-in for Mosquitto (no admin needed).
# Swap to the docker-compose Mosquitto for the demo; no app code changes.
broker:    ; .broker-venv/Scripts/amqtt.exe -c infra/amqtt/broker.yaml

# Full stack acceptance: needs `make broker`, `make api` and `make sim` running.
accept:    ; $(VENV) scripts/accept_phase1.py
accept2:   ; $(VENV) scripts/accept_phase2.py     # also needs `make web`
accept3:   ; $(VENV) scripts/accept_phase3.py
accept3b:  ; $(VENV) scripts/accept_phase3b.py
# P4 needs no running services - it builds the frontend and inspects the output.
accept4:   ; $(VENV) scripts/accept_phase4.py
# P5 runs the reconstruction itself; add --with-api once `make api` is up.
accept5:   ; $(VENV) scripts/accept_phase5.py
accept6:   ; $(VENV) scripts/accept_phase6.py
test-recon: ; cd reconstruction && .venv/Scripts/python.exe -m pytest -q -m "not slow"
test-pose: ; cd reconstruction && .venv/Scripts/python.exe -m pytest -q -m slow -s

# Render the synthetic room fixture that P5's acceptance measures against.
# It emits RGB + depth + intrinsics (what a LiDAR phone gives you) plus a
# ground_truth.json that ONLY the tests read.
synth:     ; cd reconstruction && .venv/Scripts/python.exe synth/make_room.py \
             --out ../storage/scans/synth_demo --frames 40 --write-poses
# Rebuild demo_room from that capture. --input may also be a phone .mp4.
recon:     ; cd reconstruction && .venv/Scripts/python.exe pipeline.py \
             --input ../storage/scans/synth_demo --out ../storage/meshes/demo_room \
             --room-id demo_room --intrinsics ../storage/scans/synth_demo/intrinsics.json \
             --pose-backend known --detector geometric

# The many-instances room: 3 chairs of different colours, 2 tables, 2 TVs, a
# bed, a sofa and a lamp. `demo-multi` renders it, reconstructs it with the
# real pipeline and refreshes contracts/demo_room_multi.json from the output -
# that fixture is pipeline OUTPUT and must never be hand-edited.
synth-multi: ; cd reconstruction && .venv/Scripts/python.exe synth/make_room.py \
             --out ../storage/scans/multi_demo --room multi --frames 48 --write-poses
demo-multi: synth-multi
	cd reconstruction && .venv/Scripts/python.exe pipeline.py \
	  --input ../storage/scans/multi_demo --out ../storage/meshes/multi_demo \
	  --room-id multi_demo --name "Multi-Instance Demo Room" \
	  --intrinsics ../storage/scans/multi_demo/intrinsics.json \
	  --pose-backend known --max-frames 48
	$(VENV) scripts/publish_demo_multi.py

test-gen:  ; cd genai3d && .venv/Scripts/python.exe -m pytest -q
sniff:     ; $(VENV) scripts/mqtt_sniff.py 3
api:       ; cd backend && .venv/Scripts/uvicorn.exe main:app --reload --port 8000
web:       ; cd frontend && npm run dev
sim:       ; $(VENV) firmware/sim/robot_sim.py --robot aria --broker localhost
imagine:   ; genai3d/.venv/bin/python genai3d/pipeline.py --image $(img) --out ./storage/generated
seed:      ; $(PY) scripts/seed_demo_room.py
migrate:   ; cd backend && alembic upgrade head
rev:       ; cd backend && alembic revision --autogenerate -m "$(m)"
types:     ; $(PY) contracts/generate_types.py
test:      ; cd backend && pytest -q
fmt:       ; ruff format backend reconstruction ml genai3d firmware/mpu
flash:     ; bash firmware/tools/flash.sh
check:     ; $(PY) scripts/check_contracts.py

