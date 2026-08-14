"""Synthetic room capture with EXACT ground truth.

Why this exists
---------------
The Phase 5 acceptance asks for object dimensions "within +/-15% of
tape-measured ground truth". A tape measure gives you three numbers with a
centimetre of human error and no way to re-run the experiment. A rendered room
gives you every number exactly, for every object, repeatably -- so the test can
assert on position, yaw, floor contact and count as well as size, and it fails
loudly when someone breaks the lifting maths.

This is a TEST FIXTURE, not a shortcut around real capture. It produces exactly
what a depth-equipped phone produces -- RGB frames, depth frames, intrinsics --
and nothing else. In particular it does NOT hand the pipeline the camera poses
unless asked: S02 has to solve them from the frames like it would for a real
capture. What the harness knows and the pipeline does not is kept in
ground_truth.json, which only the tests read.

The renderer is a vectorised ray caster over oriented boxes. Surfaces carry
procedural texture on purpose: RGBD odometry tracks photometric gradients, and
flat-shaded walls give it nothing to lock onto, which would make the synthetic
capture unrealistically HARD rather than unrealistically easy.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

# A small living room, all measurements in metres. Every one of these is a
# number the pipeline must recover.
DEFAULT_ROOM = {
    "size": [5.0, 2.6, 4.0],          # interior width (x), height (y), depth (z)
    "objects": [
        # label,          position [x, y, z] (centre),  dims [w, h, d],  yaw deg,  colour
        ("sofa",          [-1.55, 0.40, -1.20], [1.90, 0.80, 0.85],   0.0,  (0.28, 0.33, 0.48)),
        ("table",         [ 0.10, 0.37, -0.10], [1.10, 0.74, 0.65],   0.0,  (0.55, 0.38, 0.24)),
        ("chair",         [ 0.10, 0.45,  0.95], [0.52, 0.90, 0.54],  20.0,  (0.62, 0.28, 0.28)),
        ("chair",         [-1.10, 0.45,  0.95], [0.52, 0.90, 0.54], -15.0,  (0.62, 0.28, 0.28)),
        ("shelf",         [ 2.05, 0.90,  0.60], [0.75, 1.80, 0.32],  90.0,  (0.42, 0.32, 0.22)),
        ("tv",            [ 0.05, 1.05, -1.78], [1.05, 0.62, 0.09],   0.0,  (0.10, 0.10, 0.12)),
        ("potted_plant",  [ 1.85, 0.42, -1.40], [0.38, 0.84, 0.38],   0.0,  (0.20, 0.45, 0.24)),
    ],
}

# A room built to break instance resolution rather than to look pretty.
#
# Three chairs that differ ONLY by colour, two tables, two TVs, a bed, a sofa
# and a lamp: ten objects across six classes, four of which have more than one
# instance. Everything the feature claims has to survive here — "the red chair"
# has to pick one of three identical shapes, "the chair near the table" has to
# pick between chairs whose neighbours differ, and "go to the chair" has to
# refuse to guess.
#
# Placement rules that matter, learned from the first layout that did not work:
#
#   * chairs sit near DIFFERENT landmarks (table, bed, second table) so a
#     spatial constraint actually separates them. Three chairs around one table
#     would make "the chair near the table" ambiguous by construction, which
#     tests the question but never tests the answer.
#   * the room is 6.5 x 5.0 m, not 5 x 4. Ten objects in the smaller room left
#     no free floor between them once the navmesh inflated each by 0.31 m, so
#     A* could not route BETWEEN pieces of furniture and every approach point
#     collapsed onto the same few cells.
#   * both TVs are off the wall by 12 cm. Flush-mounted, they fuse into the
#     wall and the segmentation drops them (see the TV that section 5's
#     reconstruction misses entirely) — and a demo that cannot see either TV
#     cannot demonstrate choosing between them.
#   * NOTHING may come within ~0.30 m of anything else, in any axis. The
#     detector segments the fused cloud with 26-connected components over 5 cm
#     voxels, so a 0.15 m gap is three voxels and TSDF smear closes it: the
#     first layout put the sofa's front edge exactly against the table's back
#     edge and the two fused into a single 1.6 x 2.2 m "bed". That is the
#     detector behaving correctly on furniture that really is touching, which
#     is why the fixture must not have any.
#   * both TVs stand clear of the wall. Flush to it they fuse into it and
#     vanish, which is the same failure section 5 records for the original
#     room's TV.
#   * the camera orbits at 1.80 m here rather than the default 1.45 m, because
#     the 1.56 m lamp stands on the orbit path and the camera would otherwise
#     pass through it for a frame or two.
#   * the TVs hang at 1.05 m, not the 1.35 m they started at. The orbit looks
#     DOWN (eye 1.80 m, look-at 0.50 m), so with a 62 deg frame anything much
#     above 1.2 m on a far wall falls off the top edge: at 1.35 m neither TV
#     appeared in a single fused voxel and the detector was blamed for missing
#     objects the capture never contained. 1.05 m is also where a wall-mounted
#     television actually hangs.
MULTI_ROOM = {
    "size": [6.5, 2.6, 5.0],
    "camera_height": 1.80,
    "objects": [
        # three chairs, identical geometry, three clearly different colours,
        # each parked beside a DIFFERENT landmark
        ("chair",   [-2.10, 0.45, -0.35], [0.52, 0.90, 0.54],  15.0, (0.72, 0.12, 0.12)),  # red,   by table_01
        ("chair",   [-0.30, 0.45, -1.20], [0.52, 0.90, 0.54], -20.0, (0.09, 0.09, 0.11)),  # black, by the bed
        ("chair",   [ 2.10, 0.45,  0.60], [0.52, 0.90, 0.54],   0.0, (0.13, 0.29, 0.68)),  # blue,  by table_02
        # two tables, table-proportioned but clearly different sizes, so
        # size_class separates them as well as position does
        ("table",   [-2.10, 0.37,  0.70], [1.40, 0.74, 0.85],   0.0, (0.54, 0.37, 0.22)),
        ("table",   [ 2.10, 0.37,  1.60], [1.05, 0.74, 0.70],   0.0, (0.50, 0.34, 0.20)),
        # two TVs: one alone on the far wall, one beside the small table, so
        # "the TV near the table" has exactly one answer
        ("tv",      [-1.20, 1.05, -2.30], [1.10, 0.64, 0.12],   0.0, (0.07, 0.07, 0.09)),
        ("tv",      [ 3.05, 1.05,  1.55], [0.10, 0.56, 0.95],   0.0, (0.08, 0.08, 0.10)),
        ("bed",     [ 1.40, 0.28, -1.60], [1.95, 0.56, 1.45],   0.0, (0.78, 0.74, 0.66)),
        ("sofa",    [-2.10, 0.40,  1.90], [1.90, 0.80, 0.85],   0.0, (0.25, 0.42, 0.32)),
        ("lamp",    [ 0.80, 0.78,  2.10], [0.32, 1.56, 0.32],   0.0, (0.86, 0.80, 0.55)),
    ],
}

ROOMS = {"default": DEFAULT_ROOM, "multi": MULTI_ROOM}


# ───────────────────────────────── geometry ────────────────────────────────

def _box_matrix(yaw: float) -> np.ndarray:
    """local -> world rotation about Y, spec 8.1 (0 = +Z, positive toward +X)."""
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _ray_box(origins: np.ndarray, dirs: np.ndarray, centre: np.ndarray,
             half: np.ndarray, rot: np.ndarray):
    """Slab-method intersection with an oriented box. Vectorised over rays.

    Returns (t_hit, normal_local); t_hit is inf where there is no hit.
    """
    # Transform the rays into the box's local frame; then it is axis-aligned.
    o = (origins - centre) @ rot
    d = dirs @ rot

    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / d
        t1 = (-half - o) * inv
        t2 = (half - o) * inv

    tmin = np.minimum(t1, t2)
    tmax = np.maximum(t1, t2)
    # A ray exactly parallel to a slab gives nan; treat it as unbounded.
    tmin = np.nan_to_num(tmin, nan=-np.inf, posinf=np.inf, neginf=-np.inf)
    tmax = np.nan_to_num(tmax, nan=np.inf, posinf=np.inf, neginf=-np.inf)

    t_near = tmin.max(axis=1)
    t_far = tmax.min(axis=1)
    hit = (t_near <= t_far) & (t_far > 1e-4)
    t = np.where(hit, np.where(t_near > 1e-4, t_near, t_far), np.inf)

    axis = np.argmax(tmin, axis=1)
    normal = np.zeros_like(o)
    rows = np.arange(len(o))
    normal[rows, axis] = -np.sign(d[rows, axis])

    return t, normal


def _texture(world_pts: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Procedural per-surface texture.

    Odometry needs photometric gradient. Two octaves of hash noise plus a
    coarse checker give every surface something trackable without any texture
    files, and keep the synthetic capture about as hard as a real one.
    """
    p = world_pts
    def h(v):
        return np.modf(np.sin(v) * 43758.5453)[0]

    n1 = h(p[:, 0] * 12.9898 + p[:, 1] * 78.233 + p[:, 2] * 37.719)
    n2 = h(p[:, 0] * 51.31 + p[:, 1] * 21.17 + p[:, 2] * 93.41)
    checker = ((np.floor(p[:, 0] * 4) + np.floor(p[:, 2] * 4)
                + np.floor(p[:, 1] * 4)) % 2)

    shade = 0.80 + 0.10 * n1 + 0.06 * n2 + 0.06 * checker
    return np.clip(base * shade[:, None], 0.0, 1.0)


