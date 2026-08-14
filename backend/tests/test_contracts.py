"""Phase 0 acceptance tests - contracts and architecture discipline.

These need no database, no Docker and no network. They must always pass.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

import jsonschema
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
SCHEMAS = {
    p.stem.replace(".schema", ""): json.loads(p.read_text(encoding="utf-8"))
    for p in CONTRACTS.glob("*.schema.json")
}
ID_PATTERN = re.compile(r"^[a-z_]+_[0-9]{2}$")


@pytest.mark.parametrize("name", ["scene_graph", "command", "telemetry"])
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMAS[name])


def test_demo_room_validates() -> None:
    room = json.loads((CONTRACTS / "demo_room.json").read_text(encoding="utf-8"))
    jsonschema.validate(room, SCHEMAS["scene_graph"])


def test_every_object_id_matches_frozen_pattern() -> None:
    room = json.loads((CONTRACTS / "demo_room.json").read_text(encoding="utf-8"))
    bad = [o["id"] for o in room["objects"] if not ID_PATTERN.match(o["id"])]
    assert not bad, f"ids violate ^[a-z_]+_[0-9]{{2}}$: {bad}"


def test_command_payload_valid() -> None:
    jsonschema.validate({"action": "navigate", "target": "table_01"}, SCHEMAS["command"])


def test_aria_is_the_only_robot_id() -> None:
    """One robot. If this ever grows, it was a deliberate contract change."""
    assert SCHEMAS["command"]["properties"]["robot_id"]["enum"] == ["aria"]


def test_humanoid_actions_present() -> None:
    actions = set(SCHEMAS["command"]["properties"]["action"]["enum"])
    for a in ("look_at", "point_at", "present", "imagine", "nod", "express"):
        assert a in actions, f"missing humanoid action: {a}"


def test_no_quadruped_actions_remain() -> None:
    actions = set(SCHEMAS["command"]["properties"]["action"]["enum"])
    for a in ("jump", "climb", "balance", "crawl_under"):
        assert a not in actions, f"three-robot action survived the rewrite: {a}"


def test_telemetry_carries_joints() -> None:
    """The twin cannot mirror ARIA's limbs without these."""
    joints = SCHEMAS["telemetry"]["properties"]["joints"]["properties"]
    for j in ("head_pan", "head_tilt", "l_elbow", "r_elbow"):
        assert j in joints, f"missing joint in telemetry contract: {j}"


# ── Architecture discipline (spec 1.4.2): downward calls only ──

def _imports_of(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def test_services_never_import_api() -> None:
    """An Orchestration module importing the Presentation layer inverts the
    architecture and makes the services untestable without FastAPI."""
    services = ROOT / "backend" / "app" / "services"
    offenders = [
        f"{p.name} -> {m}"
        for p in services.glob("*.py")
        for m in _imports_of(p)
        if m.startswith("app.api")
    ]
    assert not offenders, f"services/ must not import api/: {offenders}"


def test_core_never_imports_services() -> None:
    core = ROOT / "backend" / "app" / "core"
    offenders = [
        f"{p.name} -> {m}"
        for p in core.glob("*.py")
        for m in _imports_of(p)
        if m.startswith("app.services")
    ]
    assert not offenders, f"core/ must not import services/: {offenders}"
