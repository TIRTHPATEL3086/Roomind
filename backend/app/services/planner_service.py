"""Planner (spec 9.8): resolve a command target to a world point, then A* to it."""
from __future__ import annotations

import logging
import math

from app.config import get_settings
from app.core.errors import NoPathFound, NotFound
from app.core.geometry import Vec2, yaw_towards
from app.core.navmesh import (
    DEFAULT_RADIUS,
    ROBOT_RADIUS,
    NavGrid,
    astar,
    build_grid,
    path_length,
    plan,
    smooth,
)

log = logging.getLogger("roommind.planner")

# How close ARIA stops to a bare POINT she was told to go to (a waypoint, or an
# explicit coordinate). Objects get the standoff computed below instead, which
# is measured from the object's surface rather than from its centre.
APPROACH_DISTANCE_M = 0.60

# Breathing room beyond the clearance the navmesh already guarantees. The grid
# is inflated by robot radius + geofence margin, so the nearest free cell to a
# sofa is already 0.31 m from its side; this is the extra gap that makes ARIA
# look like she stopped to look at something rather than like she nearly hit
# it, and it leaves her arms room to point.
APPROACH_CLEARANCE_M = 0.20

# How many stand-off candidates around an object to actually plan routes to.
# Every one costs an A*, and the ring is sampled far more finely than that so
# that the cheap geometric filter has something to choose from.
APPROACH_RING_SAMPLES = 24
MAX_APPROACH_PLANS = 10


def approach_distance(robot_id: str = "aria",
                      geofence_margin_m: float | None = None) -> float:
    """How far from an object's SURFACE ARIA should come to rest.

    Derived, not hardcoded: it is the robot's own footprint plus the safety
    margin the navmesh already enforces plus a fixed sliver. Change the robot's
    radius or the geofence and this follows, which is the point — a literal
    0.5 in the code would silently stop being safe the day ARIA gets wider.

    With the shipped configuration (radius 0.16, geofence 0.15) that is 0.51 m,
    inside the 0.4-0.7 m band the behaviour is specified in.
    """
    if geofence_margin_m is None:
        geofence_margin_m = get_settings().geofence_margin_m
    return (ROBOT_RADIUS.get(robot_id, DEFAULT_RADIUS)
            + geofence_margin_m + APPROACH_CLEARANCE_M)


def _offset_ring(obj: dict, standoff: float, samples: int) -> list[Vec2]:
    """Points on a rectangle `standoff` metres outside an object's footprint.

    The offset RECTANGLE, not a circle of radius `boundary + standoff` cast
    along each ray. A ray leaving the centre at an oblique angle crosses the
    face at a slant, so a point placed `standoff` further along that ray sits
    only `standoff * cos(theta)` from the surface — measured on the demo room's
    table that is 0.38 m of real clearance where 0.51 m was asked for, and the
    error is worst exactly where furniture is most likely to have something
    beside it. Offsetting each face along its own normal gives every point on
    an edge exactly `standoff` of clearance and every corner point slightly
    more, which is the guarantee the caller thinks it is getting.
    """
    cx, _, cz = (float(v) for v in obj["position"])
    w, _, d = (float(v) for v in obj["dimensions"])
    rot = float(obj.get("rotation_y", 0.0))
    hw, hd = w / 2.0 + standoff, d / 2.0 + standoff

    perimeter = 4.0 * (hw + hd)
    step = perimeter / max(samples, 4)
    c, s = math.cos(rot), math.sin(rot)

    out: list[Vec2] = []
    for i in range(max(samples, 4)):
        t = i * step
        # walk the perimeter of the expanded rectangle in the object's frame
        if t < 2 * hw:                       # +Z face, left to right
            lx, lz = -hw + t, hd
        elif t < 2 * hw + 2 * hd:            # +X face, front to back
            lx, lz = hw, hd - (t - 2 * hw)
        elif t < 4 * hw + 2 * hd:            # -Z face, right to left
            lx, lz = hw - (t - 2 * hw - 2 * hd), -hd
        else:                                # -X face, back to front
            lx, lz = -hw, -hd + (t - 4 * hw - 2 * hd)
        # local -> world, matching geometry.obb_corners_xz exactly
        out.append((cx + lx * c + lz * s, cz - lx * s + lz * c))
    return out


