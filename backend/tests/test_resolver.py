"""Target resolution tests — which physical object did the user mean?

These run against a HAND-BUILT room, deliberately, and never touch YOLO, torch,
or the reconstruction pipeline. The two halves of this feature fail
independently: recognition can be perfect while selection picks the wrong
chair, and selection can be flawless over labels a detector got wrong. Testing
selection against a fixed room is the only way to know which half broke.

The room is the one the brief describes: three chairs of different colours, two
tables, two TVs, a bed and a sofa, with the chairs deliberately parked beside
DIFFERENT landmarks so a spatial constraint actually separates them.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.core.enrich import enrich_graph
from app.core.query_parse import parse_target
from app.services.resolver_service import ResolverService

ROOT = pathlib.Path(__file__).resolve().parents[2]

ROOM_ID = "test_room"


def _obj(oid, label, pos, dims, color=None, rot=0.0, conf=0.9):
    return {
        "id": oid, "label": label, "position": list(pos),
        "dimensions": list(dims), "rotation_y": rot, "confidence": conf,
        "is_obstacle": True, "source": "detected",
        **({"color": color} if color else {}),
    }


@pytest.fixture
def room() -> dict:
    """Three chairs by three different landmarks, two tables, two TVs."""
    graph = {
        "room_id": ROOM_ID, "version": "1.0", "units": "meters", "up_axis": "Y",
        "bounds": {"min": [-3.25, 0.0, -2.5], "max": [3.25, 2.6, 2.5]},
        "floor_y": 0.0, "robot_dock": [-2.9, 0.0, -2.1],
        "objects": [
            _obj("chair_01", "chair", (-2.10, 0.45, -0.35), (0.52, 0.90, 0.54), "#B81E1E"),
            _obj("chair_02", "chair", (-0.30, 0.45, -1.20), (0.52, 0.90, 0.54), "#161618"),
            _obj("chair_03", "chair", (2.10, 0.45, 0.60), (0.52, 0.90, 0.54), "#214BAE"),
            _obj("table_01", "table", (-2.10, 0.37, 0.70), (1.40, 0.74, 0.85), "#8A5F38"),
            _obj("table_02", "table", (2.10, 0.37, 1.60), (1.05, 0.74, 0.70), "#805734"),
            _obj("tv_01", "tv", (-1.20, 1.05, -2.30), (1.10, 0.64, 0.12), "#121216"),
            _obj("tv_02", "tv", (3.05, 1.05, 1.55), (0.10, 0.56, 0.95), "#141419"),
            _obj("bed_01", "bed", (1.40, 0.28, -1.60), (1.95, 0.56, 1.45), "#C7BEAA"),
            _obj("sofa_01", "sofa", (-2.10, 0.40, 1.90), (1.90, 0.80, 0.85), "#406B52"),
        ],
    }
    return enrich_graph(graph)


@pytest.fixture
def resolver() -> ResolverService:
    # A fresh instance per test: the pending-clarification slot is per-room
    # state, and one test's unanswered question must not become the next
    # test's context.
    return ResolverService()


def resolve(resolver, room, text, **kw):
    return resolver.resolve(room, text, room_id=ROOM_ID, **kw)


# ── 1. one of a kind ──

def test_one_of_a_kind_resolves_without_asking(resolver, room) -> None:
    r = resolve(resolver, room, "go to the bed")
    assert r.status == "resolved"
    assert r.object_id == "bed_01"


def test_the_sofa_resolves_by_synonym(resolver, room) -> None:
    """Users say 'couch', the detector says 'sofa'."""
    assert resolve(resolver, room, "go to the couch").object_id == "sofa_01"


# ── 2. several of a kind: ask, never guess ──

def test_three_chairs_and_no_discriminator_asks(resolver, room) -> None:
    r = resolve(resolver, room, "Go to the chair.")
    assert r.status == "clarify"
    assert r.object_id is None, "picked a chair instead of asking"
    assert len(r.options) == 3
    assert "3 chairs" in r.question


def test_the_question_offers_a_usable_way_to_answer(resolver, room) -> None:
    """'chair_01, chair_02 or chair_03' is unambiguous and useless out loud."""
    r = resolve(resolver, room, "go to the chair")
    hints = [o["hint"] for o in r.options]
    assert hints == ["the red one", "the black one", "the blue one"]


def test_two_tvs_also_ask(resolver, room) -> None:
    r = resolve(resolver, room, "go to the tv")
    assert r.status == "clarify"
    assert {o["id"] for o in r.options} == {"tv_01", "tv_02"}


# ── 3. colour ──

@pytest.mark.parametrize("colour,expected", [
    ("red", "chair_01"),
    ("black", "chair_02"),
    ("blue", "chair_03"),
])
def test_colour_selects_the_right_instance(resolver, room, colour, expected) -> None:
    r = resolve(resolver, room, f"Go to the {colour} chair.")
    assert r.status == "resolved"
    assert r.object_id == expected


def test_a_colour_no_chair_has_is_reported_not_guessed(resolver, room) -> None:
    r = resolve(resolver, room, "go to the purple chair")
    assert r.status == "not_found"
    assert r.object_id is None
    # and it says what IS there, so the user can correct themselves
    assert "black" in r.message and "blue" in r.message and "red" in r.message


# ── 4. instance number ──

def test_chair_number_two(resolver, room) -> None:
    assert resolve(resolver, room, "Go to chair number 2.").object_id == "chair_02"


def test_the_second_chair(resolver, room) -> None:
    assert resolve(resolver, room, "go to the second chair").object_id == "chair_02"


def test_a_number_that_does_not_exist_is_refused(resolver, room) -> None:
    r = resolve(resolver, room, "go to chair number 9")
    assert r.status == "not_found"
    assert "chair_01" in r.message


def test_an_explicit_id_short_circuits(resolver, room) -> None:
    assert resolve(resolver, room, "go to chair_03").object_id == "chair_03"


def test_an_explicit_id_that_does_not_exist_is_refused(resolver, room) -> None:
    assert resolve(resolver, room, "go to chair_77").status == "not_found"


# ── 5. spatial relations ──

def test_chair_near_the_bed(resolver, room) -> None:
    r = resolve(resolver, room, "Go to the chair near the bed.")
    assert r.status == "resolved"
    assert r.object_id == "chair_02"


def test_tv_near_the_table(resolver, room) -> None:
    r = resolve(resolver, room, "go to the tv near the table")
    assert r.status == "resolved"
    assert r.object_id == "tv_02"


def test_table_near_the_sofa(resolver, room) -> None:
    assert resolve(resolver, room, "move to the table near the sofa").object_id == "table_01"


def test_a_relation_to_a_class_that_is_not_here(resolver, room) -> None:
    r = resolve(resolver, room, "go to the chair near the fridge")
    assert r.status == "not_found"
    assert "fridge" in r.message


def test_a_relation_that_matches_nothing_is_refused(resolver, room) -> None:
    """There is no chair near a TV in this room, and inventing one is worse
    than saying so."""
    r = resolve(resolver, room, "go to the chair near the sofa")
    assert r.status == "not_found"


def test_a_relation_that_still_leaves_two_asks_again(resolver, room) -> None:
    """Two chairs sit near a table — a different table each. Narrowing that
    far is progress, not an answer."""
    r = resolve(resolver, room, "go to the chair near the table")
    assert r.status == "clarify"
    assert {o["id"] for o in r.options} == {"chair_01", "chair_03"}


# ── 6. size ──

def test_size_separates_two_tables(resolver, room) -> None:
    assert resolve(resolver, room, "go to the big table").object_id == "table_01"
    assert resolve(resolver, room, "go to the small table").object_id == "table_02"


# ── 7. viewpoint ──

def test_left_and_right_use_the_robots_own_frame(resolver, room) -> None:
    """Yaw 0 faces +Z and +X is the robot's right (spec 8.1), which is a
    LEFT-handed rotation about Y and the opposite of the textbook convention."""
    viewer = {"known": True, "x": 0.0, "z": 0.0, "yaw": 0.0}
    left = resolve(resolver, room, "go to the chair on the left", viewer=viewer)
    right = resolve(resolver, room, "go to the chair on the right", viewer=viewer)
    assert left.object_id == "chair_01", "left should be the most negative X"
    assert right.object_id == "chair_03"
    assert left.frame == "robot"


def test_without_telemetry_it_falls_back_to_the_room_frame_and_says_so(
    resolver, room,
) -> None:
    """An unknown pose is not a pose of (0,0,0) — pretending otherwise answers
    a question about the robot's left using a direction she is not facing."""
    r = resolve(resolver, room, "go to the chair on the left",
                viewer={"known": False, "x": 0.0, "z": 0.0, "yaw": 0.0})
    assert r.frame == "room"


