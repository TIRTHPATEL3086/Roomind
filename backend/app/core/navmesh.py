"""Navmesh: 2D occupancy grid on the XZ plane + A* + string-pulling (spec 9.4).

The grid is built from the scene graph's object OBBs, inflated by the robot radius
plus GEOFENCE_MARGIN_M so the planner can treat ARIA as a point.

Pure Python, no I/O, no DB, no framework. This is a `core/` module: it may not
import anything from `services/` or `api/` (spec 1.4.2).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from app.core.geometry import Vec2, obb_aabb_xz, point_in_obb_xz

# ARIA's footprint: base radius plus arm-swing clearance.
ROBOT_RADIUS = {"aria": 0.16}
DEFAULT_RADIUS = 0.16

# 8-connected grid. Diagonals cost sqrt(2) so the heuristic stays admissible.
_NEIGHBOURS: tuple[tuple[int, int, float], ...] = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)),
)


@dataclass
class NavGrid:
    """Occupancy grid. `blocked[z][x]` is True where ARIA may not go."""

    resolution: float                 # metres per cell
    origin: Vec2                      # world XZ of cell (0,0)'s corner
    width: int                        # cells along X
    height: int                       # cells along Z
    blocked: list[list[bool]] = field(repr=False, default_factory=list)

    # ── coordinate conversion ──

    def world_to_cell(self, x: float, z: float) -> tuple[int, int]:
        cx = int((x - self.origin[0]) / self.resolution)
        cz = int((z - self.origin[1]) / self.resolution)
        return cx, cz

    def cell_to_world(self, cx: int, cz: int) -> Vec2:
        """Centre of the cell, not its corner."""
        return (
            self.origin[0] + (cx + 0.5) * self.resolution,
            self.origin[1] + (cz + 0.5) * self.resolution,
        )

    def in_bounds(self, cx: int, cz: int) -> bool:
        return 0 <= cx < self.width and 0 <= cz < self.height

    def is_free(self, cx: int, cz: int) -> bool:
        return self.in_bounds(cx, cz) and not self.blocked[cz][cx]

    @property
    def free_count(self) -> int:
        return sum(row.count(False) for row in self.blocked)

    # ── queries ──

    def nearest_free(self, x: float, z: float, max_radius_m: float = 1.0) -> Vec2 | None:
        """Closest free cell centre to a world point, searched in expanding rings.

        Needed because a navigation target is usually the CENTRE of an object,
        which is by definition inside an obstacle.
        """
        cx, cz = self.world_to_cell(x, z)
        if self.is_free(cx, cz):
            return self.cell_to_world(cx, cz)

        max_r = max(1, int(max_radius_m / self.resolution))
        for r in range(1, max_r + 1):
            best: tuple[float, Vec2] | None = None
            for dz in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    # ring only - the interior was covered by smaller r
                    if max(abs(dx), abs(dz)) != r:
                        continue
                    nx, nz = cx + dx, cz + dz
                    if not self.is_free(nx, nz):
                        continue
                    w = self.cell_to_world(nx, nz)
                    d = math.hypot(w[0] - x, w[1] - z)
                    if best is None or d < best[0]:
                        best = (d, w)
            if best is not None:
                return best[1]
        return None

    def line_of_sight(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """Supercover Bresenham: True if every cell the segment touches is free.

        Used by string-pulling. A plain Bresenham line can slip diagonally between
        two blocked cells, which produces a "smoothed" path that clips a table corner.
        """
        x0, z0 = a
        x1, z1 = b
        dx, dz = abs(x1 - x0), abs(z1 - z0)
        x, z = x0, z0
        n = dx + dz
        x_inc = 1 if x1 > x0 else -1
        z_inc = 1 if z1 > z0 else -1
        error = dx - dz
        dx *= 2
        dz *= 2

        for _ in range(n + 1):
            if not self.is_free(x, z):
                return False
            if error > 0:
                x += x_inc
                error -= dz
            elif error < 0:
                z += z_inc
                error += dx
            else:
                # exactly diagonal: both orthogonal neighbours must be free too,
                # otherwise we are squeezing through a corner gap
                if not self.is_free(x + x_inc, z) or not self.is_free(x, z + z_inc):
                    return False
                x += x_inc
                z += z_inc
                error -= dz
                error += dx
        return True


def build_grid(
    scene_graph: dict,
    robot_id: str = "aria",
    resolution: float = 0.05,
    geofence_margin_m: float = 0.15,
) -> NavGrid:
    """Rasterise the scene graph's obstacles into an inflated occupancy grid.

    Inflation = robot radius + geofence margin, so A* can plan for a point robot
    and the resulting path still clears real furniture.
    """
    bounds = scene_graph["bounds"]
    min_x, _, min_z = bounds["min"]
    max_x, _, max_z = bounds["max"]

    width = max(1, int(math.ceil((max_x - min_x) / resolution)))
    height = max(1, int(math.ceil((max_z - min_z) / resolution)))
    grid = NavGrid(
        resolution=resolution,
        origin=(min_x, min_z),
        width=width,
        height=height,
        blocked=[[False] * width for _ in range(height)],
    )

    inflate = ROBOT_RADIUS.get(robot_id, DEFAULT_RADIUS) + geofence_margin_m

    for obj in scene_graph.get("objects", []):
        if not obj.get("is_obstacle", True):
            continue
        pos = tuple(obj["position"])
        dim = tuple(obj["dimensions"])
        rot = float(obj.get("rotation_y", 0.0))

        # Only rasterise the AABB of the inflated OBB, then do an exact test per cell.
        ax0, az0, ax1, az1 = obb_aabb_xz(pos, dim, rot)
        cx0, cz0 = grid.world_to_cell(ax0 - inflate, az0 - inflate)
        cx1, cz1 = grid.world_to_cell(ax1 + inflate, az1 + inflate)

        for cz in range(max(0, cz0), min(height - 1, cz1) + 1):
            for cx in range(max(0, cx0), min(width - 1, cx1) + 1):
                wx, wz = grid.cell_to_world(cx, cz)
                # inflate by growing the box rather than dilating the bitmap:
                # exact, and it costs nothing extra
                grown = (dim[0] + 2 * inflate, dim[1], dim[2] + 2 * inflate)
                if point_in_obb_xz((wx, wz), pos, grown, rot):
                    grid.blocked[cz][cx] = True

    # Seal the room perimeter so a path can never leave the scanned volume.
    for cx in range(width):
        grid.blocked[0][cx] = True
        grid.blocked[height - 1][cx] = True
    for cz in range(height):
        grid.blocked[cz][0] = True
        grid.blocked[cz][width - 1] = True

    return grid


def astar(grid: NavGrid, start: Vec2, goal: Vec2) -> list[Vec2]:
    """A* over the grid. Returns world-space XZ waypoints, or [] if unreachable.

    Both endpoints are snapped to the nearest free cell first, so callers may pass
    an object's centre (which is inside an obstacle) as the goal.
    """
    s = grid.nearest_free(*start)
    g = grid.nearest_free(*goal)
    if s is None or g is None:
        return []

    start_c = grid.world_to_cell(*s)
    goal_c = grid.world_to_cell(*g)
    if start_c == goal_c:
        return [grid.cell_to_world(*goal_c)]

    def h(c: tuple[int, int]) -> float:
        """Octile distance - admissible and consistent for 8-connected grids.
        Plain Euclidean under-estimates less but octile expands far fewer nodes."""
        dx = abs(c[0] - goal_c[0])
        dz = abs(c[1] - goal_c[1])
        return (dx + dz) + (math.sqrt(2) - 2) * min(dx, dz)

    open_heap: list[tuple[float, tuple[int, int]]] = [(h(start_c), start_c)]
    came: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {start_c: 0.0}
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        if cur == goal_c:
            return _reconstruct(grid, came, cur)
        closed.add(cur)

        for dx, dz, cost in _NEIGHBOURS:
            nxt = (cur[0] + dx, cur[1] + dz)
            if nxt in closed or not grid.is_free(*nxt):
                continue
            # never cut a corner diagonally between two blocked cells
            if dx and dz:
                if not grid.is_free(cur[0] + dx, cur[1]) or not grid.is_free(cur[0], cur[1] + dz):
                    continue
            tentative = g_score[cur] + cost
            if tentative < g_score.get(nxt, math.inf):
                came[nxt] = cur
                g_score[nxt] = tentative
                heapq.heappush(open_heap, (tentative + h(nxt), nxt))

    return []


def _reconstruct(
    grid: NavGrid, came: dict[tuple[int, int], tuple[int, int]], cur: tuple[int, int]
) -> list[Vec2]:
    cells = [cur]
    while cur in came:
        cur = came[cur]
        cells.append(cur)
    cells.reverse()
    return [grid.cell_to_world(*c) for c in cells]


def smooth(grid: NavGrid, path: list[Vec2]) -> list[Vec2]:
    """String-pulling: drop any waypoint the robot can see past.

    Turns a 200-cell staircase into 3-4 real waypoints, which is the difference
    between ARIA gliding across the room and juddering cell by cell.
    """
    if len(path) <= 2:
        return list(path)

    out = [path[0]]
    anchor = 0
    i = 1
    while i < len(path) - 1:
        a = grid.world_to_cell(*path[anchor])
        b = grid.world_to_cell(*path[i + 1])
        if not grid.line_of_sight(a, b):
            out.append(path[i])
            anchor = i
        i += 1
    out.append(path[-1])
    return out


def plan(
    scene_graph: dict,
    start: Vec2,
    goal: Vec2,
    robot_id: str = "aria",
    resolution: float = 0.05,
    geofence_margin_m: float = 0.15,
) -> list[Vec2]:
    """Convenience: build grid -> A* -> smooth. Returns [] if unreachable."""
    grid = build_grid(scene_graph, robot_id, resolution, geofence_margin_m)
    raw = astar(grid, start, goal)
    return smooth(grid, raw) if raw else []


def path_length(path: list[Vec2]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:], strict=False)
    )
