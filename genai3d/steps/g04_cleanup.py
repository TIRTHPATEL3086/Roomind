"""G04 - mesh cleanup for neural backends (spec 10B.2).

Not used by the proxy path: primitives are already clean, watertight, and low
poly. This runs only when a neural backend produced raw marching-cubes output.
"""
from __future__ import annotations

import trimesh


def cleanup(mesh: trimesh.Trimesh, max_tris: int = 40000) -> trimesh.Trimesh:
    # Neural meshes often carry small floating fragments; keep the largest body.
    if mesh.body_count > 1:
        parts = mesh.split(only_watertight=False)
        if parts:
            mesh = max(parts, key=lambda m: len(m.faces))

    mesh.remove_unreferenced_vertices()
    mesh.remove_degenerate_faces()
    mesh.remove_duplicate_faces()
    mesh.fill_holes()

    if len(mesh.faces) > max_tris:
        mesh = mesh.simplify_quadric_decimation(max_tris)

    mesh.fix_normals()
    return mesh