def build_scene(room: dict) -> list[dict]:
    """Room shell (as inward-facing slabs) plus the furniture."""
    sx, sy, sz = room["size"]
    t = 0.10          # wall thickness
    prims: list[dict] = []

    def add(label, centre, dims, yaw_deg, colour, is_object):
        prims.append({
            "label": label,
            "centre": np.array(centre, dtype=np.float64),
            "half": np.array(dims, dtype=np.float64) / 2,
            "rot": _box_matrix(math.radians(yaw_deg)),
            "yaw": math.radians(yaw_deg),
            "colour": np.array(colour, dtype=np.float64),
            "dims": list(dims),
            "is_object": is_object,
        })

    # floor / ceiling / four walls, built as thin slabs just outside the interior
    add("floor",   [0, -t / 2, 0],            [sx + 2 * t, t, sz + 2 * t], 0, (0.45, 0.42, 0.38), False)
    add("ceiling", [0, sy + t / 2, 0],        [sx + 2 * t, t, sz + 2 * t], 0, (0.72, 0.72, 0.75), False)
    add("wall_n",  [0, sy / 2, -sz / 2 - t / 2], [sx + 2 * t, sy, t],      0, (0.66, 0.64, 0.60), False)
    add("wall_s",  [0, sy / 2, sz / 2 + t / 2],  [sx + 2 * t, sy, t],      0, (0.66, 0.64, 0.60), False)
    add("wall_w",  [-sx / 2 - t / 2, sy / 2, 0], [t, sy, sz + 2 * t],      0, (0.60, 0.62, 0.66), False)
    add("wall_e",  [sx / 2 + t / 2, sy / 2, 0],  [t, sy, sz + 2 * t],      0, (0.60, 0.62, 0.66), False)

    for label, pos, dims, yaw, colour in room["objects"]:
        add(label, pos, dims, yaw, colour, True)
    return prims


