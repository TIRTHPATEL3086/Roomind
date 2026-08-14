"""S08 - lift 2D detections into merged 3D oriented boxes (spec 10.7).

This is the step that decides whether the scene graph is worth anything. The
mesh can be beautiful and the poses perfect, but if a chair lands half a metre
from where it really is, ARIA walks into it and every answer she gives about
the room is wrong.

The shape of the algorithm:

    per detection   back-project the box's pixels to world points
                    -> drop background bleed-through
                    -> drop statistical outliers
                    -> fit a yaw-only OBB
    across frames   group by label, cluster by 3D IoU, require min_votes
                    -> confidence-weighted merge

The multi-view voting is the part that earns its keep. A single frame's box is
badly biased: you only ever see the camera-facing shell of an object, so its
depth extent is systematically too small. Three views from different angles
recover the real footprint, and anything seen only once was probably a
misdetection.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np

from utils.geometry import (
    canonicalise_yaw,
    fit_oriented_box_yaw_only,
    iou3d,
    remove_outliers,
    voxel_downsample,
)

log = logging.getLogger("recon.s08")

# Depth outside this range is either sensor noise or another room.
MIN_DEPTH_M = 0.15
MAX_DEPTH_M = 5.0
# Points further than this from the box's median depth are background showing
# through the gaps in a chair, not the chair.
DEPTH_SHELL_M = 0.5
MIN_POINTS = 50


def backproject_box(bbox, depth: np.ndarray, K: np.ndarray, pose: np.ndarray,
                    mask: np.ndarray | None = None,
                    depth_range: tuple[float, float] | None = None) -> np.ndarray:
    """Pixels inside bbox -> world points, using the frame's depth and pose.

    `pose` is camera-to-world (4x4). The median-depth shell filter is the
    difference between a chair and a chair fused with the wall behind it.

    `mask` may be either bbox-local (shape == the clipped box) or full-image;
    the shape decides. Segmentation backends naturally produce the former, and
    storing full-frame masks for every detection costs two orders of magnitude
    more memory for the same information.
    """
    h, w = depth.shape[:2]
    raw_x1, raw_y1 = (int(round(bbox[0])), int(round(bbox[1])))
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 3))

    ys, xs = np.mgrid[y1:y2, x1:x2]
    d = depth[y1:y2, x1:x2].astype(np.float64)

    valid = (d > MIN_DEPTH_M) & (d < MAX_DEPTH_M) & np.isfinite(d)
    if mask is not None:
        m = np.asarray(mask)
        if m.shape == (y2 - y1, x2 - x1):
            valid &= m.astype(bool)
        elif m.shape[:2] == depth.shape[:2]:
            valid &= m[y1:y2, x1:x2].astype(bool)
        else:
            # A bbox-local mask whose box was clipped at the image edge: index
            # it in ITS own coordinates, offset by how much was clipped away.
            oy, ox = y1 - raw_y1, x1 - raw_x1
            sub = m[oy:oy + (y2 - y1), ox:ox + (x2 - x1)]
            if sub.shape == (y2 - y1, x2 - x1):
                valid &= sub.astype(bool)
    if not valid.any():
        return np.zeros((0, 3))

    if depth_range is not None:
        # The detector measured this object's depth span in this frame. Prefer
        # it: it is exact, whereas the shell below is a fixed guess that keeps
        # half a metre of whatever stands behind the object.
        valid &= (d >= depth_range[0]) & (d <= depth_range[1])
    else:
        med = float(np.median(d[valid]))
        valid &= np.abs(d - med) < DEPTH_SHELL_M
    if not valid.any():
        return np.zeros((0, 3))

    xs, ys, d = xs[valid], ys[valid], d[valid]
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    cam = np.stack([(xs - cx) * d / fx, (ys - cy) * d / fy, d], axis=1)
    return (pose[:3, :3] @ cam.T).T + pose[:3, 3]


def _group_key(candidate: dict):
    """How to decide two detections might be the same object.

    A detector that already knows which sightings belong together -- a tracker,
    or the geometric backend, which segments in 3D and therefore assigns a
    stable cluster id -- says so via "cluster", and that identity is far more
    reliable than re-deriving it from box overlap. YOLO carries no such id, so
    those fall back to the label and get separated by 3D IoU below.
    """
    if candidate.get("cluster") is not None:
        return ("cluster", candidate["cluster"])
    return ("label", candidate["label"])


def _group_by_key(items):
    out = defaultdict(list)
    for it in items:
        out[_group_key(it)].append(it)
    return out


def _cluster_by_iou3d(group: list[dict], iou_thresh: float) -> list[list[dict]]:
    """Greedy single-link clustering, highest-confidence box first.

    Seeding from the most confident detection matters: seed from an arbitrary
    one and a low-confidence sliver can capture the cluster and drag the merged
    centre toward itself.
    """
    remaining = sorted(group, key=lambda c: -c["conf"])
    clusters: list[list[dict]] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        rest = []
        for cand in remaining:
            if iou3d(seed, cand) >= iou_thresh:
                cluster.append(cand)
            else:
                rest.append(cand)
        remaining = rest
        clusters.append(cluster)
    return clusters


def _circular_mean_yaw(yaws: np.ndarray, weights: np.ndarray) -> float:
    """Weighted mean of yaws that live on a HALF circle.

    Yaws are canonicalised to [-90, 90), so -89 deg and +89 deg are two degrees
    apart, not 178. Averaging them arithmetically gives 0 -- a box turned
    exactly the wrong way. Doubling the angle maps the half circle onto a full
    one, where the ordinary circular mean is correct; halving brings it back.
    """
    a = 2 * yaws
    s = float(np.sum(weights * np.sin(a)))
    c = float(np.sum(weights * np.cos(a)))
    return float(np.arctan2(s, c) / 2)


def _weighted_merge(cluster: list[dict]) -> dict:
    """Pool the POINTS from every view, then fit one box.

    The obvious merge is to fit a box per view and average the boxes. It is
    worse, and measurably so. Each view sees only the camera-facing shell of an
    object, so each per-view box is a different partial under-estimate; no
    summary statistic over those (mean, median, or the 75th percentile this
    used to take) can recover an extent that no single view observed. Pooling
    the points first turns six partial views into one nearly-complete object
    and fits the box to that.

    On this room's sofa: per-view boxes averaged out to 1.34 m against a true
    1.90 m, while the pooled cloud recovers 1.8 m -- because between them the
    views DO cover the whole sofa, they just never do so individually.
    """
    pts = np.vstack([c["points"] for c in cluster])
    pts = voxel_downsample(pts, 0.02)
    box = canonicalise_yaw(fit_oriented_box_yaw_only(pts))

    confs = np.array([c["conf"] for c in cluster], dtype=np.float64)
    label, label_meta = _merge_label(cluster)
    return {
        "label": label,
        **label_meta,
        "position": box["position"],
        "dimensions": box["dimensions"],
        "rotation_y": box["rotation_y"],
        "surface_height": box["surface_height"],
        "y_min": box["y_min"],
        # More independent sightings means more confidence, up to a ceiling:
        # the tenth view of a chair adds much less than the third.
        "confidence": float(min(0.99, float(confs.mean())
                                * min(1.0, 0.6 + 0.13 * len(cluster)))),
        "votes": len(cluster),
        "color": _merge_color(cluster),
        "points": len(pts),
    }


def _merge_label(cluster: list[dict]) -> tuple[str, dict]:
    """The cluster's class, plus how that class was decided.

    A cluster is one physical object, so its sightings must agree on one label.
    Taking `cluster[0]["label"]` was safe while every sighting in a group came
    from the same YOLO class by construction; under the fusion backend the
    grouping key is the 3D cluster id instead, and a single frame where the
    sofa was called a bed would otherwise decide the whole object's identity
    purely by sort order.

    Weighted by the class confidence, so a hesitant outlier cannot outvote a
    confident majority, and the winning label keeps the BEST confidence any
    view had for it rather than an average dragged down by partial glimpses.
    """
    weights: dict[str, float] = {}
    best_conf: dict[str, float] = {}
    for c in cluster:
        label = c.get("label", "object")
        if label == "object":
            continue
        # `label_confidence` is present-but-None for detections no recogniser
        # scored, so this needs a falsy fallback rather than a dict default.
        w = float(c.get("label_confidence") or c.get("conf") or 0.5)
        weights[label] = weights.get(label, 0.0) + w
        best_conf[label] = max(best_conf.get(label, 0.0), w)

    if not weights:
        return "object", {"label_source": "size_prior", "label_confidence": None}

    label = max(weights.items(), key=lambda kv: (kv[1], kv[0]))[0]
    total = sum(weights.values())
    agreement = weights[label] / total if total else 1.0
    sources = {c.get("label_source") for c in cluster if c.get("label") == label}
    return label, {
        "label_source": "yolo" if "yolo" in sources else "size_prior",
        "label_confidence": float(min(0.99, best_conf[label] * agreement)),
        "label_agreement": round(float(agreement), 3),
    }


def _merge_color(cluster: list[dict]) -> str | None:
    cols = [c["rgb"] for c in cluster if c.get("rgb") is not None]
    if not cols:
        return None
    med = np.median(np.array(cols), axis=0).astype(int)
    return "#%02X%02X%02X" % tuple(int(np.clip(v, 0, 255)) for v in med)


def assign_ids(merged: list[dict]) -> list[dict]:
    """Ids as {label}_{i:02d}, ordered by descending confidence (spec 10.7).

    The label is sanitised to the frozen id pattern ^[a-z_]+_[0-9]{2}$ first:
    COCO hands back 'potted plant' and 'dining table', and a space in an id
    fails schema validation at the very last step of a three-minute pipeline.

    STABILITY. Confidence alone is not a total order once a room holds several
    instances of one class. Ten identical chairs land within a few thousandths
    of each other, so the smallest change anywhere upstream -- one extra
    keyframe, a different voxel falling on a boundary -- reshuffles which chair
    is chair_01. Ids are user-visible (ARIA quotes them, and "go to chair
    number 3" resolves through the number), so a reshuffle silently changes
    which physical object a remembered id refers to.

    Rounding the confidence to 3 dp and breaking ties on position makes the
    ordering depend on where the furniture IS rather than on float noise. The
    spec's rule is preserved: it still sorts by descending confidence, and the
    tie-break only decides cases the rule leaves undefined.
    """
    out = []
    counters: dict[str, int] = defaultdict(int)

    def order(o: dict):
        pos = o["position"]
        return (-round(float(o["confidence"]), 3),
                round(float(pos[2]), 3), round(float(pos[0]), 3))

    for obj in sorted(merged, key=order):
        label = sanitise_label(obj["label"])
        counters[label] += 1
        out.append({**obj, "label": label, "id": f"{label}_{counters[label]:02d}",
                    "instance_index": counters[label]})
    return out


def sanitise_label(label: str) -> str:
    """'Dining Table' -> 'dining_table'. Anything left over becomes 'object'."""
    cleaned = "".join(ch if ch.isalpha() else "_" for ch in label.lower())
    cleaned = "_".join(p for p in cleaned.split("_") if p)
    return cleaned or "object"


def lift_boxes_to_3d(detections_per_frame, depths, poses, K,
                     min_votes: int = 3, iou_thresh: float = 0.3,
                     rgbs=None) -> list[dict]:
    """Detections from every frame -> merged, id'd 3D objects.

    min_votes is a real quality knob. At 1 you keep every hallucinated box; at 3
    you need the same object seen from three angles, which is what the multi-view
    consistency is FOR. Short captures get it relaxed by the caller.
    """
    candidates: list[dict] = []
    for det in detections_per_frame:
        f = det["frame_idx"]
        if f >= len(depths) or f >= len(poses):
            continue
        pts = backproject_box(det["bbox"], depths[f], K, poses[f],
                              det.get("mask"), det.get("depth_range"))
        if len(pts) < MIN_POINTS:
            continue

        # Downsample BEFORE outlier removal: it is O(n^2) in the point count and
        # a close-up sofa fills 200k pixels.
        pts = voxel_downsample(pts, 0.02)
        pts = remove_outliers(pts, nb=20, std_ratio=2.0)
        if len(pts) < MIN_POINTS // 2:
            continue

        box = canonicalise_yaw(fit_oriented_box_yaw_only(pts))
        # Keep the points: the merge below pools them across views rather than
        # averaging the per-view boxes. See _weighted_merge.
        box.update(label=det["label"], conf=float(det.get("conf", 1.0)),
                   cluster=det.get("cluster"), points=pts,
                   label_source=det.get("label_source"),
                   label_confidence=det.get("label_confidence"),
                   rgb=_sample_rgb(rgbs, f, det["bbox"]))
        candidates.append(box)

    merged: list[dict] = []
    for key, group in _group_by_key(candidates).items():
        # A detector-supplied cluster id already IS the grouping, so re-splitting
        # it by IoU would only undo work: partial views of one sofa from
        # opposite sides can overlap by less than the threshold.
        clusters = ([group] if key[0] == "cluster"
                    else _cluster_by_iou3d(group, iou_thresh))
        for cluster in clusters:
            if len(cluster) < min_votes:
                log.debug("dropped %s with %d vote(s)", key, len(cluster))
                continue
            merged.append(_weighted_merge(cluster))

    return assign_ids(merged)


def _sample_rgb(rgbs, frame_idx: int, bbox) -> list[int] | None:
    """Median colour of the detection's pixels, for the scene-graph swatch."""
    if rgbs is None or frame_idx >= len(rgbs):
        return None
    img = rgbs[frame_idx]
    h, w = img.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    patch = img[y1:y2, x1:x2].reshape(-1, 3)
    return np.median(patch, axis=0).tolist()
