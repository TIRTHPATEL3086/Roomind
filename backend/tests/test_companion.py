"""Companion tests: retrieval, offline intent, grounding enforcement (spec 14.2).

No API key and no network required — the Claude path is exercised through a
stub client so the tool loop, citation validation, and refusal handling are all
covered without spending a token.
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

from app.services.intent_service import intent_service
from app.services.llm_service import CITATION_RE, LLMService, llm_service
from app.services.rag_service import LexicalBackend, RagService, tokenize

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = json.loads((ROOT / "contracts" / "demo_room.json").read_text(encoding="utf-8"))
ROOM = "demo_room"


@pytest.fixture(autouse=True)
def indexed(monkeypatch):
    """Fresh lexical index per test — deterministic, no Chroma, no downloads."""
    svc = RagService()
    svc._backend = LexicalBackend()
    svc.index_room(DEMO)
    monkeypatch.setattr("app.services.rag_service.rag_service", svc)
    monkeypatch.setattr("app.services.intent_service.rag_service", svc)
    monkeypatch.setattr("app.services.llm_service.rag_service", svc)
    return svc


# ── retrieval ──

def test_tokenizer_maps_synonyms() -> None:
    assert "sofa" in tokenize("where is the couch")
    assert "tv" in tokenize("turn on the television")
    # compound labels also yield their parts, so "plant" finds potted_plant
    assert "plant" in tokenize("the potted_plant")


def test_stopwords_dropped() -> None:
    assert tokenize("how many of the chairs are in this room") == ["chair"]


def test_affordance_query_finds_seating(indexed) -> None:
    """"sit down" shares no token with "sofa" — this only works because of the
    affordance map, and it's the query shape users actually type."""
    hits = indexed.retrieve(ROOM, "where can I sit down comfortably", k=3)
    assert any(o["label"] in ("sofa", "chair") for o in hits)


def test_affordance_query_finds_a_work_surface(indexed) -> None:
    hits = indexed.retrieve(ROOM, "somewhere to eat dinner", k=2)
    assert hits and hits[0]["label"] == "table"


def test_documents_are_not_affordance_expanded(indexed) -> None:
    """Expanding both sides would make every seat match every seating intent
    and flatten the ranking — a direct mention must still outrank an affordance."""
    direct = indexed.retrieve(ROOM, "sofa", k=1)
    assert direct[0]["label"] == "sofa"


def test_retrieve_by_synonym(indexed) -> None:
    hits = indexed.retrieve(ROOM, "the couch", k=2)
    assert hits and hits[0]["label"] == "sofa"


def test_by_label_is_exact_and_complete(indexed) -> None:
    """Counting must not go through fuzzy retrieval — a similarity cutoff
    would silently drop the third chair."""
    chairs = indexed.by_label(ROOM, "chair")
    assert len(chairs) == 2
    assert {c["id"] for c in chairs} == {"chair_01", "chair_02"}


def test_by_label_accepts_user_synonyms(indexed) -> None:
    assert indexed.by_label(ROOM, "couch")[0]["id"] == "sofa_01"


def test_by_label_bridges_spaces_and_underscores(indexed) -> None:
    """Users type "potted plant"; the label is 'potted_plant'. Without this,
    the query falls through to fuzzy retrieval and can return a DIFFERENT
    object — which is how "where's the floor lamp?" found the wrong lamp."""
    assert indexed.by_label(ROOM, "potted plant")[0]["id"] == "potted_plant_01"
    assert indexed.by_label(ROOM, "potted_plant")[0]["id"] == "potted_plant_01"


def test_head_noun_match_counts_a_qualified_label(indexed) -> None:
    """A generated "wooden_chair" must count when the user asks how many
    chairs there are — otherwise adding an object makes it invisible to the
    very question it should change."""
    indexed.index_room({
        **DEMO,
        "objects": DEMO["objects"] + [{
            "id": "wooden_chair_01", "label": "wooden_chair",
            "position": [2.0, 0.45, 0.5], "dimensions": [0.45, 0.90, 0.45],
            "source": "generated", "is_obstacle": True,
        }],
    })
    ids = {o["id"] for o in indexed.by_label(ROOM, "chair")}
    assert ids == {"chair_01", "chair_02", "wooden_chair_01"}


