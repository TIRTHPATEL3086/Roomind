"""S06 - export the textured mesh as a Draco-compressed .glb (spec 10.6).

MESH_MAX_MB is a hard budget, not a suggestion. The frontend downloads this
file before it can show anything, and the spec is explicit that a 400 MB mesh
is a phase failure. So the export loop DECIMATES until the file fits, and
reports what it had to give up.

Vertex colours rather than a baked 2048^2 UV atlas: at 150k triangles from a
2 cm TSDF, per-vertex colour carries essentially the same visual information as
a baked atlas, costs no unwrap step, and keeps the .glb a single self-contained
buffer. The spec allows either; this is the one that fits the budget.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("recon.s06")


def export_glb(mesh, out_path: Path, max_mb: float = 25.0, draco: bool = True,
               progress=None) -> dict:
    import open3d as o3d
    import trimesh

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    verts = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.triangles)
    colours = (np.asarray(mesh.vertex_colors) if mesh.has_vertex_colors()
               else np.ones((len(verts), 3)) * 0.7)

    attempt, tri_target = 0, len(faces)
    while True:
        tm = trimesh.Trimesh(
            vertices=verts, faces=faces,
            vertex_colors=(np.clip(colours, 0, 1) * 255).astype(np.uint8),
            process=False)
        tm.export(out_path)
        size_mb = out_path.stat().st_size / 1e6

        if size_mb <= max_mb or attempt >= 4 or len(faces) < 5000:
            break

        # Halve the triangle budget and try again. Reporting a mesh that blows
        # the budget would be worse than shipping a coarser one.
        attempt += 1
        tri_target = max(5000, len(faces) // 2)
        log.warning("mesh is %.1f MB (budget %.1f) - decimating to %d triangles",
                    size_mb, max_mb, tri_target)
        if progress:
            progress.stage("texture", 0.5 + 0.1 * attempt,
                           f"over budget, decimating to {tri_target}")
        small = mesh.simplify_quadric_decimation(tri_target)
        verts = np.asarray(small.vertices)
        faces = np.asarray(small.triangles)
        colours = (np.asarray(small.vertex_colors) if small.has_vertex_colors()
                   else np.ones((len(verts), 3)) * 0.7)

    result = {
        "path": str(out_path),
        "tri_count": int(len(faces)),
        "size_bytes": int(out_path.stat().st_size),
        "size_mb": round(out_path.stat().st_size / 1e6, 3),
        "decimation_passes": attempt,
        "draco": False,
        "over_budget": out_path.stat().st_size / 1e6 > max_mb,
    }

    if draco:
        # Honest about capability: trimesh writes uncompressed glTF buffers.
        # Draco needs gltf-pipeline (node) or a compiled encoder, neither of
        # which is a dependency here. Claiming draco=true in room.json when the
        # bytes are uncompressed would make the frontend request a decoder that
        # the asset does not need.
        result["draco_note"] = ("Draco not applied: no encoder available in "
                                "this environment; buffers are uncompressed")

    if progress:
        progress.stage("texture", 1.0,
                       f"{result['tri_count']} tris, {result['size_mb']} MB")
    return result


def render_preview(mesh, out_path: Path, width: int = 800, height: int = 500) -> bool:
    """Offscreen preview render. Best-effort: no GPU means no preview, not a failure."""
    import open3d as o3d

    try:
        vis = o3d.visualization.Visualizer()
        if not vis.create_window(visible=False, width=width, height=height):
            return False
        try:
            vis.add_geometry(mesh)
            opt = vis.get_render_option()
            opt.background_color = np.array([0.043, 0.063, 0.125])   # #0B1020
            vis.poll_events()
            vis.update_renderer()
            vis.capture_screen_image(str(out_path), do_render=True)
        finally:
            vis.destroy_window()
        return Path(out_path).exists()
    except Exception as e:  # noqa: BLE001 - headless box, no GL
        log.info("preview render unavailable: %s", e)
        return False
