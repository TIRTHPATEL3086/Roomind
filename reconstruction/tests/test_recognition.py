"""Recognition and instance identity (Phase 6).

The fusion detector has two halves that fail differently, so they are tested
separately:

  * `vote_labels` decides WHAT each object is, from YOLO boxes. Tested with
    hand-written boxes and no ultralytics, no weights and no GPU — the voting
    arithmetic is what breaks, not the network.
  * S08/S10 decide WHICH object is which, and give it a stable id. Tested for
    the property that actually matters downstream: the same room processed
    twice must produce the same ids, because "chair number 3" resolves through
    that number and ARIA quotes the id out loud.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steps.s07_detect import (  # noqa: E402
    MIN_LABEL_OVERLAP,
    COCO_KEEP,
    UNSUPPORTED_BY_COCO,
    supported_classes,
    vote_labels,
)
from steps.s08_lift3d import assign_ids, sanitise_label  # noqa: E402
from steps.s10_scenegraph import classify_by_size, post_process  # noqa: E402
from utils.shared import colors, spatial  # noqa: E402


def det(frame: int, cluster: int, x: int, y: int, w: int, h: int) -> dict:
    """A geometric detection: a box plus the mask of pixels that are really it."""
    return {"frame_idx": frame, "cluster": cluster,
            "bbox": [x, y, x + w, y + h],
            "mask": np.ones((h, w), dtype=bool)}


def box(label: str, conf: float, x1, y1, x2, y2) -> dict:
    return {"label": label, "conf": conf, "bbox": [x1, y1, x2, y2]}


# ── label voting ──

def test_a_class_is_voted_onto_a_cluster() -> None:
    dets = [det(f, 0, 100, 100, 60, 120) for f in range(5)]
    yolo = {f: [box("chair", 0.85, 98, 98, 162, 222)] for f in range(5)}

    verdict = vote_labels(dets, yolo)[0]
    assert verdict["label"] == "chair"
    assert verdict["label_source"] == "yolo"
    assert verdict["label_votes"] == 5


def test_an_enclosing_box_cannot_steal_the_object_inside_it() -> None:
    """A 'dining table' box legally contains every chair tucked under it.
    Coverage alone would let one table detection relabel six chairs; the
    containment penalty is what stops it."""
    chairs = [det(f, 0, 100, 100, 60, 120) for f in range(6)]
    tables = [det(f, 1, 60, 180, 300, 90) for f in range(6)]
    yolo = {f: [box("chair", 0.85, 95, 95, 165, 225),
                box("table", 0.90, 50, 90, 380, 280)] for f in range(6)}

    verdicts = vote_labels(chairs + tables, yolo)
    assert verdicts[0]["label"] == "chair"
    assert verdicts[1]["label"] == "table"


def test_a_confident_majority_survives_one_disagreeing_frame() -> None:
    dets = [det(f, 0, 100, 100, 60, 120) for f in range(6)]
    yolo = {f: [box("chair", 0.80, 98, 98, 162, 222)] for f in range(5)}
    yolo[5] = [box("bench", 0.70, 98, 98, 162, 222)]

    verdict = vote_labels(dets, yolo)[0]
    assert verdict["label"] == "chair"
    assert verdict["runner_up"] == "bench"
    # a contested vote is a weaker claim than a unanimous one
    assert verdict["label_confidence"] < 0.80


def test_a_box_that_barely_clips_the_mask_does_not_vote() -> None:
    dets = [det(f, 0, 100, 100, 60, 120) for f in range(6)]
    # overlaps the top ~17% of the mask, well under MIN_LABEL_OVERLAP
    yolo = {f: [box("bed", 0.95, 60, 60, 300, 120)] for f in range(6)}

    assert MIN_LABEL_OVERLAP > 0.2
    assert vote_labels(dets, yolo) == {}


def test_no_yolo_boxes_means_no_verdict_not_a_guess() -> None:
    """Silence is not a class. An unrecognised cluster must fall through to the
    size prior with `label_source` saying so, never inherit a nearby label."""
    dets = [det(f, 0, 100, 100, 60, 120) for f in range(6)]
    assert vote_labels(dets, {}) == {}


def test_one_marginal_sighting_is_not_recognition() -> None:
    dets = [det(0, 0, 100, 100, 60, 120)]
    yolo = {0: [box("chair", 0.36, 98, 98, 162, 222)]}
    assert vote_labels(dets, yolo) == {}


# ── honest reporting of what is supported ──

def test_classes_coco_cannot_see_are_declared_unsupported() -> None:
    for label in ("lamp", "shelf", "door", "window", "cabinet"):
        assert label in UNSUPPORTED_BY_COCO
        assert label not in COCO_KEEP.values(), (
            f"{label} is listed as recognisable but COCO has no such class")


def test_supported_classes_reports_the_gap() -> None:
    info = supported_classes(weights=None)
    assert "chair" in info["recognised"]
    assert "lamp" in info["size_prior_only"]
    assert info["trained_for_furniture"] is False


# ── instance identity ──

def _merged(label, conf, x, z, dims=(0.52, 0.90, 0.54)):
    return {"label": label, "confidence": conf,
            "position": [x, dims[1] / 2, z], "dimensions": list(dims),
            "rotation_y": 0.0, "y_min": 0.0, "votes": 5}


def test_several_instances_of_one_class_stay_separate() -> None:
    ids = [o["id"] for o in assign_ids([
        _merged("chair", 0.91, -2.1, -0.35),
        _merged("chair", 0.91, -0.3, -1.20),
        _merged("chair", 0.91, 2.1, 0.60),
    ])]
    assert ids == ["chair_01", "chair_02", "chair_03"]
    assert len(set(ids)) == 3


def test_ids_do_not_reshuffle_when_confidences_wobble() -> None:
    """Ten identical chairs land within thousandths of each other, so float
    noise upstream would otherwise renumber the room between two runs over the
    same capture — and chair_03 would stop meaning the same chair."""
    base = [_merged("chair", 0.9100, -2.1, -0.35),
            _merged("chair", 0.9100, -0.3, -1.20),
            _merged("chair", 0.9100, 2.1, 0.60)]
    jittered = [_merged("chair", 0.9101, -2.1, -0.35),
                _merged("chair", 0.9099, -0.3, -1.20),
                _merged("chair", 0.9100, 2.1, 0.60)]

    by_pos = lambda objs: {  # noqa: E731
        (round(o["position"][0], 2), round(o["position"][2], 2)): o["id"]
        for o in objs}
    assert by_pos(assign_ids(base)) == by_pos(assign_ids(jittered))


def test_instance_index_matches_the_id() -> None:
    for obj in assign_ids([_merged("chair", 0.9, 0, 0),
                           _merged("chair", 0.8, 1, 1)]):
        assert obj["instance_index"] == int(obj["id"].rsplit("_", 1)[1])


def test_labels_are_sanitised_to_the_frozen_id_pattern() -> None:
    """COCO says 'dining table' and 'potted plant'; a space in an id fails
    schema validation at the very last step of a three-minute pipeline."""
    assert sanitise_label("Dining Table") == "dining_table"
    assert sanitise_label("potted plant") == "potted_plant"
    assert sanitise_label("!!!") == "object"


# ── post-processing keeps the two claims apart ──

def test_an_unrecognised_object_is_labelled_by_size_and_says_so() -> None:
    kept, _ = post_process(
        [{**_merged("object", 0.85, 0.0, 0.0), "id": "object_01"}],
        floor_y=0.0, bmin=[-3, 0, -3], bmax=[3, 3, 3], detector="fusion")
    assert kept[0]["label"] == "chair"
    assert kept[0]["attributes"]["label_source"] == "size_prior"
    # a size prior is a weaker claim than recognition, and the number must say so
    assert kept[0]["confidence"] <= 0.55


def test_a_recognised_object_keeps_its_detector_provenance() -> None:
    obj = {**_merged("chair", 0.88, 0.0, 0.0), "id": "chair_01",
           "label_source": "yolo", "label_confidence": 0.88}
    kept, _ = post_process([obj], floor_y=0.0, bmin=[-3, 0, -3],
                           bmax=[3, 3, 3], detector="fusion")
    assert kept[0]["attributes"]["label_source"] == "yolo"
    assert kept[0]["attributes"]["label_confidence"] == 0.88


def test_a_measured_colour_becomes_a_name_the_resolver_can_match() -> None:
    obj = {**_merged("chair", 0.9, 0.0, 0.0), "id": "chair_01",
           "color": "#B81E1E", "label_source": "yolo", "label_confidence": 0.9}
    kept, _ = post_process([obj], floor_y=0.0, bmin=[-3, 0, -3],
                           bmax=[3, 3, 3], detector="fusion")
    assert kept[0]["attributes"]["color"]["value"] == "red"


def test_an_object_with_no_measured_colour_gets_no_colour_attribute() -> None:
    """Absence of a measurement and an unnameable measurement are different
    states, and only the first means 'nothing told us'."""
    obj = {**_merged("chair", 0.9, 0.0, 0.0), "id": "chair_01"}
    kept, _ = post_process([obj], floor_y=0.0, bmin=[-3, 0, -3],
                           bmax=[3, 3, 3], detector="fusion")
    assert "color" not in kept[0]["attributes"]


def test_low_confidence_objects_are_flagged_uncertain() -> None:
    obj = {**_merged("chair", 0.30, 0.0, 0.0), "id": "chair_01",
           "label_source": "yolo", "label_confidence": 0.30}
    kept, _ = post_process([obj], floor_y=0.0, bmin=[-3, 0, -3],
                           bmax=[3, 3, 3], detector="fusion")
    assert kept[0]["attributes"]["uncertain"] is True


# ── the shipped multi-instance room ──

MULTI = ROOT.parent / "contracts" / "demo_room_multi.json"


@pytest.mark.skipif(not MULTI.exists(), reason="multi-instance fixture not built")
def test_the_shipped_room_really_holds_several_of_each_class() -> None:
    graph = json.loads(MULTI.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for obj in graph["objects"]:
        counts[obj["label"]] = counts.get(obj["label"], 0) + 1

    assert counts["chair"] == 3
    assert counts["table"] == 2
    assert counts["tv"] == 2
    assert counts["bed"] == 1
    # and the three chairs are genuinely distinguishable by colour
    chair_colours = {
        o["attributes"]["color"]["value"]
        for o in graph["objects"] if o["label"] == "chair"}
    assert len(chair_colours) == 3, f"chairs are not separable by colour: {chair_colours}"


@pytest.mark.skipif(not MULTI.exists(), reason="multi-instance fixture not built")
def test_the_shipped_room_came_out_of_the_pipeline() -> None:
    """Not hand-authored. If this fixture is ever edited by hand the scan
    provenance goes with it, and the demo stops proving anything."""
    graph = json.loads(MULTI.read_text(encoding="utf-8"))
    assert graph["scan"]["detector"] == "fusion"
    assert graph["scan"]["frames_used"] >= 8
    assert all(o["source"] == "detected" for o in graph["objects"])


@pytest.mark.skipif(not MULTI.exists(), reason="multi-instance fixture not built")
def test_the_relation_layer_separates_the_chairs() -> None:
    """Colour is not the only handle: each chair sits beside a different
    landmark, which is what makes 'the chair near the bed' resolvable."""
    graph = json.loads(MULTI.read_text(encoding="utf-8"))
    by_id = {o["id"]: o for o in graph["objects"]}

    near = {
        cid: {r["to"].rsplit("_", 1)[0]
              for r in by_id[cid]["attributes"].get("relations", [])
              if r["rel"] == "near"}
        for cid in ("chair_01", "chair_02", "chair_03")
    }
    assert any("bed" in v for v in near.values())
    assert any("table" in v for v in near.values())


def test_relations_are_measured_between_surfaces_not_centres() -> None:
    """Two sofas whose centres are 2 m apart can be touching."""
    a = {"id": "sofa_01", "position": [0, 0.4, 0], "dimensions": [1.9, 0.8, 0.85],
         "rotation_y": 0.0}
    b = {"id": "sofa_02", "position": [2.0, 0.4, 0], "dimensions": [1.9, 0.8, 0.85],
         "rotation_y": 0.0}
    assert spatial.centre_distance(a, b) == pytest.approx(2.0)
    assert spatial.surface_gap(a, b) == pytest.approx(0.1, abs=1e-6)


def test_shared_colour_vocabulary_is_the_same_on_both_sides() -> None:
    """The pipeline writes the name and the resolver matches on it; two copies
    of this table would drift, and the drift would show up as ARIA walking to
    the wrong chair rather than as a failing import."""
    assert colors.name_hex("#B81E1E").value == "red"
    assert colors.matches("red", colors.name_hex("#B81E1E").as_dict())