def test_facing_the_other_way_swaps_left_and_right(resolver, room) -> None:
    import math

    viewer = {"known": True, "x": 0.0, "z": 0.0, "yaw": math.pi}
    r = resolve(resolver, room, "go to the chair on the left", viewer=viewer)
    assert r.object_id == "chair_03", "turning around must swap left and right"


def test_nearest_picks_rather_than_asks(resolver, room) -> None:
    """A query that ASKS for a ranking is an instruction to choose."""
    viewer = {"known": True, "x": -2.0, "z": -1.0, "yaw": 0.0}
    r = resolve(resolver, room, "go to the nearest chair", viewer=viewer)
    assert r.status == "resolved"
    assert r.object_id == "chair_01"


# ── 8. clarification round trip ──

def test_a_reply_answers_the_open_question(resolver, room) -> None:
    first = resolve(resolver, room, "go to the chair")
    assert first.status == "clarify"

    second = resolve(resolver, room, "the red one")
    assert second.status == "resolved"
    assert second.object_id == "chair_01"


def test_a_reply_may_be_a_bare_number(resolver, room) -> None:
    resolve(resolver, room, "go to the chair")
    assert resolve(resolver, room, "number 3").object_id == "chair_03"


def test_a_reply_may_be_a_relation(resolver, room) -> None:
    resolve(resolver, room, "go to the chair")
    assert resolve(resolver, room, "the one near the bed").object_id == "chair_02"


