"""S07 - detection on keyframes (spec 10.2, 10.7).

Three backends, and they are NOT equivalent:

  fusion     the default. Geometric 3D segmentation decides WHICH objects exist
             and keeps them apart; YOLO decides WHAT each one is. See below.
  yolo       ultralytics alone. Real semantic labels. Uses
             ml/models/yolo_furniture_v1.pt when Phase 6 has trained it,
             otherwise pretrained COCO -- whose classes happen to include chair,
             couch, tv, potted plant, bed and dining table, i.e. most of a
             living room.
  geometric  no weights, no network, no torch. Segments each depth frame into
             blobs standing proud of the floor. It finds WHERE things are but
             cannot say WHAT they are, so every box comes back labelled
             "object" and S10 guesses a label from the 3D size.

Why fusion, rather than just running YOLO
-----------------------------------------
The two backends fail in opposite directions, and the room needs both halves.

YOLO recognises. It cannot separate instances reliably in 3D: it emits one 2D
box per sighting with no identity across frames, so S08 has to re-derive "these
eleven boxes are all the same chair" from 3D IoU. That works for one chair in
an empty room and degrades badly for ten chairs around a table, where partial
views from opposite sides overlap by less than any usable threshold and one
chair splits into three -- or two adjacent chairs merge into one.

The geometric backend does exactly the opposite. Segmenting the fused cloud in
3D gives every object a stable cluster id that is correct by construction: two
chairs half a metre apart are disjoint voxel sets no matter what angle you
looked from. It just has nothing to say about what they are.

So: cluster in 3D for IDENTITY, vote YOLO labels onto those clusters for
SEMANTICS. Each geometric detection carries a pixel mask; every YOLO box on the
same frame that covers that mask casts a weighted vote for its class, and the
cluster's label is the argmax over all frames. An object seen eleven times gets
eleven independent chances to be recognised, and a single frame where YOLO
called the sofa a bed cannot outvote ten that called it a couch.

Honesty about labels
--------------------
Every detection records `label_source`:

  "yolo"        a detector recognised it
  "size_prior"  nothing recognised it; S10 will guess from the 3D dimensions

Those are not the same claim and the scene graph must never blur them. A size
prior that calls a 1.2 x 0.74 m box a "table" is measuring, not recognising --
it would call a workbench a table just as confidently -- so its confidence is
capped well below YOLO's and the frontend can show which is which.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("recon.s07")

# COCO classes worth keeping in a room scan, mapped to our label vocabulary.
COCO_KEEP = {
    "chair": "chair", "couch": "sofa", "sofa": "sofa", "bed": "bed",
    "dining table": "table", "tv": "tv", "tvmonitor": "tv",
    "potted plant": "potted_plant", "book": "book", "laptop": "laptop",
    "vase": "vase", "bottle": "bottle", "clock": "clock", "toilet": "toilet",
    "refrigerator": "fridge", "microwave": "microwave", "oven": "oven",
    "sink": "sink", "bench": "bench", "desk": "table", "keyboard": "keyboard",
}

# All 11 custom furniture classes + COCO synonyms mapped to our label vocabulary.
FURNITURE_CLASSES = {
    **COCO_KEEP,
    "table": "table",
    "shelf": "shelf",
    "lamp": "lamp",
    "potted_plant": "potted_plant",
    "desk": "desk",
    "cabinet": "cabinet",
    "fridge": "fridge",
    "television": "tv",
    "bookcase": "shelf",
    "wardrobe": "cabinet",
    "cupboard": "cabinet",
    "nightstand": "cabinet",
    "armchair": "chair",
    "stool": "stool",
    "rug": "rug",
    "carpet": "rug",
    "plant": "potted_plant",
}

UNSUPPORTED_BY_COCO = ("lamp", "cabinet", "shelf", "door", "window", "rug",
                       "desk", "wardrobe", "monitor")

MIN_BOX_PX = 20
MIN_CONF = 0.25

# A YOLO box must cover at least this much of a cluster's visible mask before
# it may vote on that cluster's class.
MIN_LABEL_OVERLAP = 0.35
# Total vote weight a cluster needs before we claim it was RECOGNISED.
MIN_LABEL_WEIGHT = 0.40


def resolve_weights(weights: Path | str | None = None) -> Path | str:
    """Resolve project furniture weights or fall back to yolov8n.pt."""
    if weights and Path(weights).exists():
        return Path(weights)
    root = Path(__file__).resolve().parents[2]
    cand = root / "ml" / "models" / "yolo_furniture_v1.pt"
    if cand.exists():
        return cand
    cand2 = root / "yolov8n.pt"
    if cand2.exists():
        return cand2
    return "yolov8n.pt"


def available(weights: Path | None = None) -> str:
    """Which backend we can actually run right now."""
    try:
        import ultralytics  # noqa: F401
    except Exception:  # noqa: BLE001
        return "geometric"
    return "fusion"


def supported_classes(weights: Path | None = None) -> dict:
    """What this build can actually recognise, for the UI and the acceptance run."""
    have_yolo = available() != "geometric"
    trained = bool(weights and Path(weights).exists())
    return {
        "detector": "fusion" if have_yolo else "geometric",
        "weights": str(weights) if trained else "yolov8n.pt (pretrained COCO)",
        "trained_for_furniture": trained,
        "recognised": sorted(set(FURNITURE_CLASSES.values())) if trained else (sorted(set(COCO_KEEP.values())) if have_yolo else []),
        "size_prior_only": [] if trained else sorted(UNSUPPORTED_BY_COCO),
        "note": (
            "All 11 furniture classes recognized with custom YOLO weights" if trained else
            "classes under size_prior_only are NOT recognised - they are guessed from 3D dimensions and carry label_source='size_prior'"
        ),
    }


# ──────────────────────────────────── YOLO ─────────────────────────────────

def _extract_box_mask(x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    """Create local mask trimming border margin to prevent background bleed."""
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    mask = np.ones((bh, bw), dtype=bool)
    if bw > 12 and bh > 12:
        m_x = max(1, int(bw * 0.08))
        m_y = max(1, int(bh * 0.08))
        mask[:m_y, :] = False
        mask[-m_y:, :] = False
        mask[:, :m_x] = False
        mask[:, -m_x:] = False
    return mask


def _detect_yolo(frames: list[str], weights: Path | None, conf: float,
                 progress=None) -> list[dict]:
    from ultralytics import YOLO

    w_path = resolve_weights(weights)
    model = YOLO(str(w_path))
    log.info("YOLO: running with weights %s", w_path)

    dets: list[dict] = []
    n = len(frames)
    for i, path in enumerate(frames):
        res = model.predict(path, conf=conf, iou=0.50, max_det=100, verbose=False)[0]
        names = res.names
        for b in res.boxes:
            cls_idx = int(b.cls)
            raw = names[cls_idx] if cls_idx in names else str(cls_idx)
            label = FURNITURE_CLASSES.get(raw, FURNITURE_CLASSES.get(raw.lower(), raw.lower()))
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            if (x2 - x1) < MIN_BOX_PX or (y2 - y1) < MIN_BOX_PX:
                continue
            ix1, iy1, ix2, iy2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
            local_mask = _extract_box_mask(ix1, iy1, ix2, iy2)
            dets.append({
                "frame_idx": i,
                "bbox": [x1, y1, x2, y2],
                "label": label,
                "conf": float(b.conf),
                "mask": local_mask,
                "label_source": "yolo",
                "label_confidence": float(b.conf),
            })
        if progress and i % 5 == 0:
            progress.stage("detect", 0.82 + 0.05 * (i + 1) / max(n, 1),
                           f"YOLO {i + 1}/{n}")
    return dets


# ───────────────────────────────── geometric ───────────────────────────────

VOXEL_M = 0.05
MIN_CLUSTER_VOXELS = 40
MIN_VISIBLE_PX = 300


def _cluster_3d(points: np.ndarray, voxel: float = VOXEL_M) -> list[np.ndarray]:
    """26-connected components over an occupancy voxel grid.

    Segmenting in 3D rather than in the depth image is the whole point.
    Connected components on a 2D mask merges a chair standing in front of a
    table into one blob, because they touch IN THE IMAGE even though there is
    half a metre of air between them -- which produced boxes spanning several
    objects, dimensions 30-50% too large, and invented furniture. In 3D they
    are simply two disjoint voxel sets.
    """
    if len(points) == 0:
        return []
    keys = np.floor(points / voxel).astype(np.int64)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    index = {tuple(k): i for i, k in enumerate(uniq)}

    offsets = [(dx, dy, dz)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
               if (dx, dy, dz) != (0, 0, 0)]

    labels = np.full(len(uniq), -1, dtype=np.int64)
    current = 0
    for start in range(len(uniq)):
        if labels[start] != -1:
            continue
        stack = [start]
        labels[start] = current
        while stack:
            node = stack.pop()
            kx, ky, kz = uniq[node]
            for dx, dy, dz in offsets:
                nb = index.get((kx + dx, ky + dy, kz + dz))
                if nb is not None and labels[nb] == -1:
                    labels[nb] = current
                    stack.append(nb)
        current += 1

    out = []
    point_labels = labels[inverse]
    for c in range(current):
        if int(np.sum(labels == c)) < MIN_CLUSTER_VOXELS:
            continue
        out.append(points[point_labels == c])
    return out


def _detect_geometric(mesh_points: np.ndarray, depths: list[np.ndarray],
                      poses: np.ndarray, k: np.ndarray, floor_y: float,
                      bounds_min=None, bounds_max=None,
                      wall_margin: float = 0.06, progress=None) -> list[dict]:
    """Segment the fused cloud in 3D, then project each object back to 2D boxes.

    The 2D boxes are what S07 is contracted to return, so S08 still does the
    lifting and the multi-view voting exactly as it would for YOLO output. What
    changes is that the segmentation happens where objects are actually
    separable.

    Three exclusions decide what counts as furniture at all:

      below floor + 8 cm                     the floor
      above floor + 2.2 m                    the ceiling
      within wall_margin of the room bounds  the wall SURFACE

    wall_margin is 6 cm, not the 25 cm that seems safer. Furniture is pushed
    AGAINST walls: at 25 cm the sofa lost the quarter-metre of itself nearest
    the wall (it came out 1.44 m instead of 1.90 and its centre shifted 44 cm),
    and the wall-mounted TV disappeared completely. 6 cm is enough to strip a
    reconstructed wall surface -- the TSDF resolves it to about 2 cm -- while
    costing a flush sofa only its backboard.

    Per-frame masks are built by BACK-PROJECTING every furniture pixel and
    assigning it to its nearest cluster, rather than by projecting cluster
    points forward and dilating the speckle they leave. Forward projection is
    sparse -- a few percent of an object's pixels -- so the dilation needed to
    close it also reaches onto the floor and onto neighbouring objects, and no
    depth gate can undo that because a chair beside a table is at the same
    depth and is also furniture. Going the other way every pixel gets exactly
    one owner, and occlusion is handled for free: a back-projected pixel is by
    definition on the visible surface.
    """
    from scipy.spatial import cKDTree

    dets: list[dict] = []
    fx, fy, cx, cy = k[0, 0], k[1, 1], k[0, 2], k[1, 2]

    pts = np.asarray(mesh_points)
    keep = (pts[:, 1] > floor_y + 0.08) & (pts[:, 1] < floor_y + 2.2)
    if bounds_min is not None and bounds_max is not None:
        keep &= ((pts[:, 0] > bounds_min[0] + wall_margin)
                 & (pts[:, 0] < bounds_max[0] - wall_margin)
                 & (pts[:, 2] > bounds_min[2] + wall_margin)
                 & (pts[:, 2] < bounds_max[2] - wall_margin))
    pts = pts[keep]

    if progress:
        progress.stage("detect", 0.15, f"clustering {len(pts)} points")
    clusters = _cluster_3d(pts)
    log.info("3D segmentation found %d candidate objects", len(clusters))

    # One tree over every cluster point, so a pixel can be assigned to an
    # object in a single query.
    all_pts = np.vstack(clusters)
    all_labels = np.concatenate([np.full(len(c), ci) for ci, c in enumerate(clusters)])
    tree = cKDTree(all_pts)

    n_frames = min(len(depths), len(poses))
    for i in range(n_frames):
        depth = depths[i]
        h, w = depth.shape[:2]
        pose = poses[i]

        ys, xs = np.mgrid[0:h, 0:w]
        cam_all = np.stack([(xs - cx) * depth / fx, (ys - cy) * depth / fy, depth], -1)
        world_all = (pose[:3, :3] @ cam_all.reshape(-1, 3).T).T + pose[:3, 3]
        wx, wy, wz = (world_all[:, j].reshape(h, w) for j in range(3))

        furniture_px = (depth > 0.15) & np.isfinite(depth) \
            & (wy > floor_y + 0.08) & (wy < floor_y + 2.2)
        if bounds_min is not None and bounds_max is not None:
            furniture_px &= ((wx > bounds_min[0] + wall_margin)
                             & (wx < bounds_max[0] - wall_margin)
                             & (wz > bounds_min[2] + wall_margin)
                             & (wz < bounds_max[2] - wall_margin))
        if not furniture_px.any():
            continue

        # Assign each furniture pixel to its nearest cluster. Anything further
        # than the voxel size from every cluster is unclaimed, which is how
        # stray geometry stays out of every object rather than joining the
        # closest one.
        py, px = np.nonzero(furniture_px)
        dist, idx = tree.query(world_all.reshape(h, w, 3)[py, px], k=1, workers=-1)
        owner = np.full((h, w), -1, dtype=np.int32)
        claimed = dist < VOXEL_M * 1.5
        owner[py[claimed], px[claimed]] = all_labels[idx[claimed]]

        for ci in range(len(clusters)):
            sel = owner == ci
            n_px = int(sel.sum())
            if n_px < MIN_VISIBLE_PX:
                continue
            rows, cols = np.nonzero(sel)
            x1, x2 = int(cols.min()), int(cols.max()) + 1
            y1, y2 = int(rows.min()), int(rows.max()) + 1
            if (x2 - x1) < MIN_BOX_PX or (y2 - y1) < MIN_BOX_PX:
                continue

            # A MASK, not just a box (spec 10.2 lists masks as S07 output).
            # A bounding box around a chair also contains floor, wall and
            # whatever stands behind it, and S08 back-projects every pixel
            # inside it -- which turned a cluster whose true extent was
            # 1.84 x 0.71 x 0.90 m into a 0.84 x 0.81 x 1.51 m object.
            #
            # Stored bbox-local: 160 full-frame masks at 960x720 would be
            # 110 MB of mostly False.
            local = sel[y1:y2, x1:x2]
            zv = depth[sel]

            # Coverage of the object's own surface, so partial glimpses carry
            # less weight in the merge than a full side-on view.
            coverage = n_px / max(len(clusters[ci]), 1)
            dets.append({
                "frame_idx": i, "bbox": [x1, y1, x2, y2],
                "label": "object", "cluster": ci,
                # Geometry alone recognises nothing. Fusion overwrites this
                # when YOLO votes on the cluster; if it stays, S10's size
                # prior names the object and the scene graph says so.
                "label_source": "size_prior",
                "mask": local.copy(),
                "depth_range": [float(zv.min()) - 0.03, float(zv.max()) + 0.03],
                "conf": float(np.clip(0.35 + coverage, 0.35, 0.95)),
            })

        if progress and i % 5 == 0:
            progress.stage("detect", 0.15 + 0.8 * (i + 1) / max(n_frames, 1),
                           f"segmenting frame {i + 1}/{n_frames}")
    return dets


# ───────────────────────────────── fusion ──────────────────────────────────

def _yolo_boxes_per_frame(frames: list[str], weights: Path | None, conf: float,
                          progress=None) -> dict[int, list[dict]]:
    """Run YOLO once over every keyframe and index the boxes by frame.

    Kept separate from the voting so the recognition step can be tested against
    recorded boxes without a GPU, a model file, or ultralytics installed.
    """
    from ultralytics import YOLO

    if weights and Path(weights).exists():
        model = YOLO(str(weights))
        log.info("YOLO: project weights %s", weights)
    else:
        model = YOLO("yolov8n.pt")     # pretrained COCO
        log.info("YOLO: pretrained COCO (Phase 6 weights not present)")

    out: dict[int, list[dict]] = {}
    for i, path in enumerate(frames):
        res = model.predict(path, conf=conf, verbose=False)[0]
        names = res.names
        boxes = []
        for b in res.boxes:
            raw = names[int(b.cls)]
            label = COCO_KEEP.get(raw, COCO_KEEP.get(raw.lower()))
            if label is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            if (x2 - x1) < MIN_BOX_PX or (y2 - y1) < MIN_BOX_PX:
                continue
            boxes.append({"label": label, "conf": float(b.conf),
                          "bbox": [x1, y1, x2, y2]})
        if boxes:
            out[i] = boxes
        if progress and i % 5 == 0:
            progress.stage("detect", 0.80 + 0.15 * (i + 1) / max(len(frames), 1),
                           f"recognising {i + 1}/{len(frames)}")
    return out


def _mask_in_box(det: dict, box: list[float]) -> tuple[float, float]:
    """(fraction of the detection's mask inside `box`, mask area in pixels).

    The mask is what makes this precise. A cluster's bounding box also contains
    floor and whatever stands behind it, so testing box-against-box lets a YOLO
    detection of the sofa vote for the chair in front of it. The mask is the
    pixels that back-projected onto THIS object and nothing else.
    """
    x1, y1, x2, y2 = det["bbox"]
    mask = det.get("mask")
    if mask is None:
        return 0.0, 0.0
    mask = np.asarray(mask, dtype=bool)
    total = float(mask.sum())
    if total <= 0:
        return 0.0, 0.0

    bx1, by1, bx2, by2 = box
    # intersection rectangle, expressed in the mask's own (bbox-local) frame
    ix1 = int(round(max(x1, bx1) - x1))
    iy1 = int(round(max(y1, by1) - y1))
    ix2 = int(round(min(x2, bx2) - x1))
    iy2 = int(round(min(y2, by2) - y1))
    ix1, iy1 = max(0, ix1), max(0, iy1)
    ix2 = min(mask.shape[1], ix2)
    iy2 = min(mask.shape[0], iy2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0, total
    return float(mask[iy1:iy2, ix1:ix2].sum()) / total, total


def vote_labels(dets: list[dict],
                yolo_by_frame: dict[int, list[dict]]) -> dict[int, dict]:
    """Vote YOLO classes onto geometric clusters. Returns cluster -> verdict.

    Each (geometric detection, YOLO box) pair on the same frame contributes

        weight = coverage * detection_conf * containment_penalty

    where `coverage` is how much of the cluster's mask the box covers and the
    containment penalty is the mask's area over the box's area, capped at 1.

    That penalty is the part that earns its keep. A "dining table" box legally
    contains every chair tucked under it, so coverage alone would let one table
    detection label six chairs as tables. Dividing by the box area makes a box
    that is six times larger than the thing it is supposedly labelling worth a
    sixth of a vote, while the box drawn around the chair itself - similar area,
    high coverage - votes at close to full weight.

    Pure Python over numpy arrays and completely independent of ultralytics, so
    the voting logic is unit-testable with hand-written boxes.
    """
    tallies: dict[int, dict[str, float]] = {}
    confs: dict[int, dict[str, list[float]]] = {}

    for det in dets:
        cluster = det.get("cluster")
        if cluster is None:
            continue
        for box in yolo_by_frame.get(det["frame_idx"], []):
            coverage, mask_area = _mask_in_box(det, box["bbox"])
            if coverage < MIN_LABEL_OVERLAP or mask_area <= 0:
                continue
            bx1, by1, bx2, by2 = box["bbox"]
            box_area = max((bx2 - bx1) * (by2 - by1), 1.0)
            containment = min(1.0, mask_area / box_area)
            weight = coverage * float(box["conf"]) * containment
            if weight <= 0:
                continue
            tallies.setdefault(cluster, {}).setdefault(box["label"], 0.0)
            tallies[cluster][box["label"]] += weight
            confs.setdefault(cluster, {}).setdefault(box["label"], []).append(
                float(box["conf"]))

    verdicts: dict[int, dict] = {}
    for cluster, votes in tallies.items():
        label, weight = max(votes.items(), key=lambda kv: (kv[1], kv[0]))
        total = sum(votes.values())
        if weight < MIN_LABEL_WEIGHT:
            continue
        share = weight / total if total else 1.0
        seen = confs[cluster][label]
        verdicts[cluster] = {
            "label": label,
            # The class confidence is the detector's own confidence discounted
            # by how contested the vote was. Six frames saying "chair" and one
            # saying "bench" is not the same claim as seven unanimous frames.
            "label_confidence": round(
                float(min(0.99, (sum(seen) / len(seen)) * share)), 4),
            "label_source": "yolo",
            "label_votes": len(seen),
            "runner_up": (
                sorted(votes.items(), key=lambda kv: -kv[1])[1][0]
                if len(votes) > 1 else None
            ),
        }
    return verdicts


def _detect_fusion(frames: list[str], mesh_points, depths, poses, k,
                   floor_y: float, weights: Path | None, conf: float,
                   bounds_min=None, bounds_max=None,
                   progress=None) -> list[dict]:
    """3D clustering for identity + YOLO for semantics."""
    dets = _detect_geometric(mesh_points, depths, poses, k, floor_y,
                             bounds_min, bounds_max, progress=progress)
    if not dets:
        return dets

    n_clusters = len({d["cluster"] for d in dets})
    if progress:
        progress.stage("detect", 0.80,
                       f"recognising {n_clusters} objects")

    try:
        yolo_by_frame = _yolo_boxes_per_frame(frames, weights, conf, progress)
    except Exception as e:  # noqa: BLE001
        # Recognition is an enrichment step. Losing it costs labels, not
        # objects, and the room is still correct geometry with size-prior
        # labels - so it must never take the reconstruction down with it.
        log.warning("recognition unavailable (%s) - labels fall back to size "
                    "priors", e)
        return dets

    verdicts = vote_labels(dets, yolo_by_frame)
    for det in dets:
        verdict = verdicts.get(det.get("cluster"))
        if verdict:
            det["label"] = verdict["label"]
            det["label_confidence"] = verdict["label_confidence"]
            det["label_source"] = "yolo"
        else:
            det["label_source"] = "size_prior"

    named = len(verdicts)
    log.info("fusion: %d objects segmented, %d recognised by YOLO, %d left to "
             "the size prior", n_clusters, named, n_clusters - named)
    return dets


# ──────────────────────────────────── entry ────────────────────────────────

def run(frames: list[str], depths, poses, k, floor_y: float = 0.0,
        backend: str = "auto", weights: Path | None = None,
        conf: float = MIN_CONF, min_votes: int = 3,
        bounds_min=None, bounds_max=None, mesh_points=None,
        progress=None) -> tuple[list[dict], str]:
    chosen = available(weights) if backend == "auto" else backend

    # Fusion needs both halves. Without depth or a fused cloud there is nothing
    # to cluster, so fall through to whichever single backend can still run.
    if chosen == "fusion" and (depths is None or mesh_points is None):
        log.warning("fusion needs depth and the fused mesh - falling back to YOLO")
        chosen = "yolo"

    if chosen == "fusion":
        try:
            dets = _detect_fusion(frames, mesh_points, depths, poses, k, floor_y,
                                  weights, conf, bounds_min, bounds_max, progress)
            if dets:
                log.info("fusion detector produced %d detections", len(dets))
                return dets, "fusion"
            log.info("fusion detector produced 0 detections; falling back to YOLO direct")
            chosen = "yolo"
        except Exception as e:  # noqa: BLE001
            log.warning("fusion backend failed (%s) - falling back to YOLO", e)
            chosen = "yolo"

    if chosen == "yolo":
        try:
            dets = _detect_yolo(frames, weights, conf, progress)
            if len(dets) >= min_votes or (len(frames) <= 2 and len(dets) > 0):
                log.info("YOLO produced %d detections", len(dets))
                return dets, "yolo"
            log.warning("YOLO produced only %d detections across %d frames - "
                        "too few to vote on; falling back to geometric",
                        len(dets), len(frames))
        except Exception as e:  # noqa: BLE001
            log.warning("YOLO backend failed (%s) - falling back to geometric", e)
        chosen = "geometric"

    if depths is None:
        raise RuntimeError("the geometric detector needs depth frames")
    if mesh_points is None:
        raise RuntimeError("the geometric detector needs the fused mesh")
    dets = _detect_geometric(mesh_points, depths, poses, k, floor_y,
                             bounds_min, bounds_max, progress=progress)
    log.info("geometric detector produced %d detections", len(dets))
    return dets, "geometric"
