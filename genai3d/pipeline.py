"""Image -> 3D CLI (spec 10B.1).

    genai3d/.venv/bin/python genai3d/pipeline.py \
      --image ./storage/uploads/lamp.jpg \
      --out   ./storage/generated/<job_id> \
      --backend auto --device cpu --timeout 45 --hint "a tall floor lamp"

Exit codes:
  0 — generated with the requested backend
  3 — generation failed or timed out, a PROXY was written (still usable)
  1 — hard failure, nothing written

Writes object.glb, object.json, thumb.png, metrics.json into --out.
Progress goes to stdout as one JSON object per line so the Imagine Manager can
stream imagine.progress without parsing prose.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import trimesh  # noqa: E402
from PIL import Image  # noqa: E402

from steps.g01_prepare import prepare  # noqa: E402
from steps.g02_understand import understand  # noqa: E402
from steps.g06_scale import scale_to_metric  # noqa: E402
from steps.g07_export import export  # noqa: E402
from steps.g08_proxy import build_proxy  # noqa: E402
from utils.safety import SafetyError, check_upload  # noqa: E402

STAGES = {
    "prepare": 0.10, "understand": 0.20, "generate": 0.55,
    "cleanup": 0.70, "texture": 0.80, "scale": 0.90, "export": 1.00,
}


def emit(stage: str, **extra) -> None:
    """One JSON line per progress tick. stdout is a protocol here, not a log."""
    print(json.dumps({"stage": stage, "progress": STAGES.get(stage, 0.0), **extra}),
          flush=True)


def run(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    used_proxy = False
    backend_name = "proxy"

    # ── G01 prepare ──
    emit("prepare")
    raw = Path(args.image).read_bytes()
    try:
        check_upload(raw, max_mb=args.max_upload_mb)
    except SafetyError as e:
        print(json.dumps({"stage": "failed", "error": str(e)}), flush=True)
        return 1
    rgba, prep_meta = prepare(raw)

    # ── G02 understand ──
    emit("understand")
    info = understand(rgba, hint=args.hint, estimator=args.size_estimator)
    emit("understand", label=info["label"], est_dims_m=info["est_dims_m"],
         scale_confidence=info["scale_confidence"])

    # ── G03 generate ──
    emit("generate", backend=args.backend)
    mesh = None
    if args.backend != "proxy":
        try:
            from backends.factory import get_backend

            b = get_backend(args.backend, device=args.device)
            if b is not None:
                mesh = b.generate(rgba, timeout_s=args.timeout)
                backend_name = b.name
        except Exception as e:  # noqa: BLE001
            emit("generate", note=f"backend failed: {type(e).__name__}: {e}")

    if mesh is None:
        mesh, kind = build_proxy(rgba, info["est_dims_m"], info["placement"])
        used_proxy = True
        backend_name = "proxy"
        emit("generate", note=f"proxy fallback ({kind})")

    # ── G04/G05 cleanup + texture (no-ops for the proxy: already clean) ──
    emit("cleanup")
    if not used_proxy:
        from steps.g04_cleanup import cleanup

        mesh = cleanup(mesh, max_tris=args.max_tris)
    emit("texture")

    # ── G06 scale — one path for every backend, so the tests cover all of them ──
    emit("scale")
    sr = scale_to_metric(mesh, info["est_dims_m"], floor_y=0.0)

    # ── G07 export ──
    emit("export")
    paths = export(out, mesh, rgba, info, sr, backend_name, used_proxy,
                   gen_ms=round((time.perf_counter() - t0) * 1000),
                   prep_meta=prep_meta)

    emit("export", **{k: str(v) for k, v in paths.items()})
    return 3 if used_proxy and args.backend not in ("proxy",) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="RoomMind image -> 3D")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "triposr", "trellis", "proxy"])
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--hint", default="")
    ap.add_argument("--size-estimator", default="prior_table",
                    choices=["vlm", "prior_table", "manual"])
    ap.add_argument("--max-tris", type=int, default=40000)
    ap.add_argument("--max-upload-mb", type=int, default=8)
    args = ap.parse_args()

    try:
        return run(args)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"stage": "failed", "error": f"{type(e).__name__}: {e}"}),
              flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
