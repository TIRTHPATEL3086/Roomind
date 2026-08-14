"""Contract gate - run before every commit and in CI.

Checks that:
  1. all three JSON Schemas are themselves valid Draft 2020-12
  2. the demo room fixture validates against the scene graph schema
  3. every object id matches the frozen ^[a-z_]+_[0-9]{2}$ pattern
  4. generate_types.py is up to date (no uncommitted contract drift)

    py -3.11 scripts/check_contracts.py
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
ID_PATTERN = re.compile(r"^[a-z_]+_[0-9]{2}$")

failures: list[str] = []


def check(label: str, fn) -> None:
    try:
        detail = fn()
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    except Exception as e:  # noqa: BLE001
        failures.append(f"{label}: {e}")
        print(f"  FAIL  {label}\n        {e}")


def _schemas_valid() -> str:
    for name in ("scene_graph", "command", "telemetry"):
        s = json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(s)
    return "3 schemas"


def _fixtures() -> list[pathlib.Path]:
    """Every checked-in room. All of them are held to the schema, not just the
    primary one - a second fixture that quietly stopped validating would only
    surface as a 500 the first time someone selected that room."""
    return sorted(CONTRACTS.glob("demo_room*.json"))


def _fixture_valid() -> str:
    schema = json.loads((CONTRACTS / "scene_graph.schema.json").read_text(encoding="utf-8"))
    total = 0
    for path in _fixtures():
        room = json.loads(path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(room, schema)
        except jsonschema.ValidationError as e:
            raise AssertionError(f"{path.name}: {e.message}") from e
        total += len(room["objects"])
    return f"{len(_fixtures())} rooms, {total} objects"


def _ids_match_pattern() -> str:
    total = 0
    for path in _fixtures():
        room = json.loads(path.read_text(encoding="utf-8"))
        bad = [o["id"] for o in room["objects"] if not ID_PATTERN.match(o["id"])]
        if bad:
            raise AssertionError(
                f"{path.name}: ids violate ^[a-z_]+_[0-9]{{2}}$: {bad}")
        total += len(room["objects"])
    return f"{total} ids"


def _types_current() -> str:
    r = subprocess.run(
        [sys.executable, str(CONTRACTS / "generate_types.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "generate_types.py failed")
    if "WROTE" in r.stdout:
        raise AssertionError(
            "generated TS types were stale - they have now been regenerated, re-run this check"
        )
    return "types in sync"


print("contract gate")
check("schemas are valid Draft 2020-12", _schemas_valid)
check("room fixtures validate", _fixture_valid)
check("object ids match frozen pattern", _ids_match_pattern)
check("frontend TS types are in sync", _types_current)

if failures:
    print(f"\n{len(failures)} CHECK(S) FAILED")
    raise SystemExit(1)
print("\nall contract checks passed")
