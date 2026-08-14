#!/usr/bin/env python3
"""Emit TypeScript interfaces from the frozen JSON Schemas in contracts/.

Single source of truth: contracts/*.schema.json  ->  frontend/src/types/*.ts

Idempotent. Fails loudly on an invalid schema. Run it after ANY contract change:
    py -3.11 contracts/generate_types.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
OUT_DIR = ROOT / "frontend" / "src" / "types"

# schema file stem -> (output .ts file, root interface name)
TARGETS = {
    "scene_graph": ("scene.ts", "SceneGraph"),
    "command": ("command.ts", "Command"),
    "telemetry": ("telemetry.ts", "Telemetry"),
}

HEADER = """// AUTO-GENERATED FROM contracts/{src} - DO NOT EDIT BY HAND.
// Regenerate with:  py -3.11 contracts/generate_types.py
"""


# root interface names keep their intended casing; everything else is derived
CASING = {"scenegraph": "SceneGraph", "command": "Command", "telemetry": "Telemetry"}


def ts_name(key: str) -> str:
    """snake_case -> PascalCase, preserving known root casings.

    Uppercases the first character only - never lowercases the tail, or an
    already-PascalCase parent prefix (TelemetrySensors) would be flattened
    to Telemetrysensors when a grandchild interface is named from it.
    """
    parts = key.split("_")
    out = []
    for p in parts:
        if not p:
            continue
        out.append(CASING.get(p.lower(), p[:1].upper() + p[1:]))
    return "".join(out)


def singular(key: str) -> str:
    """objects -> object, waypoints -> waypoint. Array item interfaces name one item."""
    if key.endswith("ies"):
        return key[:-3] + "y"
    if key.endswith("ses") or key.endswith("xes"):
        return key[:-2]
    if key.endswith("s") and not key.endswith("ss"):
        return key[:-1]
    return key


def indent(text: str, n: int = 2) -> str:
    pad = " " * n
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


# Set per file by build(). $ref is resolved against this, and every ref is
# emitted ONCE under a stable name so two properties sharing a $def share the
# TypeScript interface too - which is the whole point of writing the $def.
_ROOT: dict = {}
_REF_NAMES: dict[str, str] = {}


def resolve_ref(schema: dict) -> tuple[dict, str | None]:
    """Follow a local `$ref`. Returns (target schema, its $defs key).

    Only `#/$defs/<name>` is supported, deliberately: a remote or a deeply
    pointed ref would make the contract depend on fetch order or on JSON
    Pointer subtleties, and this generator is a build gate, not a validator.
    """
    ref = schema.get("$ref")
    if not ref:
        return schema, None
    if not ref.startswith("#/$defs/"):
        sys.exit(f"FATAL: only #/$defs/<name> refs are supported, got {ref!r}")
    key = ref[len("#/$defs/"):]
    target = (_ROOT.get("$defs") or {}).get(key)
    if target is None:
        sys.exit(f"FATAL: {ref} does not exist")
    return target, key


def render_type(schema: dict, name_hint: str, nested: list[str]) -> str:
    """Return the TS type expression for `schema`, appending any named
    nested interfaces it needs to `nested`."""
    if "$ref" in schema:
        target, key = resolve_ref(schema)
        # The interface is named from the $def, not from the property that
        # happens to reach it first, so `attributes.relations` and the
        # room-level `relations` do not generate two identical interfaces.
        if key not in _REF_NAMES:
            iface = ts_name(f"{_ROOT.get('_root_name', '')}_{key}")
            # reserve the name BEFORE recursing, so a self-referential $def
            # terminates instead of spinning
            _REF_NAMES[key] = iface
            nested.append(render_interface(iface, target, nested))
        return _REF_NAMES[key]

    if "const" in schema:
        return json.dumps(schema["const"])

    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])

    t = schema.get("type")

    if isinstance(t, list):  # e.g. ["string", "null"]
        parts = [render_type({**schema, "type": x}, name_hint, nested) for x in t]
        return " | ".join(parts)

    if t == "string":
        return "string"
    if t in ("number", "integer"):
        return "number"
    if t == "boolean":
        return "boolean"

    if t == "array":
        items = schema.get("items")
        if not items:
            return "unknown[]"
        # fixed-length numeric tuples (positions, dimensions) stay tuples
        mn, mx = schema.get("minItems"), schema.get("maxItems")
        # an array's item interface should be named for ONE item, not the collection
        inner = render_type(items, singular(name_hint), nested)
        if mn and mn == mx and mn <= 4 and inner == "number":
            return "[" + ", ".join(["number"] * mn) + "]"
        return f"{inner}[]"

    if t == "object" or "properties" in schema:
        props = schema.get("properties")
        if not props:
            return "Record<string, unknown>"
        iface = ts_name(name_hint)
        nested.append(render_interface(iface, schema, nested))
        return iface

    return "unknown"


def render_interface(name: str, schema: dict, nested: list[str]) -> str:
    props: dict = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines: list[str] = []
    for key, sub in props.items():
        desc = sub.get("description")
        if desc:
            lines.append(f"  /** {desc} */")
        opt = "" if key in required else "?"
        # nested interfaces get a name derived from parent+key so they never collide
        expr = render_type(sub, f"{name}_{key}", nested)
        lines.append(f"  {key}{opt}: {expr};")
    body = "\n".join(lines)
    return f"export interface {name} {{\n{body}\n}}"


def build(stem: str, out_file: str, root_name: str) -> str:
    src = CONTRACTS / f"{stem}.schema.json"
    if not src.exists():
        sys.exit(f"FATAL: missing schema {src}")
    try:
        schema = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"FATAL: {src.name} is not valid JSON: {e}")

    if schema.get("type") != "object":
        sys.exit(f"FATAL: {src.name} root must be type=object")

    global _ROOT
    _ROOT = {**schema, "_root_name": root_name}
    _REF_NAMES.clear()

    nested: list[str] = []
    root = render_interface(root_name, schema, nested)
    # nested interfaces are collected depth-first; emit them before the root
    blocks = [HEADER.format(src=src.name)] + nested + [root]
    return "\n\n".join(blocks).rstrip() + "\n"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, (out_file, root_name) in TARGETS.items():
        content = build(stem, out_file, root_name)
        dest = OUT_DIR / out_file
        # idempotent: only touch the file if the content actually changed
        if dest.exists() and dest.read_text(encoding="utf-8") == content:
            written.append(f"  unchanged  {dest.relative_to(ROOT)}")
        else:
            dest.write_text(content, encoding="utf-8")
            written.append(f"  WROTE      {dest.relative_to(ROOT)}")

    # a barrel file so callers can `import type { SceneGraph } from "../types"`
    index = (
        "// AUTO-GENERATED - DO NOT EDIT BY HAND.\n"
        'export type {\n'
        "  SceneGraph,\n"
        "  SceneGraphObject,\n"
        "  SceneGraphObjectAttributes,\n"
        "  SceneGraphObjectAttributesColor,\n"
        "  SceneGraphRelation,\n"
        "  SceneGraphRoomRelation,\n"
        "  SceneGraphWaypoint,\n"
        '} from "./scene";\n'
        'export type { Command } from "./command";\n'
        'export type { Telemetry, TelemetryJoints } from "./telemetry";\n'
    )
    idx = OUT_DIR / "index.ts"
    if idx.exists() and idx.read_text(encoding="utf-8") == index:
        written.append(f"  unchanged  {idx.relative_to(ROOT)}")
    else:
        idx.write_text(index, encoding="utf-8")
        written.append(f"  WROTE      {idx.relative_to(ROOT)}")

    print("generate_types.py")
    print("\n".join(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