def test_a_new_command_abandons_the_old_question(resolver, room) -> None:
    """'Actually, go to the sofa' must not be answered with a chair."""
    resolve(resolver, room, "go to the chair")
    r = resolve(resolver, room, "actually go to the sofa")
    assert r.object_id == "sofa_01"


def test_the_pending_question_carries_the_action(resolver, room) -> None:
    resolve(resolver, room, "point at the chair", action="point_at")
    assert resolver.pending_action(ROOM_ID) == "point_at"


def test_a_lookup_does_not_arm_a_clarification(resolver, room) -> None:
    """Speculative resolution must not leave a question open behind it, or the
    NEXT sentence gets read as a reply to something nobody asked."""
    resolve(resolver, room, "go to the chair", remember=False)
    assert not resolver.has_pending(ROOM_ID)


# ── 9. missing and uncertain ──

def test_a_class_the_room_does_not_have(resolver, room) -> None:
    r = resolve(resolver, room, "go to the fridge")
    assert r.status == "not_found"
    assert "chair" in r.message, "should list what IS in the room"


def test_no_object_named_at_all(resolver, room) -> None:
    assert resolve(resolver, room, "go over there").status == "not_found"


def test_a_low_confidence_detection_asks_before_moving(resolver, room) -> None:
    """Below the threshold the object stays on the map — the navmesh still has
    to avoid it — but acting on it means trusting a detection the pipeline
    itself flagged."""
    room["objects"].append(
        _obj("fridge_01", "fridge", (2.9, 0.85, -1.0), (0.6, 1.7, 0.6),
             "#9AA0A6", conf=0.31))
    enrich_graph(room)

    r = resolve(resolver, room, "go to the fridge")
    assert r.status == "confirm"
    assert r.object_id == "fridge_01"
    assert "31%" in r.question


