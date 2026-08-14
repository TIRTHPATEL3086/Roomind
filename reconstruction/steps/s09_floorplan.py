"""S09 - floor plane, room bounds, and the occupancy grid (spec 10.2).

The floor plane matters more than it sounds. Every object's vertical position
is snapped to it in S10, the navmesh is a slice parallel to it, and the whole
scene graph's floor_y comes from it. Get the floor 10 cm wrong and every chair
in the room floats or sinks by 10 cm.
"""
from __future__ import annotations

import logging
import math

import numpy as np

log = logging.getLogger("recon.s09")

GRID_RESOLUTION_M = 0.05        # matches the navmesh contract in scene_graph.schema
CEILING_CLEARANCE_M = 2.2


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix taking unit vector a onto unit vector b (Rodrigues)."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def estimate_gravity(poses: np.ndarray, points: np.ndarray,
                     tol: float = 0.03) -> tuple[np.ndarray, float]:
    """Find which way is up, and how confident we are.

    THIS IS NOT OPTIONAL, and missing it is a silent disaster.

    Pose estimation puts the reconstruction in the FIRST CAMERA's frame -- for
    RGBD odometry, frame 0 is the identity by construction. So "up" in the
    fused mesh is wherever the phone happened to be pointing when recording
    started, not gravity. Everything downstream assumes spec 8.1 (Y-up): the
    floor estimate, the navmesh slice, the floor-snap, and every object's
    height. Skip this and the floor comes out tilted and offset -- which is
    exactly what it did here on the first run: floor_y = -0.126 m against a
    true 0.0, with 2.9% plane inliers.

    Two sources, combined:
      1. The mean camera DOWN axis over the whole capture. A person walking a
         room holds the phone roughly upright, so this is a good coarse prior
         and, unlike a plane fit, it cannot mistake a wall for the floor.
      2. A plane fit to the lowest large horizontal slab, which refines the
         coarse prior to something accurate.

    Returns (up_vector, inlier_fraction) in the CURRENT (unaligned) frame.
    """
    # 1. coarse prior: cameras use x-right, y-DOWN, z-forward.
    downs = np.asarray(poses)[:, :3, 1]
    g = downs.mean(axis=0)
    if np.linalg.norm(g) < 1e-6:
        g = np.array([0.0, -1.0, 0.0])
    up = -g / np.linalg.norm(g)

    # 2. heights along the coarse up, then vote for the floor slab.
    h = points @ up
    lo, hi = float(np.percentile(h, 0.5)), float(np.percentile(h, 99.5))
    if hi - lo < 1e-6:
        return up, 0.0
    bins = max(16, int((hi - lo) / tol))
    hist, edges = np.histogram(h, bins=bins, range=(lo, hi))
    cutoff = max(1, int(len(hist) / 3))
    band = float((edges[int(np.argmax(hist[:cutoff]))]
                  + edges[int(np.argmax(hist[:cutoff])) + 1]) / 2)

    slab = points[np.abs(h - band) < tol * 2]
    if len(slab) < 50:
        return up, 0.0

    # 3. refine: least-squares plane normal through the slab.
    centred = slab - slab.mean(axis=0)
    normal = np.linalg.svd(centred, full_matrices=False)[2][2]
    if np.dot(normal, up) < 0:
        normal = -normal

    # Reject a refinement that disagrees wildly with the camera prior: that
    # means the slab was a wall or a table top, not the floor.
    if float(np.dot(normal, up)) < math.cos(math.radians(30)):
        log.warning("floor plane normal is %.0f deg off the camera prior - "
                    "keeping the prior",
                    math.degrees(math.acos(np.clip(np.dot(normal, up), -1, 1))))
        return up, 0.0

    inliers = float(np.mean(np.abs(points @ normal - slab.mean(axis=0) @ normal)
                            < tol * 2))
    return normal, inliers


def align_to_gravity(mesh, poses: np.ndarray) -> tuple[object, np.ndarray, dict]:
    """Rotate mesh and poses so that +Y is up (spec 8.1).

    Returns (mesh, poses, meta). The mesh is modified in place and returned for
    convenience. Poses MUST be transformed too -- the geometric detector and
    S08's back-projection both use them, and a mesh in one frame with poses in
    another puts every object in the wrong place.
    """
    import open3d as o3d

    verts = np.asarray(mesh.vertices)
    if len(verts) == 0:
        return mesh, poses, {"applied": False, "reason": "empty mesh"}

    up, inliers = estimate_gravity(poses, verts)
    tilt_deg = float(math.degrees(math.acos(np.clip(up[1], -1.0, 1.0))))

    rot = _rotation_between(up, np.array([0.0, 1.0, 0.0]))
    mesh.vertices = o3d.utility.Vector3dVector(verts @ rot.T)
    if mesh.has_vertex_normals():
        mesh.vertex_normals = o3d.utility.Vector3dVector(
            np.asarray(mesh.vertex_normals) @ rot.T)

    aligned = np.asarray(poses).copy()
    aligned[:, :3, :3] = rot @ aligned[:, :3, :3]
    aligned[:, :3, 3] = aligned[:, :3, 3] @ rot.T

    log.info("gravity alignment: rotated %.1f deg (plane inliers %.1f%%)",
             tilt_deg, inliers * 100)
    return mesh, aligned, {"applied": True, "tilt_deg": round(tilt_deg, 2),
                           "plane_inliers": round(inliers, 4)}


