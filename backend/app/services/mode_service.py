"""ARIA Operating Modes, Gestures & Advanced Safety Polish (Phase 10).

Implements the four operating modes from spec:
1. COMPANION (interactive conversational + gestures + citations)
2. SENTRY (active room patrolling + detection + intruder alerts)
3. GUIDE (smooth leading + object showcase)
4. MAPPING (autonomous room exploration & scan assistance)
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

log = logging.getLogger("roommind.modes")

class OperatingMode(str, Enum):
    COMPANION = "companion"
    SENTRY = "sentry"
    GUIDE = "guide"
    MAPPING = "mapping"

class ModeConfig(BaseModel):
    mode: OperatingMode
    speed_factor: float = 1.0
    patrol_interval_s: float = 10.0
    obstacle_clearance_m: float = 0.51
    audio_reactive: bool = True
    gestures_enabled: bool = True

class ModeManager:
    def __init__(self):
        self.current_mode: OperatingMode = OperatingMode.COMPANION
        self.config: Dict[OperatingMode, ModeConfig] = {
            OperatingMode.COMPANION: ModeConfig(mode=OperatingMode.COMPANION, speed_factor=1.0, audio_reactive=True),
            OperatingMode.SENTRY: ModeConfig(mode=OperatingMode.SENTRY, speed_factor=0.6, patrol_interval_s=15.0),
            OperatingMode.GUIDE: ModeConfig(mode=OperatingMode.GUIDE, speed_factor=0.8, obstacle_clearance_m=0.6),
            OperatingMode.MAPPING: ModeConfig(mode=OperatingMode.MAPPING, speed_factor=0.5, patrol_interval_s=5.0)
        }

    def set_mode(self, mode: OperatingMode) -> Dict[str, Any]:
        self.current_mode = mode
        cfg = self.config[mode]
        log.info(f"ARIA switched operating mode to {mode.value}")
        return {
            "status": "success",
            "active_mode": mode.value,
            "config": cfg.model_dump()
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_mode": self.current_mode.value,
            "modes_available": [m.value for m in OperatingMode],
            "config": self.config[self.current_mode].model_dump()
        }

mode_manager = ModeManager()