# ────────────────────────────────── camera ─────────────────────────────────

def look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Camera-to-world for an OpenCV camera: x right, y DOWN, z forward.

    The cross-product ORDER here is load-bearing and easy to get backwards.

        right = fwd x world_up      (NOT world_up x fwd)
        down  = fwd x right

    Getting it wrong yields a matrix that is still a valid rotation, so nothing
    errors -- but the camera's y axis points UP, every rendered image comes out
    vertically flipped (you see the undersides of the furniture), and
    pose[:3, 1] is up rather than down. S09 reads exactly that column to
    estimate gravity, so it concluded the room needed rotating by 179 degrees
    and the floor landed at -1.9 m.

    Sanity check for fwd = +Z in a Y-up world: right = -X, down = -Y, and
    right x down = +Z = fwd, so the frame is right-handed.
    """
    fwd = target - eye
    fwd = fwd / np.linalg.norm(fwd)

    world_up = np.array([0.0, 1.0, 0.0])
    right = np.cross(fwd, world_up)
    if np.linalg.norm(right) < 1e-6:        # looking straight up or down
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)

    pose = np.eye(4)
    pose[:3, 0], pose[:3, 1], pose[:3, 2] = right, down, fwd
    pose[:3, 3] = eye
    return pose


def orbit_trajectory(room: dict, n: int, height: float = 1.45,
                     radius_scale: float = 0.42) -> list[np.ndarray]:
    """A slow lap around the perimeter, looking ACROSS the room.

    Two details decide whether this capture is usable at all:

    * The radius has to put the camera OUTSIDE the furniture. At 0.32 the
      camera orbits among the chairs, every frame fills with one object at
      1.5 m, and no frame ever sees the room -- so nothing gets the three
      distinct viewpoints that S08's voting needs.
    * The look-at target sits on the OPPOSITE side of the room and lags the
      camera slightly, so consecutive frames overlap (odometry needs that)
      while the view still sweeps (voting needs that).
    """
    sx, _, sz = room["size"]
    rx, rz = sx * radius_scale, sz * radius_scale
    poses = []
    for i in range(n):
        a = 2 * math.pi * i / n
        eye = np.array([rx * math.sin(a), height, rz * math.cos(a)])
        target = np.array([-0.80 * rx * math.sin(a + 0.55), 0.50,
                           -0.80 * rz * math.cos(a + 0.55)])
        poses.append(look_at(eye, target))
    return poses


# ────────────────────────────────── render ─────────────────────────────────

def render(prims: list[dict], pose: np.ndarray, k: np.ndarray,
           width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (rgb uint8 HxWx3, depth float32 HxW in metres)."""
    ys, xs = np.mgrid[0:height, 0:width]
    fx, fy, cx, cy = k[0, 0], k[1, 1], k[0, 2], k[1, 2]

    # Deliberately NOT normalised. With the camera-space z component left at
    # 1, the ray parameter t comes out as the Z-DEPTH (perpendicular distance
    # to the image plane), which is what a depth sensor reports and what every
    # pinhole back-projection here assumes.
    #
    # Normalising makes t the Euclidean RANGE instead. That is correct on the
    # optical axis and wrong everywhere else -- by 1/cos(theta), which reaches
    # ~27% in the corners of a 62 deg frame. The reconstruction then bulges
    # outward at the periphery: this room fused to 7.3 m across instead of 5.2.
    dirs_cam = np.stack([(xs.ravel() - cx) / fx, (ys.ravel() - cy) / fy,
                         np.ones(width * height)], axis=1)
    dirs = dirs_cam @ pose[:3, :3].T
    origins = np.broadcast_to(pose[:3, 3], dirs.shape)

    best_t = np.full(len(dirs), np.inf)
    best_col = np.zeros((len(dirs), 3))
    best_n = np.zeros((len(dirs), 3))

    for prim in prims:
        t, normal_local = _ray_box(origins, dirs, prim["centre"],
                                   prim["half"], prim["rot"])
        closer = t < best_t
        if not closer.any():
            continue
        best_t = np.where(closer, t, best_t)
        pts = origins[closer] + t[closer, None] * dirs[closer]
        best_col[closer] = _texture(pts, prim["colour"])
        best_n[closer] = normal_local[closer] @ prim["rot"].T

    # Simple lambert from a ceiling light, plus ambient, so faces of the same
    # box differ in brightness -- another gradient for odometry to use.
    light = np.array([0.35, 1.0, 0.25])
    light /= np.linalg.norm(light)
    lam = np.clip(best_n @ light, 0.0, 1.0)
    shade = 0.55 + 0.45 * lam
    rgb = np.clip(best_col * shade[:, None], 0, 1)

    miss = ~np.isfinite(best_t)
    rgb[miss] = 0.0
    depth = np.where(miss, 0.0, best_t).astype(np.float32)

    return ((rgb * 255).astype(np.uint8).reshape(height, width, 3),
            depth.reshape(height, width))


