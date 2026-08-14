"""G07 — write object.glb, object.json, thumb.png, metrics.json (spec 10B.2)."""
from __future__ import annotations

import json
from pathlib import Path

import trimesh
from PIL import Image

THUMB_PX = 256

# Labels that actually afford putting something on top. `surface_height` drives
# the placement solver, so marking a lamp or a plant as a surface would let the
# next generated object be placed balancing on the lampshade.
SURFACE_LABELS = {
    "table", "desk", "shelf", "bookshelf", "cabinet", "counter", "sideboard",
    "dresser", "stool", "box", "crate", "bench", "nightstand", "coffee_table",
    "side_table", "workbench",
}


def _surface_height(label: str, height: float, placement: str) -> float | None:
    if placement != "floor" or height <= 0.15:
        return None
    parts = set(label.split("_")) | {label}
    return round(height, 4) if parts & SURFACE_LABELS else None


def export(out: Path, mesh: trimesh.Trimesh, image: Image.Image, info: dict,
           scale_result, backend: str, is_proxy: bool, gen_ms: int,
           prep_meta: dict) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)

    glb = out / "object.glb"
    mesh.export(glb)

    thumb = out / "thumb.png"
    t = image.copy()
    t.thumbnail((THUMB_PX, THUMB_PX), Image.Resampling.LANCZOS)
    t.save(thumb)

    w, h, d = scale_result.final_dims

    # object.json is a single OBJECT FRAGMENT valid against the object
    # sub-schema of spec 8.2. It carries no id: the Imagine Manager allocates
    # that from the live scene graph, so ids stay unique and follow the frozen
    # {label}_{NN} rule. This step never writes to the DB (layer discipline).
    obj = {
        "label": info["label"],
        "dimensions": [round(w, 4), round(h, 4), round(d, 4)],
        "rotation_y": 0.0,
        "color": "#A78BFA",
        "confidence": round(float(info["scale_confidence"]), 3),
        "is_obstacle": bool(info["is_obstacle"]),
        "surface_height": _surface_height(info["label"], h, info["placement"]),
        "source": "generated",
        "scale_confidence": round(float(info["scale_confidence"]), 3),
        "attributes": {
            "placement": info["placement"],
            "category": info.get("category", "object"),
            "proxy": is_proxy,
            "backend": backend,
            "primitive": mesh.metadata.get("primitive"),
        },
    }
    (out / "object.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")

    metrics = {
        "backend": backend,
        "is_proxy": is_proxy,
        "gen_ms": gen_ms,
        "triangles": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "glb_bytes": glb.stat().st_size,
        "scale_factor": round(scale_result.scale, 6),
        "dims_clamped": scale_result.clamped,
        "aspect_preserved": scale_result.aspect_preserved,
        "estimator": info.get("estimator"),
        **prep_meta,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    return {"glb": glb, "object": out / "object.json",
            "thumb": thumb, "metrics": out / "metrics.json"}
