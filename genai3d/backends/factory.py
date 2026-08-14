"""Backend selection (spec 10B.3).

Probes what is actually installed and usable, picks the best, and LOGS WHY.
`pipeline.py` calls only this — it never imports a backend module directly, so
adding a backend never touches the pipeline.

Returns None when nothing neural is available, which is the signal for the
pipeline to build a proxy. That is a normal outcome, not an error: the proxy
path is the shipped default until a GPU justifies otherwise.
"""
from __future__ import annotations

import json
import sys


def _log(msg: str, **extra) -> None:
    print(json.dumps({"stage": "backend", "note": msg, **extra}), flush=True)


def _vram_gb() -> float:
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:  # noqa: BLE001
        return 0.0


def get_backend(requested: str = "auto", device: str = "cpu"):
    """Return a loaded Image3DBackend, or None to signal 'use the proxy'."""
    if requested == "proxy":
        _log("proxy requested explicitly")
        return None

    vram = _vram_gb()

    order: list[str]
    if requested == "auto":
        # TRELLIS needs ~16 GB; TripoSR runs on ~6 GB or slowly on CPU.
        order = (["trellis", "triposr"] if vram >= 16 else ["triposr"])
        if vram == 0.0:
            _log("no CUDA device detected", vram_gb=0)
    else:
        order = [requested]

    for name in order:
        try:
            if name == "triposr":
                from backends.triposr import TripoSRBackend as B
            elif name == "trellis":
                from backends.trellis import TrellisBackend as B
            else:
                _log(f"unknown backend '{name}'")
                continue

            b = B(device=device)
            if not b.available():
                _log(f"{name} not available (weights missing or too little VRAM)",
                     vram_gb=round(vram, 1))
                continue
            b.load()
            _log(f"using {name}", vram_gb=round(vram, 1), device=device)
            return b
        except ImportError as e:
            _log(f"{name} not installed ({e.name})")
        except Exception as e:  # noqa: BLE001
            _log(f"{name} failed to load: {type(e).__name__}: {e}")

    _log("no neural backend available -> proxy", vram_gb=round(vram, 1))
    return None


__all__ = ["get_backend"]
sys.modules.setdefault("backends.factory", sys.modules[__name__])
