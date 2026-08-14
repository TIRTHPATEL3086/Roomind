"""Progress reporting for the reconstruction pipeline (spec 8.7, 10.1).

Two sinks, both optional and both non-fatal:

  stdout   one JSON object per line. This is the channel the Twin Generator
           reads, exactly as imagine_manager reads genai3d's pipeline -- a
           subprocess boundary with a line-delimited contract, so the API
           process never has to import Open3D.
  HTTP     POST to --progress-url, for running the CLI standalone against a
           live server.

A progress report must NEVER be able to fail the run. A three-minute
reconstruction that dies at S09 because a socket closed is strictly worse than
one that finishes silently, so every send is wrapped.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

# Fraction of total wall-clock each stage takes, from the 10.2 budget table.
# Progress is reported against these weights rather than "stage 4 of 10" so the
# bar moves at a roughly constant rate instead of stalling for 45 s on pose.
STAGE_WEIGHTS: dict[str, float] = {
    "ingest": 0.03,
    "pose": 0.28,
    "depth": 0.12,
    "fuse": 0.15,
    "mesh": 0.09,
    "texture": 0.15,
    "detect": 0.06,
    "lift3d": 0.05,
    "floorplan": 0.04,
    "scenegraph": 0.03,
}
STAGE_ORDER = list(STAGE_WEIGHTS)


def _cumulative(stage: str) -> float:
    total = 0.0
    for s in STAGE_ORDER:
        if s == stage:
            return total
        total += STAGE_WEIGHTS[s]
    return total


class Progress:
    def __init__(self, scan_id: str, url: str | None = None, quiet: bool = False):
        self.scan_id = scan_id
        self.url = url
        self.quiet = quiet
        self.started = time.time()
        self._last = -1.0

    def stage(self, stage: str, frac: float = 0.0, note: str = "", **extra) -> None:
        """Report progress WITHIN a stage; frac is 0..1 of that stage."""
        base = _cumulative(stage)
        overall = base + STAGE_WEIGHTS.get(stage, 0.0) * max(0.0, min(1.0, frac))
        # Never go backwards. A stage that re-reports an earlier fraction would
        # make the browser's bar jump left, which reads as a crash.
        overall = max(overall, self._last)
        self._last = overall
        self._emit({
            "scan_id": self.scan_id, "stage": stage,
            "progress": round(overall, 4), "note": note,
            "elapsed_s": round(time.time() - self.started, 2),
            **extra,
        })

    def done(self, **extra) -> None:
        self._last = 1.0
        self._emit({"scan_id": self.scan_id, "stage": "completed", "progress": 1.0,
                    "elapsed_s": round(time.time() - self.started, 2), **extra})

    def failed(self, error: str, stage: str = "failed") -> None:
        self._emit({"scan_id": self.scan_id, "stage": stage, "error": error,
                    "progress": round(self._last, 4),
                    "elapsed_s": round(time.time() - self.started, 2)})

    def _emit(self, payload: dict) -> None:
        line = json.dumps(payload)
        if not self.quiet:
            # Unbuffered: the parent reads these line by line and a buffered
            # pipe would deliver the whole run's progress at once, at the end.
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        if self.url:
            self._post(line)

    def _post(self, line: str) -> None:
        try:
            req = urllib.request.Request(
                self.url, data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=2.0).close()
        except (urllib.error.URLError, OSError, ValueError):
            pass  # see module docstring: reporting must never fail the run
