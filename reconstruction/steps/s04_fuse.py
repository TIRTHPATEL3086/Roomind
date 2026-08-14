"""S04-S06 - TSDF fusion, meshing, and texture (spec 10.6).

Kept in one module because they share the TSDF volume and splitting them would
mean serialising a multi-hundred-megabyte voxel grid to disk between stages for
no benefit.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

log = logging.getLogger("recon.s04")

# voxel_length by --quality. 2 cm is the spec's medium setting; 1 cm quadruples
# memory and mostly resolves detail that the 150k-triangle budget then discards.
VOXEL_BY_QUALITY = {"fast": 0.04, "medium": 0.02, "high": 0.01}
TARGET_TRIS = 150_000

# A detached mesh component is kept only if it is at least this big relative to
# the room shell, and at least this many triangles outright. Both bars are low:
# the job is to separate real furniture from depth speckle, and a wall-mounted
# TV comes out around 5,000 triangles while noise shards are tens.
MIN_COMPONENT_FRACTION = 0.002
MIN_COMPONENT_TRIS = 200


def fuse(frames: list[str], depths: list[np.ndarray], poses: np.ndarray,
         k: np.ndarray, quality: str = "medium", progress=None):
    import open3d as o3d

    from utils.intrinsics import to_open3d

    h, w = depths[0].shape[:2]
    intr = to_open3d(k, w, h)
    voxel = VOXEL_BY_QUALITY.get(quality, 0.02)

    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel,
        sdf_trunc=voxel * 3,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8)

    n = len(frames)
    for i in range(n):
        bgr = cv2.imread(frames[i], cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        if bgr.shape[:2] != (h, w):
            bgr = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)
        colour = o3d.geometry.Image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        depth = o3d.geometry.Image(depths[i].astype(np.float32))

        # depth_trunc 5.0, not the spec's 4.0: in a 5 x 4 m room the far wall
        # is 4.3 m from a camera walking the opposite perimeter, so a 4 m cut
        # deletes exactly the geometry that closes the room.
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            colour, depth, depth_scale=1.0, depth_trunc=5.0,
            convert_rgb_to_intensity=False)
        # integrate() wants WORLD-from-camera (the extrinsic), and poses are
        # camera-to-world, hence the inverse. Getting this backwards produces a
        # mesh that looks like the room turned inside out.
        volume.integrate(rgbd, intr, np.linalg.inv(poses[i]))

        if progress and i % 5 == 0:
            progress.stage("fuse", i / n, f"integrating {i}/{n}")

    return volume


def extract_mesh(volume, progress=None):
    import open3d as o3d

    mesh = volume.extract_triangle_mesh()
    mesh.compute_vertex_normals()
    if progress:
        progress.stage("mesh", 0.3, f"{len(mesh.triangles)} raw triangles")

    mesh = mesh.filter_smooth_taubin(number_of_iterations=8)
    if len(mesh.triangles) > TARGET_TRIS:
        mesh = mesh.simplify_quadric_decimation(TARGET_TRIS)
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_unreferenced_vertices()

    # Drop floating fragments -- but NOT everything that happens not to touch
    # the floor.
    #
    # TSDF fusion always leaves shards where depth was noisy, and they wreck the
    # room's bounding box: one stray triangle three metres outside the wall
    # makes the navmesh four times bigger than the room. The old rule kept only
    # the single largest connected component, which removed them perfectly and
    # also removed every object that is genuinely detached from the room shell.
    # A wall-mounted television standing 14 cm proud of the wall is its own
    # component, so both TVs in the multi-instance fixture were deleted here --
    # 20 and 17 frames respectively had hundreds of pixels on them, they
    # integrated into the volume correctly, and then this line threw them away.
    # Every stage downstream reported the truth as it found it: the detector
    # found no TV because by then there was no TV.
    #
    # So: keep any component that is both SUBSTANTIAL and INSIDE the room.
    # Shards fail the first test or the second, detached furniture passes both.
    if progress:
        progress.stage("mesh", 0.7, "dropping floating fragments")
    labels, counts, _ = mesh.cluster_connected_triangles()
    labels = np.asarray(labels)
    counts = np.asarray(counts)
    if len(counts):
        main = int(np.argmax(counts))
        tris = np.asarray(mesh.triangles)
        verts = np.asarray(mesh.vertices)

        main_verts = verts[np.unique(tris[labels == main])]
        lo, hi = main_verts.min(axis=0), main_verts.max(axis=0)
        threshold = max(MIN_COMPONENT_TRIS,
                        int(counts[main] * MIN_COMPONENT_FRACTION))

        keep = np.zeros(len(counts), dtype=bool)
        keep[main] = True
        for c in range(len(counts)):
            if c == main or counts[c] < threshold:
                continue
            cluster_verts = verts[np.unique(tris[labels == c])]
            centre = (cluster_verts.min(axis=0) + cluster_verts.max(axis=0)) / 2
            # Inside the shell's own bounds, so it cannot inflate them.
            if np.all(centre >= lo) and np.all(centre <= hi):
                keep[c] = True

        dropped = int((~keep).sum())
        if dropped:
            log.info("dropped %d floating fragment(s), kept %d component(s)",
                     dropped, int(keep.sum()))
        mesh.remove_triangles_by_mask(~keep[labels] | (labels < 0))
        mesh.remove_unreferenced_vertices()

    mesh.compute_vertex_normals()
    if progress:
        progress.stage("mesh", 1.0, f"{len(mesh.triangles)} triangles")
    return mesh


def boost_saturation(mesh, saturation: float = 1.25, contrast: float = 1.12):
    """Spec 10.6: a deliberate look, not a bug.

    Raw baked albedo from phone footage is washed out and reads as grey mush on
    the dark navy UI. A mild saturation lift plus an S-curve is what makes the
    reconstruction look like a product rather than a lidar dump.
    """
    import open3d as o3d

    if not mesh.has_vertex_colors():
        return mesh
    cols = np.asarray(mesh.vertex_colors)
    if len(cols) == 0:
        return mesh

    hsv = cv2.cvtColor((cols[None] * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    hsv = hsv.astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * saturation, 0, 255)
    rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)[0] / 255.0

    # Contrast S-curve about mid-grey.
    rgb = np.clip((rgb - 0.5) * contrast + 0.5, 0.0, 1.0)
    mesh.vertex_colors = o3d.utility.Vector3dVector(rgb)
    return mesh
