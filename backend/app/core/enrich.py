"""Fill in the instance-level facts the resolver filters on.

The reconstruction pipeline already writes colour names, size classes and the
relation layer into room.json (S10). This module computes the same fields for
graphs that arrive without them — the checked-in demo fixture, a room from an
older scan, an object Imagine just generated — so the resolver has exactly one
shape to read and "go to the red chair" behaves identically whatever produced
the room.

It is deliberately idempotent and additive. Anything already present wins: a
colour the detector measured from real pixels is better evidence than anything
that can be re-derived here, and silently recomputing it would let a refactor
overwrite measurements with inferences.

Called from `scene_service` on every install, so nothing downstream has to ask
whether a given graph has been through it.
"""
from __future__ import annotations

from app.core import spatial
from app.core.colors import name_hex


def enrich_object(obj: dict, source: str = "fixture") -> dict:
    """Attach class, instance index and colour name to one object, in place."""
    attrs = obj.setdefault("attributes", {})

    attrs.setdefault("class", obj.get("label"))

    if "instance_index" not in attrs:
        # The id already carries the index; parsing it back is exact and keeps
        # "chair number 3" resolving to chair_03 even for hand-written rooms.
        stem, _, tail = obj.get("id", "").rpartition("_")
        if stem and tail.isdigit():
            attrs["instance_index"] = int(tail)

    if "color" not in attrs and obj.get("color"):
        if (named := name_hex(obj["color"])) is not None:
            attrs["color"] = named.as_dict()

    attrs.setdefault("label_source", source)
    if "confidence" in obj and "uncertain" not in attrs:
        attrs["uncertain"] = bool(float(obj["confidence"]) < LOW_CONFIDENCE)
    return obj


# Mirrors reconstruction/steps/s10_scenegraph.LOW_CONFIDENCE. Kept as a plain
# constant on both sides rather than shared, because the pipeline decides it at
# write time and the resolver re-checks it at query time — they are two
# independent gates on the same rule, and a scan produced before the threshold
# moved must still be judged by the current one.
LOW_CONFIDENCE = 0.45


def enrich_graph(graph: dict) -> dict:
    """Make a scene graph fully queryable. Idempotent; mutates and returns it."""
    objects = graph.get("objects") or []
    default_source = "generated" if graph.get("source") == "imagine" else "fixture"
    for obj in objects:
        enrich_object(obj, source=obj.get("source") or default_source)

    spatial.assign_size_classes(objects)
    relations = spatial.attach_relations(objects)
    graph["relations"] = [r.as_dict() for r in relations]
    return graph