def test_head_noun_match_is_one_directional(indexed) -> None:
    """Asking for a "wooden chair" must NOT return the plain chairs."""
    indexed.index_room({
        **DEMO,
        "objects": DEMO["objects"] + [{
            "id": "wooden_chair_01", "label": "wooden_chair",
            "position": [2.0, 0.45, 0.5], "dimensions": [0.45, 0.90, 0.45],
            "source": "generated", "is_obstacle": True,
        }],
    })
    ids = {o["id"] for o in indexed.by_label(ROOM, "wooden chair")}
    assert ids == {"wooden_chair_01"}


def test_multiword_generated_label_is_findable(indexed) -> None:
    """Generated labels come from a free-text hint and are usually multi-word."""
    indexed.index_room({
        **DEMO,
        "objects": DEMO["objects"] + [{
            "id": "floor_lamp_01", "label": "floor_lamp",
            "position": [1.0, 0.8, 1.0], "dimensions": [0.35, 1.55, 0.35],
            "source": "generated", "is_obstacle": True,
        }],
    })
    hits = indexed.by_label(ROOM, "floor lamp")
    assert [o["id"] for o in hits] == ["floor_lamp_01"]


def test_exists_rejects_invented_ids(indexed) -> None:
    assert indexed.exists(ROOM, "lamp_01")
    assert not indexed.exists(ROOM, "unicorn_99")


# ── offline answers ──

def test_counting_question_is_grounded() -> None:
    reply, cites = intent_service.answer("how many chairs are there?", ROOM)
    assert "Two" in reply
    assert set(cites) == {"chair_01", "chair_02"}
    assert "[chair_01]" in reply and "[chair_02]" in reply


def test_counting_a_thing_that_isnt_there() -> None:
    reply, cites = intent_service.answer("how many pianos are there?", ROOM)
    assert "don't see" in reply.lower()
    assert cites == []


def test_where_question_cites_and_locates() -> None:
    reply, cites = intent_service.answer("where's the lamp?", ROOM)
    assert cites == ["lamp_01"]
    assert "[lamp_01]" in reply


def test_room_summary_lists_real_objects() -> None:
    reply, cites = intent_service.answer("what's in this room?", ROOM)
    assert "9" in reply
    assert len(cites) == 9


def test_non_question_returns_none() -> None:
    assert intent_service.answer("go to the table", ROOM) is None


# ── offline command parsing ──

def test_stop_wins_outright() -> None:
    cmds = intent_service.parse("no wait, stop!", ROOM)
    assert cmds[0]["action"] == "stop"
    assert cmds[0]["priority"] == 10
    assert len(cmds) == 1


def test_two_verbs_keep_sentence_order() -> None:
    cmds = intent_service.parse("go to the table and point at the lamp", ROOM)
    assert [c["action"] for c in cmds] == ["navigate", "point_at"]
    assert cmds[0]["target"] == "table_01"
    assert cmds[1]["target"] == "lamp_01"


def test_synonym_resolves_to_a_real_id() -> None:
    cmds = intent_service.parse("go to the couch", ROOM)
    assert cmds[0]["target"] == "sofa_01"


def test_turn_left_is_negative_degrees() -> None:
    cmds = intent_service.parse("turn left 45 degrees", ROOM)
    assert cmds[0]["params"]["degrees"] == -45


def test_unparseable_input_yields_no_commands() -> None:
    assert intent_service.parse("what a lovely day", ROOM) == []


@pytest.mark.asyncio
async def test_offline_chat_answers_and_cites() -> None:
    out = await llm_service._chat_offline(ROOM, "how many chairs?")
    assert out["engine"] == "offline"
    assert set(out["citations"]) == {"chair_01", "chair_02"}


