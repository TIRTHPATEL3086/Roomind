"""G02 — label the subject and estimate its real-world size (spec 10B.4).

Two estimators:
  vlm         — Claude vision returns {label, est_dims_m, scale_confidence, ...}
  prior_table — offline median-size lookup. MANDATORY, not a nicety: it is what
                makes Imagine work with MOCK_LLM=true and no network.

The VLM path validates its own JSON and retries once before falling back, so a
malformed reply degrades to a sane size rather than failing the job.
"""
from __future__ import annotations

import json
import os
import re

from PIL import Image

from steps.g06_scale import prior_dims, sanitize_dims
from utils.safety import check_not_a_person

VALID_PLACEMENT = ("floor", "surface", "wall")

SYSTEM = """You size real-world objects from a photo. Reply ONLY with JSON.

{
  "label": "floor_lamp",          // snake_case, becomes the object id prefix
  "category": "lighting",
  "est_dims_m": [0.35, 1.62, 0.35],  // [width, height, depth] IN METRES
  "scale_confidence": 0.72,       // 0..1 - be honest, low is fine
  "placement": "floor",           // floor | surface | wall
  "is_obstacle": true
}

Height matters most - it is what the scale is matched on. If the object is a
person or part of a person, reply {"label": "person"} and nothing else."""


def _from_prior(label: str, hint: str) -> dict:
    dims, conf = prior_dims(label)
    return {
        "label": label,
        "category": "object",
        "est_dims_m": list(dims),
        "scale_confidence": conf,
        "placement": _guess_placement(label, dims),
        "is_obstacle": dims[1] > 0.10,
        "estimator": "prior_table",
        "hint": hint,
    }


def _guess_placement(label: str, dims) -> str:
    if label in ("tv", "monitor", "mirror", "clock", "picture"):
        return "wall"
    # small and short -> it belongs on a table, not the floor
    if dims[1] < 0.5 and max(dims[0], dims[2]) < 0.5:
        return "surface"
    return "floor"


def _label_from_hint(hint: str) -> str:
    """Best-effort noun from the user's hint, for the offline path."""
    words = re.findall(r"[a-z]+", (hint or "").lower())
    stop = {"a", "an", "the", "my", "this", "that", "small", "big", "large",
            "tall", "short", "nice", "new", "old", "of", "with", "and"}
    words = [w for w in words if w not in stop]
    if not words:
        return "object"
    # prior_dims already tries the head noun, so the last word is a good guess
    return "_".join(words[-2:]) if len(words) > 1 else words[-1]


def _validate(raw: dict, hint: str) -> dict | None:
    label = str(raw.get("label", "")).strip().lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z][a-z_]*", label or ""):
        return None
    if label == "person":
        check_not_a_person("person")
    dims = raw.get("est_dims_m")
    if not (isinstance(dims, list) and len(dims) == 3):
        return None
    dims, _ = sanitize_dims(dims)
    placement = raw.get("placement")
    if placement not in VALID_PLACEMENT:
        placement = _guess_placement(label, dims)
    conf = raw.get("scale_confidence", 0.5)
    try:
        conf = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "label": label,
        "category": str(raw.get("category", "object")),
        "est_dims_m": list(dims),
        "scale_confidence": conf,
        "placement": placement,
        "is_obstacle": bool(raw.get("is_obstacle", dims[1] > 0.10)),
        "estimator": "vlm",
        "hint": hint,
    }


def _ask_vlm(img: Image.Image, hint: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key.startswith("sk-ant-xxx"):
        return None
    try:
        import base64
        import io

        import anthropic

        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode()

        client = anthropic.Anthropic(api_key=key)
        for _attempt in range(2):
            resp = client.messages.create(
                model=os.environ.get("LLM_MODEL", "claude-opus-5"),
                max_tokens=1024,
                system=SYSTEM,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": f'Hint: "{hint}"' if hint else "Size it."},
                ]}],
            )
            # A refusal returns HTTP 200 with empty content.
            if resp.stop_reason == "refusal":
                return None
            text = "".join(b.text for b in resp.content if b.type == "text")
            if m := re.search(r"\{.*\}", text, re.S):
                if out := _validate(json.loads(m.group(0)), hint):
                    return out
        return None
    except Exception:  # noqa: BLE001 - any failure falls back to the prior table
        return None


def understand(img: Image.Image, hint: str = "",
               estimator: str = "prior_table") -> dict:
    check_not_a_person(hint)

    if estimator == "vlm":
        if out := _ask_vlm(img, hint):
            return out

    return _from_prior(_label_from_hint(hint), hint)