# ─────────────────────────────────── entry ─────────────────────────────────

def generate(out_dir: Path, room: dict | None = None, n_frames: int = 36,
             width: int = 640, height: int = 480, fov_deg: float = 62.0,
             write_poses: bool = False, seed: int = 0) -> dict:
    """Write frames/, depth/, intrinsics.json and ground_truth.json."""
    import cv2

    room = room or DEFAULT_ROOM
    out_dir = Path(out_dir)
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    (out_dir / "depth").mkdir(parents=True, exist_ok=True)

    f = width / (2 * math.tan(math.radians(fov_deg) / 2))
    k = np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1]])

    prims = build_scene(room)
    # Tall furniture stands on the orbit path in the larger rooms, and a camera
    # inside a lamp renders its interior for a frame or two. Lifting the orbit
    # above the tallest object is cheaper than routing around it.
    poses = orbit_trajectory(room, n_frames,
                             height=float(room.get("camera_height", 1.45)))

    for i, pose in enumerate(poses):
        rgb, depth = render(prims, pose, k, width, height)
        cv2.imwrite(str(out_dir / "frames" / f"{i:05d}.jpg"),
                    cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        # uint16 millimetres: exactly the format a depth-equipped phone ships.
        np.save(out_dir / "depth" / f"{i:05d}.npy", depth)

    from utils.intrinsics import save as save_intrinsics
    save_intrinsics(out_dir / "intrinsics.json", k, width, height)

    if write_poses:
        (out_dir / "poses.json").write_text(
            json.dumps({"poses": [p.tolist() for p in poses]}), encoding="utf-8")

    sx, sy, sz = room["size"]
    truth = {
        "room_size": room["size"],
        "floor_y": 0.0,
        "bounds": {"min": [-sx / 2, 0.0, -sz / 2], "max": [sx / 2, sy, sz / 2]},
        "n_frames": n_frames,
        "intrinsics": {"fx": float(k[0, 0]), "fy": float(k[1, 1]),
                       "cx": float(k[0, 2]), "cy": float(k[1, 2]),
                       "width": width, "height": height},
        "objects": [
            {"label": label, "position": list(pos), "dimensions": list(dims),
             "rotation_y_deg": yaw,
             "bottom_y": round(pos[1] - dims[1] / 2, 6)}
            for label, pos, dims, yaw, _ in room["objects"]
        ],
    }
    (out_dir / "ground_truth.json").write_text(json.dumps(truth, indent=2),
                                               encoding="utf-8")
    return truth


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a synthetic room capture.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=36)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--room", default="default", choices=sorted(ROOMS),
                    help="'multi' is the many-instances room: 3 chairs, "
                         "2 tables, 2 TVs, a bed, a sofa and a lamp")
    ap.add_argument("--write-poses", action="store_true",
                    help="also emit poses.json (skips S02 pose estimation)")
    a = ap.parse_args()

    truth = generate(Path(a.out), room=ROOMS[a.room], n_frames=a.frames,
                     width=a.width, height=a.height,
                     write_poses=a.write_poses)
    print(f"wrote {a.frames} frames to {a.out} "
          f"({len(truth['objects'])} ground-truth objects)")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