@pytest.mark.asyncio
async def test_offline_chat_produces_commands() -> None:
    out = await llm_service._chat_offline(ROOM, "point at the lamp")
    assert out["commands"][0]["action"] == "point_at"
    assert out["commands"][0]["target"] == "lamp_01"


# ── grounding enforcement (this is the load-bearing rule) ──

def test_invented_citations_are_stripped(indexed) -> None:
    svc = LLMService()
    assert svc._validate(ROOM, ["chair_01", "unicorn_99", "lamp_01"]) == [
        "chair_01", "lamp_01"
    ]


def test_duplicate_citations_collapse(indexed) -> None:
    svc = LLMService()
    assert svc._validate(ROOM, ["lamp_01", "lamp_01"]) == ["lamp_01"]


def test_invented_ids_removed_from_reply_text(indexed) -> None:
    """The user must never SEE an invented id, not just not have it in the
    citations array."""
    svc = LLMService()
    out = svc._strip_unknown(ROOM, "I see a chair [chair_01] and a piano [piano_01].")
    assert "[chair_01]" in out
    assert "piano_01" not in out


def test_citation_regex_matches_the_frozen_id_pattern() -> None:
    found = CITATION_RE.findall("[table_01] [potted_plant_02] [nope] [Bad_01]")
    assert found == ["table_01", "potted_plant_02"]


# ── prompt assembly and caching discipline ──

def test_system_prompt_puts_scene_facts_before_the_breakpoint(indexed) -> None:
    blocks = LLMService().build_system(ROOM, "design")
    idx = next(i for i, b in enumerate(blocks) if "cache_control" in b)
    joined = " ".join(b["text"] for b in blocks[: idx + 1])
    assert "lamp_01" in joined, "scene facts must be inside the cached prefix"


def test_mode_line_sits_after_the_breakpoint(indexed) -> None:
    """A mode switch must cost one small re-read, not the whole prompt."""
    blocks = LLMService().build_system(ROOM, "education")
    idx = next(i for i, b in enumerate(blocks) if "cache_control" in b)
    after = " ".join(b["text"] for b in blocks[idx + 1:])
    assert "metres" in after
    before = " ".join(b["text"] for b in blocks[: idx + 1])
    assert "Lean explanatory" not in before


def test_system_prompt_has_no_cache_invalidators(indexed) -> None:
    """A timestamp or uuid above the breakpoint silently kills every cache hit."""
    import re

    text = " ".join(b["text"] for b in LLMService().build_system(ROOM))
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text), "timestamp in prompt"
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text), "uuid in prompt"


def test_exactly_one_cache_breakpoint(indexed) -> None:
    blocks = LLMService().build_system(ROOM)
    assert sum("cache_control" in b for b in blocks) == 1


def test_two_builds_are_byte_identical(indexed) -> None:
    """Non-determinism here means the cache never hits."""
    a = LLMService().build_system(ROOM, "design")
    b = LLMService().build_system(ROOM, "design")
    assert a == b


# ── Claude path, via a stub client ──

def _block(**kw):
    return SimpleNamespace(**kw)