def test_an_empty_room_says_it_has_not_been_scanned(resolver) -> None:
    graph = enrich_graph({
        "room_id": ROOM_ID, "version": "1.0", "units": "meters",
        "bounds": {"min": [-2, 0, -2], "max": [2, 2.5, 2]},
        "floor_y": 0.0, "robot_dock": [0, 0, 0], "objects": [],
    })
    r = resolve(resolver, graph, "go to the chair")
    assert r.status == "not_found"
    assert "scanned" in r.message


# ── 10. id stability ──

def test_ids_are_stable_across_repeated_enrichment(room) -> None:
    """Enriching a graph must never renumber it. The id is user-visible — ARIA
    quotes it, and 'chair number 3' resolves through it — so a reshuffle
    silently changes which physical chair a remembered id refers to."""
    before = [o["id"] for o in room["objects"]]
    for _ in range(3):
        enrich_graph(room)
    assert [o["id"] for o in room["objects"]] == before


def test_instance_index_is_derived_from_the_id(room) -> None:
    for obj in room["objects"]:
        expected = int(obj["id"].rsplit("_", 1)[1])
        assert obj["attributes"]["instance_index"] == expected


# ── 11. the parser, independently of any room ──

@pytest.mark.parametrize("text,cls,colours,ordinal,ego", [
    ("Go to the chair.", "chair", [], None, None),
    ("Go to the red chair.", "chair", ["red"], None, None),
    ("Go to the black chair near the table.", "chair", ["black"], None, None),
    ("Go to the chair on the left.", "chair", [], None, "left"),
    ("Go to chair number 3.", "chair", [], 3, None),
    ("Go near the TV.", "tv", [], None, None),
    ("Move to the table near the sofa.", "table", [], None, None),
    ("the red one", None, ["red"], None, None),
])
def test_parses_the_brief_examples(text, cls, colours, ordinal, ego) -> None:
    q = parse_target(text)
    assert q.object_class == cls
    assert q.colors == colours
    assert q.ordinal == ordinal
    assert q.egocentric == ego


def test_a_landmark_is_not_mistaken_for_the_target() -> None:
    """'the chair near the table' has two nouns, and picking the wrong one
    sends ARIA to the table."""
    q = parse_target("go to the chair near the table")
    assert q.object_class == "chair"
    assert [(r.rel, r.other_class) for r in q.relations] == [("near", "table")]


def test_go_near_the_tv_is_a_target_not_a_landmark() -> None:
    """Same 'near' keyword, opposite meaning: here it qualifies how close to
    get to the TV, and there is no second noun for it to relate to."""
    q = parse_target("go near the tv")
    assert q.object_class == "tv"
    assert q.relations == []


def test_a_bare_query_is_recognised_as_undiscriminating() -> None:
    assert parse_target("go to the chair").is_bare
    assert not parse_target("go to the red chair").is_bare


# ── 12. questions do not pick arbitrarily either ──

def test_where_is_it_reports_every_match(room, monkeypatch) -> None:
    """'Where's the chair?' has three answers in this room. Answering with one
    of them and pointing at it is the same coin flip the navigation path
    refuses to make — the user cannot see that a choice was made at all."""
    from app.services.intent_service import intent_service
    from app.services.rag_service import LexicalBackend, RagService

    svc = RagService()
    svc._backend = LexicalBackend()
    svc.index_room(room)
    monkeypatch.setattr("app.services.intent_service.rag_service", svc)

    reply, citations = intent_service.answer("where's the chair?", ROOM_ID)
    assert set(citations) == {"chair_01", "chair_02", "chair_03"}
    assert "3 chairs" in reply
    assert "Which one" in reply


def test_where_is_it_stays_direct_when_there_is_only_one(room, monkeypatch) -> None:
    from app.services.intent_service import intent_service
    from app.services.rag_service import LexicalBackend, RagService

    svc = RagService()
    svc._backend = LexicalBackend()
    svc.index_room(room)
    monkeypatch.setattr("app.services.intent_service.rag_service", svc)

    reply, citations = intent_service.answer("where's the bed?", ROOM_ID)
    assert citations == ["bed_01"]
    assert "pointing at it" in reply
