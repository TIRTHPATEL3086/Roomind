"""Access to the backend's pure-Python core modules from the reconstruction venv.

`app.core.colors` and `app.core.spatial` are shared, not duplicated. The scene
graph this pipeline writes is read by the resolver in the API process, and the
two have to agree exactly on what "red" means and on what counts as "near" — a
second copy of either would drift, and the drift would show up as ARIA
confidently walking to the wrong chair rather than as a failing import.

This is the same arrangement firmware/sim already uses for kinematics: one
implementation of the maths, reached over sys.path, with the venvs otherwise
kept apart. It is safe in both directions because both modules are pure stdlib
— importing them pulls in no FastAPI, no SQLAlchemy, and nothing from
`services/`, so the subprocess boundary that keeps Open3D and torch out of the
API process is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core import colors, spatial  # noqa: E402

__all__ = ["colors", "spatial"]