class StubClient:
    """Minimal stand-in for anthropic.Anthropic — records requests, replays
    scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        return self._responses.pop(0)


def _resp(content, stop_reason="end_turn", **extra):
    return SimpleNamespace(
        content=content, stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_creation_input_tokens=0,
                              cache_read_input_tokens=100),
        **extra,
    )


@pytest.mark.asyncio
async def test_claude_path_strips_invented_ids(indexed, monkeypatch) -> None:
    svc = LLMService()
    stub = StubClient([_resp([
        _block(type="text", text="Two chairs [chair_01] and a piano [piano_01].")
    ])])
    monkeypatch.setattr(svc, "_get_client", lambda: stub)

    out = await svc._chat_claude(ROOM, "how many chairs?", "design")
    assert out["citations"] == ["chair_01"]
    assert "piano_01" not in out["reply"]


@pytest.mark.asyncio
async def test_claude_tool_loop_collects_commands(indexed, monkeypatch) -> None:
    svc = LLMService()
    stub = StubClient([
        _resp([_block(type="tool_use", id="t1", name="issue_command",
                      input={"action": "point_at", "target": "lamp_01"})],
              stop_reason="tool_use"),
        _resp([_block(type="text", text="There it is. [lamp_01]")]),
    ])
    monkeypatch.setattr(svc, "_get_client", lambda: stub)

    out = await svc._chat_claude(ROOM, "where's the lamp?", "design")
    assert out["commands"] == [
        {"action": "point_at", "target": "lamp_01", "params": {}, "priority": 5}
    ]
    assert out["citations"] == ["lamp_01"]


@pytest.mark.asyncio
async def test_tool_rejects_invented_target_before_the_planner(indexed, monkeypatch) -> None:
    """An invented id must be caught at the tool boundary and corrected in the
    same turn, not forwarded to the robot."""
    svc = LLMService()
    stub = StubClient([
        _resp([_block(type="tool_use", id="t1", name="issue_command",
                      input={"action": "point_at", "target": "piano_01"})],
              stop_reason="tool_use"),
        _resp([_block(type="text", text="I don't see a piano.")]),
    ])
    monkeypatch.setattr(svc, "_get_client", lambda: stub)

    out = await svc._chat_claude(ROOM, "point at the piano", "design")
    assert out["commands"] == []
    correction = stub.requests[1]["messages"][-1]["content"][0]["content"]
    assert "no object 'piano_01'" in correction


@pytest.mark.asyncio
async def test_refusal_does_not_index_into_empty_content(indexed, monkeypatch) -> None:
    """A refusal returns HTTP 200 with empty content — reading content[0]
    unconditionally would raise IndexError."""
    svc = LLMService()
    stub = StubClient([_resp([], stop_reason="refusal",
                             stop_details=SimpleNamespace(category="cyber"))])
    monkeypatch.setattr(svc, "_get_client", lambda: stub)

    out = await svc._chat_claude(ROOM, "...", "design")
    assert out["engine"] == "claude:refusal"
    assert out["citations"] == []


@pytest.mark.asyncio
async def test_all_tool_results_return_in_one_message(indexed, monkeypatch) -> None:
    """Splitting parallel tool results across messages trains the model to stop
    making parallel calls."""
    svc = LLMService()
    stub = StubClient([
        _resp([
            _block(type="tool_use", id="t1", name="query_scene", input={"label": "chair"}),
            _block(type="tool_use", id="t2", name="query_scene", input={"label": "table"}),
        ], stop_reason="tool_use"),
        _resp([_block(type="text", text="Done.")]),
    ])
    monkeypatch.setattr(svc, "_get_client", lambda: stub)

    await svc._chat_claude(ROOM, "count things", "design")
    results = stub.requests[1]["messages"][-1]["content"]
    assert len(results) == 2
    assert {r["tool_use_id"] for r in results} == {"t1", "t2"}


@pytest.mark.asyncio
async def test_effort_is_sent_under_output_config(indexed, monkeypatch) -> None:
    """effort is nested in output_config, not top-level — and SDK 0.69.0 needs
    it via extra_body."""
    svc = LLMService()
    stub = StubClient([_resp([_block(type="text", text="ok")])])
    monkeypatch.setattr(svc, "_get_client", lambda: stub)

    await svc._chat_claude(ROOM, "hi", "design")
    req = stub.requests[0]
    assert req["extra_body"]["output_config"]["effort"]
    assert "effort" not in req
    # thinking is omitted deliberately: on claude-opus-5 that runs adaptive
    assert "thinking" not in req


@pytest.mark.asyncio
async def test_query_scene_counts_exactly(indexed, monkeypatch) -> None:
    svc = LLMService()
    out, cmd = svc._run_tool(ROOM, "query_scene", {"label": "chair"})
    assert cmd is None
    # one line per object — counting substrings would double-count, since each
    # line carries the id both as a prefix and inside the description
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert {ln.split(":")[0] for ln in lines} == {"chair_01", "chair_02"}
