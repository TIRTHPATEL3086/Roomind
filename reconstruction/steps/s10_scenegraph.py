"""S10 - emit room.json (spec 10.7 post-processing, 8.2 schema).

Every rule in the 10.7 table is applied here, and each one exists because
skipping it produces a specific visible failure:

  floor snap        detections drift vertically; without it chairs hover
  dimension gate    < 5 cm or > 4 m is noise, not furniture
  bounds gate       a back-projection error puts a sofa outside the wall
  is_climbable      marks flat tops the Imagine placer can put things on
  is_obstacle       anything over 10 cm blocks the robot; feeds the navmesh
  colour            median projected pixel, for the UI swatch
  id assignment     {label}_{NN} by descending confidence, per 8.2

The output MUST validate against contracts/scene_graph.schema.json. That is
checked here rather than left to the caller, because failing at the last step
of a three-minute pipeline with an unvalidated file is how a bad room reaches
the dashboard.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path

import numpy as np

from utils.shared import colors, spatial

log = logging.getLogger("recon.s10")

ID_PATTERN = re.compile(r"^[a-z_]+_[0-9]{2}$")

# Below this, an object is real enough to keep on the map (the navmesh still
# has to avoid it) but too shaky to act on without asking. The resolver refuses
# to navigate to an uncertain object without confirmation.
LOW_CONFIDENCE = 0.45

# Labels that stand on the floor. Their boxes get snapped down to it.
FLOOR_STANDING = {
    "chair", "table", "sofa", "shelf", "potted_plant", "bed", "desk",
    "bench", "stool", "cabinet", "fridge", "rug", "object",
}
# Labels with a usable flat top (spec 10.7 is_climbable rule).
CLIMBABLE_LABELS = {"table", "chair", "sofa", "shelf", "box", "stool", "desk", "bench"}
CLIMBABLE_MAX_HEIGHT_M = 0.75
OBSTACLE_MIN_HEIGHT_M = 0.10

# Size priors for the geometric detector, which knows WHERE but not WHAT.
# (label, [w, h, d] typical metres, tolerance). Ordered: first match wins.
SIZE_PRIORS: list[tuple[str, tuple[float, float, float], float]] = [
    ("rug",          (1.60, 0.02, 1.00), 0.90),
    ("sofa",         (1.90, 0.80, 0.90), 0.45),
    ("bed",          (1.90, 0.55, 1.40), 0.45),
    ("table",        (1.20, 0.74, 0.75), 0.45),
    ("desk",         (1.20, 0.74, 0.60), 0.40),
    ("shelf",        (0.80, 1.80, 0.35), 0.45),
    ("chair",        (0.55, 0.90, 0.55), 0.35),
    ("stool",        (0.35, 0.45, 0.35), 0.30),
    ("potted_plant", (0.40, 0.80, 0.40), 0.40),
    ("tv",           (1.10, 0.65, 0.08), 0.40),
    ("lamp",         (0.30, 1.50, 0.30), 0.40),
    ("cabinet",      (0.90, 1.20, 0.50), 0.45),
    ("fridge",       (0.80, 1.75, 0.70), 0.40),
]


def classify_by_size(dims) -> tuple[str, float]:
    """Guess a label from 3D dimensions. Used only for geometric detections.

    Returns (label, confidence). This is a WEAK classifier and its confidence
    says so -- it caps at 0.55, well below what YOLO reports, so nothing
    downstream mistakes a size guess for recognition.
    """
    w, h, d = (float(v) for v in dims)
    # Compare orientation-insensitively: a table rotated 90 deg is still a table.
    got = np.array([max(w, d), h, min(w, d)])

    best, best_err = None, 1e9
    for label, proto, tol in SIZE_PRIORS:
        pw, ph, pd = proto
        want = np.array([max(pw, pd), ph, min(pw, pd)])
        err = float(np.mean(np.abs(got - want) / np.maximum(want, 0.05)))
        if err < tol and err < best_err:
            best, best_err = label, err

    if best is None:
        return "object", 0.30
    return best, float(min(0.55, 0.55 * (1.0 - best_err)))


def _in_bounds(pos, bmin, bmax, margin: float = 0.35) -> bool:
    return (bmin[0] - margin <= pos[0] <= bmax[0] + margin
            and bmin[2] - margin <= pos[2] <= bmax[2] + margin)


def post_process(objects: list[dict], floor_y: float, bmin, bmax,
                 detector: str) -> tuple[list[dict], list[dict]]:
    """Apply the 10.7 rules. Returns (kept, rejected_with_reasons)."""
    kept: list[dict] = []
    rejected: list[dict] = []

    for obj in objects:
        w, h, d = (float(v) for v in obj["dimensions"])
        label = obj["label"]
        conf = float(obj.get("confidence", 0.5))
        label_source = obj.get("label_source") or "size_prior"
        label_conf = obj.get("label_confidence")

        # The size prior runs whenever nothing RECOGNISED the object, whichever
        # backend produced it. Under fusion that is a per-object question, not
        # a per-run one: YOLO may name six clusters in a room and leave the
        # lamp unnamed because COCO has no lamp class at all.
        if label == "object":
            label, prior_conf = classify_by_size(obj["dimensions"])
            label_source = "size_prior"
            label_conf = prior_conf
            if label != "object":
                # The object-level confidence came from multi-view agreement and
                # is about EXISTENCE. Its class is a much weaker claim, so the
                # combined confidence must not exceed what the prior can support.
                conf = min(conf, prior_conf)

        if not (0.05 <= min(w, h, d) and max(w, h, d) <= 4.0):
            rejected.append({**obj, "reason": f"implausible size {w:.2f}x{h:.2f}x{d:.2f}"})
            continue
        # Re-classify AFTER the floor extension below would change the height?
        # No: the classifier reads horizontal extents far more than height, and
        # deferring it would mean re-deriving the label from a height the
        # detector never measured. Guessed labels stay based on what was seen.

        pos = list(obj["position"])
        if not _in_bounds(pos, bmin, bmax):
            rejected.append({**obj, "reason": f"centre outside room bounds {pos}"})
            continue

        # ── the floor snap ──
        # Two things go wrong with heights, and they need different fixes.
        #
        # 1. Detections drift vertically, so a box sits a few centimetres above
        #    or below the floor. Translating it down fixes that.
        # 2. Segmentation deliberately cuts everything below floor + 8 cm, so
        #    the observed bottom of every floor-standing object is 8 cm too
        #    high and the object is 8 cm SHORT. Translating cannot fix that --
        #    it just moves the error to the top, making a 0.90 m chair a 0.82 m
        #    chair floating correctly at floor level.
        #
        # So: extend the box DOWN to the floor rather than sliding it, whenever
        # its measured bottom is plausibly resting there.
        if label in FLOOR_STANDING:
            y_min = float(obj.get("y_min", pos[1] - h / 2))
            gap = y_min - floor_y
            if -0.05 <= gap <= 0.20:
                top = pos[1] + h / 2
                h = top - floor_y
                pos[1] = floor_y + h / 2
            else:
                # Too far off the floor to be a measurement artefact -- either
                # it is genuinely mounted (a wall shelf) or the detection is
                # wrong. Translate, do not stretch.
                pos[1] = floor_y + h / 2

        surface = float(pos[1] + h / 2)
        final_conf = round(min(0.99, conf), 3)
        attributes: dict = {
            "class": label,
            "votes": int(obj.get("votes", 1)),
            "detector": detector,
            "label_source": label_source,
            "uncertain": bool(final_conf < LOW_CONFIDENCE),
        }
        if label_conf is not None:
            attributes["label_confidence"] = round(float(label_conf), 3)
        if obj.get("label_agreement") is not None:
            attributes["label_agreement"] = obj["label_agreement"]

        obj_out = {
            "id": obj["id"],
            "label": label,
            "position": [round(v, 4) for v in pos],
            "dimensions": [round(w, 4), round(h, 4), round(d, 4)],
            "rotation_y": round(float(obj.get("rotation_y", 0.0)), 4),
            "confidence": final_conf,
            "is_obstacle": bool(h > OBSTACLE_MIN_HEIGHT_M),
            "is_climbable": bool(label in CLIMBABLE_LABELS
                                 and surface < CLIMBABLE_MAX_HEIGHT_M),
            "source": "detected",
            "attributes": attributes,
        }
        if obj.get("color"):
            obj_out["color"] = obj["color"]
            # Name the measured swatch so "the red chair" has something exact to
            # match. Absent when nothing was measured - a colour we did not see
            # is not a colour we may claim.
            if (named := colors.name_hex(obj["color"])) is not None:
                attributes["color"] = named.as_dict()
        # surface_height is only meaningful for things you can put objects ON.
        # Setting it on a lamp would let the placer balance a mug on a lampshade.
        if obj_out["is_climbable"]:
            obj_out["surface_height"] = round(surface, 4)

        kept.append(obj_out)

    return _reassign_ids(kept), rejected


def _reassign_ids(objects: list[dict]) -> list[dict]:
    """Re-number after post-processing.

    S08 assigned ids before the size classifier renamed 'object' to 'chair' and
    before the gates dropped anything, so the numbering has holes and the wrong
    stems. Ids are part of the frozen contract and are quoted verbatim by ARIA,
    so they get rebuilt from the final list.

    Same total ordering as `s08_lift3d.assign_ids`, and for the same reason:
    ten chairs of near-identical confidence must not swap numbers between two
    runs over the same capture, because "go to chair number 3" resolves through
    that number. Confidence is rounded before comparison and ties fall back to
    position, so the ordering tracks the furniture rather than float noise.
    """
    counters: dict[str, int] = {}
    out = []

    def order(o: dict):
        return (-round(float(o["confidence"]), 3),
                round(float(o["position"][2]), 3),
                round(float(o["position"][0]), 3))

    for obj in sorted(objects, key=order):
        label = obj["label"]
        counters[label] = counters.get(label, 0) + 1
        index = counters[label]
        attrs = {**obj.get("attributes", {}), "instance_index": index}
        out.append({**obj, "id": f"{label}_{index:02d}", "attributes": attrs})
    return out


def build(room_id: str, objects: list[dict], floor: dict, mesh_info: dict,
          scan_meta: dict, name: str | None = None) -> dict:
    grid = floor["grid"]

    # The relation layer, baked once here rather than recomputed per query.
    # "The chair near the table" is a geometry question with an exact answer,
    # and answering it at write time means the resolver is a filter over facts
    # instead of an estimator. `attach_relations` also writes each object's own
    # outgoing relations into its attributes, so the companion prompt and the
    # frontend can read them without indexing anything.
    spatial.assign_size_classes(objects)
    relations = spatial.attach_relations(objects)

    return {
        "room_id": room_id,
        "version": "1.0",
        "name": name or room_id.replace("_", " ").title(),
        "units": "meters",
        "up_axis": "Y",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "bounds": {"min": [round(v, 4) for v in floor["bounds_min"]],
                   "max": [round(v, 4) for v in floor["bounds_max"]]},
        "floor_y": round(float(floor["floor_y"]), 4),
        "mesh": {
            "url": mesh_info.get("url", f"/api/v1/rooms/{room_id}/mesh"),
            "format": "glb",
            "draco": bool(mesh_info.get("draco", False)),
            "tri_count": int(mesh_info.get("tri_count", 0)),
            "size_bytes": int(mesh_info.get("size_bytes", 0)),
        },
        "navmesh": {
            "url": mesh_info.get("navmesh_url", f"/api/v1/rooms/{room_id}/navmesh"),
            "resolution": grid["resolution"],
            "origin": grid["origin"],
            "width": grid["width"],
            "height": grid["height"],
        },
        "robot_dock": [round(v, 4) for v in floor["robot_dock"]],
        "objects": objects,
        "relations": [r.as_dict() for r in relations],
        "waypoints": [],
        "scan": scan_meta,
    }


def validate(graph: dict, schema_path: Path) -> list[str]:
    """Validate against the frozen schema. Returns a list of error strings."""
    import jsonschema

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
              for e in validator.iter_errors(graph)]

    # Belt and braces on the id pattern: it is the one field other subsystems
    # parse rather than just read, and a bad id fails much later and less
    # legibly (in the RAG index, or in a chat citation).
    for obj in graph.get("objects", []):
        if not ID_PATTERN.match(obj.get("id", "")):
            errors.append(f"object id '{obj.get('id')}' violates ^[a-z_]+_[0-9]{{2}}$")
    return errors


def run(room_id: str, out_dir: Path, objects: list[dict], floor: dict,
        mesh_info: dict, scan_meta: dict, schema_path: Path,
        detector: str, name: str | None = None, progress=None) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    kept, rejected = post_process(objects, floor["floor_y"],
                                  floor["bounds_min"], floor["bounds_max"],
                                  detector)
    for r in rejected:
        log.info("rejected %s: %s", r.get("id"), r["reason"])

    graph = build(room_id, kept, floor, mesh_info,
                  {**scan_meta, "rejected_objects": len(rejected)}, name)

    errors = validate(graph, schema_path)
    if errors:
        raise ValueError("room.json failed schema validation:\n  "
                         + "\n  ".join(errors))

    (out_dir / "room.json").write_text(json.dumps(graph, indent=2),
                                       encoding="utf-8")
    np.save(out_dir / "navmesh.npy", floor["grid"]["grid"])

    if progress:
        progress.stage("scenegraph", 1.0,
                       f"{len(kept)} objects ({len(rejected)} rejected)")
    return {"graph": graph, "kept": len(kept), "rejected": rejected}