def estimate_floor(points: np.ndarray, ransac_iters: int = 200,
                   tol: float = 0.02, rng_seed: int = 0) -> tuple[float, float]:
    """Return (floor_y, inlier_fraction) for a horizontal plane.

    A horizontal-plane search, not a general RANSAC plane fit: the room is
    already gravity-aligned (Y-up per spec 8.1), so the only unknown is the
    height. Fitting a general plane here would let a large table top tilt the
    "floor" by a few degrees and skew every object's snap.
    """
    y = np.asarray(points)[:, 1]
    if len(y) == 0:
        return 0.0, 0.0

    # Histogram vote: the floor is the largest horizontal slab in the room, and
    # the lowest large one (a table top is also horizontal and also large).
    lo, hi = float(np.percentile(y, 0.5)), float(np.percentile(y, 99.5))
    if hi - lo < 1e-6:
        return float(lo), 1.0
    bins = max(16, int((hi - lo) / tol))
    hist, edges = np.histogram(y, bins=bins, range=(lo, hi))

    # Consider only the bottom third of the room's height for floor candidates.
    cutoff = int(len(hist) / 3) + 1
    best = int(np.argmax(hist[:cutoff]))
    floor_y = float((edges[best] + edges[best + 1]) / 2)

    inliers = float(np.mean(np.abs(y - floor_y) < tol * 2))
    return floor_y, inliers


def room_bounds(points: np.ndarray, floor_y: float,
                percentile: float = 1.0) -> tuple[list[float], list[float]]:
    """Robust bounds: percentiles, not min/max.

    A single surviving noise vertex outside the wall would otherwise stretch
    the room by metres, and the navmesh grid is sized from these numbers.
    """
    p = np.asarray(points)
    lo = np.percentile(p, percentile, axis=0)
    hi = np.percentile(p, 100 - percentile, axis=0)
    lo[1] = min(floor_y, float(lo[1]))
    hi[1] = max(floor_y + CEILING_CLEARANCE_M, float(hi[1]))
    return [float(v) for v in lo], [float(v) for v in hi]


def build_occupancy(points: np.ndarray, bounds_min, bounds_max, floor_y: float,
                    resolution: float = GRID_RESOLUTION_M) -> dict:
    """uint8 grid: 1 = blocked. Indexed [z, x], origin at (bounds_min.x, .z).

    Only geometry between 8 cm and 2.2 m above the floor blocks the robot.
    Below 8 cm is the floor itself and the odd bit of skirting; above 2.2 m is
    ceiling, which ARIA (0.4 m tall) is never going to hit.
    """
    p = np.asarray(points)
    width = max(1, int(np.ceil((bounds_max[0] - bounds_min[0]) / resolution)))
    height = max(1, int(np.ceil((bounds_max[2] - bounds_min[2]) / resolution)))
    grid = np.zeros((height, width), dtype=np.uint8)

    standing = p[(p[:, 1] > floor_y + 0.08) & (p[:, 1] < floor_y + CEILING_CLEARANCE_M)]
    if len(standing):
        gx = np.floor((standing[:, 0] - bounds_min[0]) / resolution).astype(int)
        gz = np.floor((standing[:, 2] - bounds_min[2]) / resolution).astype(int)
        ok = (gx >= 0) & (gx < width) & (gz >= 0) & (gz < height)
        grid[gz[ok], gx[ok]] = 1

    return {
        "grid": grid,
        "resolution": resolution,
        "origin": [float(bounds_min[0]), float(bounds_min[2])],
        "width": width,
        "height": height,
        "blocked_fraction": float(grid.mean()),
    }


def pick_robot_dock(grid_info: dict, floor_y: float,
                    clearance_cells: int = 6) -> list[float]:
    """A free spot near a wall for ARIA to park.

    Near a wall rather than mid-room: a dock in the middle of the floor is
    where people walk. Falls back to the grid centre if the room is too
    cluttered to find anything with clearance.
    """
    grid = grid_info["grid"]
    h, w = grid.shape
    res = grid_info["resolution"]
    ox, oz = grid_info["origin"]

    free = grid == 0
    best, best_score = None, -1.0
    for gz in range(clearance_cells, h - clearance_cells):
        for gx in range(clearance_cells, w - clearance_cells):
            if not free[gz, gx]:
                continue
            window = free[gz - clearance_cells:gz + clearance_cells + 1,
                          gx - clearance_cells:gx + clearance_cells + 1]
            if not window.all():
                continue
            # Prefer positions far from the grid centre, i.e. toward the edges.
            score = abs(gx - w / 2) / w + abs(gz - h / 2) / h
            if score > best_score:
                best, best_score = (gx, gz), score

    if best is None:
        best = (w // 2, h // 2)
    return [float(ox + (best[0] + 0.5) * res), float(floor_y),
            float(oz + (best[1] + 0.5) * res)]


def run(mesh, progress=None) -> dict:
    verts = np.asarray(mesh.vertices)
    if len(verts) == 0:
        raise RuntimeError("S09 got an empty mesh - fusion produced no geometry")

    if progress:
        progress.stage("floorplan", 0.2, "estimating floor plane")
    floor_y, inliers = estimate_floor(verts)

    bmin, bmax = room_bounds(verts, floor_y)
    if progress:
        progress.stage("floorplan", 0.6, "building occupancy grid")
    grid_info = build_occupancy(verts, bmin, bmax, floor_y)
    dock = pick_robot_dock(grid_info, floor_y)

    if inliers < 0.05:
        log.warning("floor plane has only %.1f%% inliers - the capture may not "
                    "be gravity-aligned", inliers * 100)

    if progress:
        progress.stage("floorplan", 1.0,
                       f"floor y={floor_y:.3f}, {grid_info['width']}x{grid_info['height']} grid")
    return {"floor_y": floor_y, "floor_inliers": inliers,
            "bounds_min": bmin, "bounds_max": bmax,
            "grid": grid_info, "robot_dock": dock}
