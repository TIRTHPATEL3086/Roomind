"""G01 — decode, strip EXIF, orient, resize, isolate the subject (spec 10B.2)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

from utils.safety import check_subject_area

MAX_EDGE = 1024


def _strip_exif(img: Image.Image) -> Image.Image:
    """Apply the orientation tag, then drop ALL metadata.

    Done first, before anything else touches the file: user photos routinely
    carry GPS coordinates, and this image gets stored and served back as a
    thumbnail. Re-encoding through a fresh Image object is the reliable way to
    guarantee nothing survives.
    """
    img = ImageOps.exif_transpose(img)
    clean = Image.new(img.mode, img.size)
    clean.putdata(list(img.getdata()))
    return clean


def _remove_background(img: Image.Image) -> tuple[Image.Image, str]:
    """Isolate the subject. rembg when installed, border-flood otherwise.

    rembg pulls a ~176 MB u2net model on first use, so it is optional: the
    fallback keeps the offline path working, and for the proxy billboard a
    rough cut-out is visually fine.
    """
    try:
        from rembg import remove  # type: ignore

        return remove(img).convert("RGBA"), "rembg"
    except Exception:  # noqa: BLE001 - ImportError or model-download failure
        return _flood_cutout(img), "border_flood"


def _flood_cutout(img: Image.Image, tol: int = 28) -> Image.Image:
    """Cheap cut-out: treat the median border colour as background.

    Works well on product shots and studio photos (the common Imagine input),
    poorly on busy scenes. Honest about being a fallback.
    """
    rgba = img.convert("RGBA")
    a = np.array(rgba)
    h, w = a.shape[:2]
    border = np.concatenate([
        a[0, :, :3], a[h - 1, :, :3], a[:, 0, :3], a[:, w - 1, :3],
    ])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((a[:, :, :3].astype(float) - bg) ** 2).sum(axis=2))
    a[:, :, 3] = np.where(dist < tol, 0, 255).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


def _crop_to_subject(img: Image.Image, pad: int = 8) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    return img.crop((
        max(0, x0 - pad), max(0, y0 - pad),
        min(img.width, x1 + pad), min(img.height, y1 + pad),
    ))


def prepare(data: bytes) -> tuple[Image.Image, dict]:
    """bytes -> (RGBA cut-out, metadata). Raises SafetyError on a bad subject."""
    img = Image.open(io.BytesIO(data))
    img.load()
    original = img.size

    img = _strip_exif(img).convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

    rgba, method = _remove_background(img)

    alpha = np.array(rgba.getchannel("A"))
    fraction = float((alpha > 16).mean())
    check_subject_area(fraction)

    rgba = _crop_to_subject(rgba)
    return rgba, {
        "original_size": list(original),
        "prepared_size": list(rgba.size),
        "bg_removal": method,
        "subject_fraction": round(fraction, 4),
        "exif_stripped": True,
    }