class PlannerService:
    def resolve_target(self, scene_graph: dict, target: str | None,
                       params: dict | None = None) -> tuple[float, float, float]:
        """object id | waypoint name | params.point -> a world XYZ point.

        Raises NotFound rather than guessing. The LLM is only ever allowed to cite
        ids that exist (spec 8.2), so a miss here is a real bug, not user error.
        """
        params = params or {}

        if "point" in params:
            p = params["point"]
            if len(p) == 2:
                return (float(p[0]), scene_graph.get("floor_y", 0.0), float(p[1]))
            return (float(p[0]), float(p[1]), float(p[2]))

        if not target:
            raise NotFound("command has no target and no params.point")

        for obj in scene_graph.get("objects", []):
            if obj["id"] == target:
                return tuple(obj["position"])  # type: ignore[return-value]

        for wp in scene_graph.get("waypoints", []):
            if wp["name"] == target:
                return tuple(wp["position"])  # type: ignore[return-value]

        raise NotFound(f"unknown target '{target}' - not an object id or waypoint name")

    def find_object(self, scene_graph: dict, target: str | None) -> dict | None:
        if not target:
            return None
        for obj in scene_graph.get("objects", []):
            if obj["id"] == target:
                return obj
        return None

    # ── approach points ──

    def approach_candidates(self, obj: dict, robot_id: str = "aria",
                            geofence_margin_m: float | None = None) -> list[Vec2]:
        """Stand-off points evenly around an object, hugging its footprint."""
        standoff = approach_distance(robot_id, geofence_margin_m)
        return _offset_ring(obj, standoff, APPROACH_RING_SAMPLES)

    def approach_point(self, scene_graph: dict, obj: dict, start: Vec2,
                       robot_id: str = "aria",
                       grid: NavGrid | None = None) -> tuple[Vec2, list[Vec2]]:
        """Pick where to stop near an object, and the route that gets there.

        Navigating to an object's CENTRE and hoping the path stops in time is
        the failure this replaces. The centre of a sofa is inside the sofa, so
        A* snapped the goal to whatever free cell happened to be nearest -
        usually behind it, sometimes on the far side of the room from the user -
        and the old fix truncated the waypoint list once it came within 0.6 m of
        the centre. On anything larger than a side table that measures the wrong
        thing entirely: 0.6 m from the centre of a 1.9 m sofa is 0.35 m INSIDE
        it, so the trim never fired and ARIA drove as close as the inflation let
        her, on whichever side the search happened to reach first.

        So: generate real stand-off points around the footprint, keep the ones
        that are free floor, and plan to the cheapest reachable one. The stop
        distance is then measured from the surface, which is what "stop near the
        chair" has always meant.
        """
        s = get_settings()
        if grid is None:
            grid = build_grid(scene_graph, robot_id,
                              geofence_margin_m=s.geofence_margin_m)

        candidates = self.approach_candidates(obj, robot_id, s.geofence_margin_m)
        free = [c for c in candidates if grid.is_free(*grid.world_to_cell(*c))]

        # Cheapest first by straight line, so the A* budget is spent on the
        # points most likely to win rather than on the far side of the object.
        free.sort(key=lambda c: math.hypot(c[0] - start[0], c[1] - start[1]))

        best: tuple[float, Vec2, list[Vec2]] | None = None
        for candidate in free[:MAX_APPROACH_PLANS]:
            raw = astar(grid, start, candidate)
            if not raw:
                continue
            route = smooth(grid, raw)
            cost = path_length(route)
            if best is None or cost < best[0]:
                best = (cost, candidate, route)
            # A route no longer than the straight line cannot be beaten, so
            # stop paying for A* the moment one turns up.
            if best[0] <= math.hypot(candidate[0] - start[0],
                                     candidate[1] - start[1]) + 1e-6:
                break

        if best is not None:
            return best[1], best[2]

        # Nothing around the object is both free and reachable - it may be
        # boxed in, or against a wall with the robot on the wrong side. Fall
        # back to the old behaviour rather than refusing to move at all, and
        # say so, because a path that ends further away than asked is worth a
        # log line.
        cx, _, cz = (float(v) for v in obj["position"])
        fallback = grid.nearest_free(cx, cz, max_radius_m=2.0)
        if fallback is None:
            raise NoPathFound(f"no free space anywhere near '{obj['id']}'")
        raw = astar(grid, start, fallback)
        if not raw:
            raise NoPathFound(f"'{obj['id']}' is not reachable from {start}")
        log.info("no clear stand-off around %s - approaching its nearest free "
                 "cell instead", obj["id"])
        return fallback, smooth(grid, raw)

    # ── planning ──

    def plan_path(self, scene_graph: dict, start: Vec2, target: str | None,
                  params: dict | None = None, robot_id: str = "aria") -> list[Vec2]:
        s = get_settings()

        obj = self.find_object(scene_graph, target) if not (params or {}).get("point") else None
        if obj is not None:
            _, path = self.approach_point(scene_graph, obj, start, robot_id)
            if not path:
                raise NoPathFound(f"no route from {start} to '{target}'")
            return path

        gx, _, gz = self.resolve_target(scene_graph, target, params)
        path = plan(
            scene_graph, start, (gx, gz),
            robot_id=robot_id,
            geofence_margin_m=s.geofence_margin_m,
        )
        if not path:
            raise NoPathFound(f"no route from {start} to '{target or params}'")

        return self._trim_approach(path, (gx, gz), scene_graph, robot_id)

    def final_yaw(self, path: list[Vec2], look_at_xz: Vec2) -> float:
        """Which way ARIA should be facing when she arrives.

        Arriving with her back to the thing she was sent to is the difference
        between a robot that went to the chair and a robot that stopped near it.
        """
        if not path:
            return 0.0
        return yaw_towards(path[-1], look_at_xz)

    def _trim_approach(self, path: list[Vec2], goal: Vec2, scene_graph: dict,
                       robot_id: str) -> list[Vec2]:
        """Stop APPROACH_DISTANCE_M short of a bare point goal.

        Objects no longer come through here - they get a real stand-off point
        (see approach_point). This remains for waypoints and explicit
        coordinates, where there is no footprint to measure from and stopping a
        little short is still the polite behaviour.
        """
        keep: list[Vec2] = []
        for wp in path:
            keep.append(wp)
            if math.hypot(wp[0] - goal[0], wp[1] - goal[1]) <= APPROACH_DISTANCE_M:
                break
        return keep or path

    def is_reachable(self, scene_graph: dict, start: Vec2, goal: Vec2,
                     robot_id: str = "aria") -> bool:
        s = get_settings()
        return bool(plan(scene_graph, start, goal, robot_id,
                         geofence_margin_m=s.geofence_margin_m))

    def free_space_ratio(self, scene_graph: dict, robot_id: str = "aria") -> float:
        """Sanity metric - if this is near zero the inflation swallowed the room."""
        grid = build_grid(scene_graph, robot_id,
                          geofence_margin_m=get_settings().geofence_margin_m)
        total = grid.width * grid.height
        return grid.free_count / total if total else 0.0


planner_service = PlannerService()

__all__ = ["planner_service", "PlannerService", "APPROACH_DISTANCE_M",
           "APPROACH_CLEARANCE_M", "approach_distance", "ROBOT_RADIUS"]
