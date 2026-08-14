"""Promote the reconstructed multi-instance room to a checked-in fixture.

`contracts/demo_room_multi.json` is pipeline OUTPUT, not hand-authored content.
This is the only thing that should ever write it, so that the guarantee the
tests assert on — scan provenance intact, every object `source=detected` — is
structurally true rather than a convention someone has to remember.

The only edit made on the way through is the asset URLs: the pipeline writes
paths relative to its output directory, and the browser fetches the mesh and
navmesh over HTTP knowing nothing about storage layout. The Twin Generator does
exactly the same rewrite when it commits a live scan.

    make demo-multi        # render -> reconstruct -> publish
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "storage" / "meshes" / "multi_demo" / "room.json"
DEST = ROOT / "contracts" / "demo_room_multi.json"


def main() -> int:
    if not SOURCE.exists():
        print(f"FATAL: {SOURCE} does not exist - run the reconstruction first "
              f"(make demo-multi)")
        return 2

    graph = json.loads(SOURCE.read_text(encoding="utf-8"))
    room_id = graph["room_id"]
    graph.setdefault("mesh", {})["url"] = f"/api/v1/rooms/{room_id}/mesh"
    graph.setdefault("navmesh", {})["url"] = f"/api/v1/rooms/{room_id}/navmesh"

    DEST.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for obj in graph["objects"]:
        counts[obj["label"]] = counts.get(obj["label"], 0) + 1
    guessed = sum(1 for o in graph["objects"]
                  if (o.get("attributes") or {}).get("label_source") == "size_prior")

    print(f"published {DEST.relative_to(ROOT)}")
    print(f"  {len(graph['objects'])} objects: "
          + ", ".join(f"{n}x {label}" for label, n in sorted(counts.items())))
    print(f"  {len(graph.get('relations', []))} relations")
    print(f"  detector={graph['scan']['detector']} "
          f"poses={graph['scan']['pose_backend']} "
          f"frames={graph['scan']['frames_used']}")
    if guessed:
        print(f"  NOTE: {guessed}/{len(graph['objects'])} labels came from the "
              f"SIZE PRIOR, not recognition")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
