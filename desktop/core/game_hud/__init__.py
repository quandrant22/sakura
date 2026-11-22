"""desktop.core.game_hud — Модуль Game Awareness & Real-Time HUD Tracking для Сакуры."""

from desktop.core.game_hud.brain import GameHudDirector
from desktop.core.game_hud.debug import render_debug_frame
from desktop.core.game_hud.mapper import AutoHudMapper
from desktop.core.game_hud.tracker import HudTracker
from desktop.core.game_hud.types import (
    BarOrientation,
    GameState,
    HudElementConfig,
    HudElementType,
    HudProfile,
    PreprocessMode,
    ReaderType,
)

__all__ = [
    "GameHudDirector",
    "AutoHudMapper",
    "HudTracker",
    "HudProfile",
    "HudElementConfig",
    "GameState",
    "HudElementType",
    "BarOrientation",
    "PreprocessMode",
    "ReaderType",
    "render_debug_frame",
]
