"""Image-to-3D backend interface (spec 10B.3).

Same shape as the on-device inference factory in Phase 8: one ABC, several
implementations, a factory that probes and LOGS ITS CHOICE. pipeline.py must
only ever touch the factory, never a backend module directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import trimesh


class Image3DBackend(ABC):
    name: str

    @abstractmethod
    def available(self) -> bool:
        """Weights present on disk and enough VRAM. Must not raise."""

    @abstractmethod
    def load(self) -> None:
        """Lazy; keep the model warm between jobs."""

    @abstractmethod
    def generate(self, rgba, timeout_s: float) -> trimesh.Trimesh:
        """RGBA cut-out -> unit-normalised mesh. g06 does the metric scaling."""
