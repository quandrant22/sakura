"""desktop.core.features — Единая точка доступа к подсистемам Сакуры (Capri Suite).

Объединяет:
- HuskManager (Husk Mode для CLI-агентов)
- GameSenseDetector (мгновенные игровые реакции)
- LookoutEngine (фоновый визуальный дозор)
- ClipBuffer (голосовое клипирование в MP4)
- InkManager (рисование поверх экрана)
- CallModeManager & MicMixManager (режим звонков и виртуальный микрофон)
- WatchAlongManager (совместный просмотр)
- CareManager (система заботы о пользователе)
"""

from __future__ import annotations

import logging
from typing import Optional

from desktop.core.call_mode import CallModeManager
from desktop.core.care import CareManager
from desktop.core.clips import ClipBuffer
from desktop.core.gamesense import GameSenseDetector, GameSenseRunner, get_gamesense_runner
from desktop.core.husk import HuskManager
from desktop.core.ink import InkManager
from desktop.core.lookout import LookoutEngine
from desktop.core.loopback_speech import LoopbackSpeechListener
from desktop.core.mic_mix import MicMixManager
from desktop.core.watch_along import WatchAlongManager

log = logging.getLogger("sakura.features")

_husk_manager: Optional[HuskManager] = None
_gamesense_detector: Optional[GameSenseDetector] = None
_lookout_engine: Optional[LookoutEngine] = None
_clip_buffer: Optional[ClipBuffer] = None
_ink_manager: Optional[InkManager] = None
_call_mode_manager: Optional[CallModeManager] = None
_mic_mix_manager: Optional[MicMixManager] = None
_watch_along_manager: Optional[WatchAlongManager] = None
_care_manager: Optional[CareManager] = None
_loopback_speech_listener: Optional[LoopbackSpeechListener] = None


def get_husk_manager() -> HuskManager:
    global _husk_manager
    if _husk_manager is None:
        _husk_manager = HuskManager()
    return _husk_manager

get_husk_agent_bridge = get_husk_manager


def get_gamesense_detector() -> GameSenseDetector:
    return get_gamesense_runner().detector


def get_lookout_engine() -> LookoutEngine:
    global _lookout_engine
    if _lookout_engine is None:
        _lookout_engine = LookoutEngine()
    return _lookout_engine


def get_clip_buffer() -> ClipBuffer:
    global _clip_buffer
    if _clip_buffer is None:
        _clip_buffer = ClipBuffer()
    return _clip_buffer


def get_ink_manager() -> InkManager:
    global _ink_manager
    if _ink_manager is None:
        _ink_manager = InkManager()
    return _ink_manager


def get_call_mode_manager() -> CallModeManager:
    global _call_mode_manager
    if _call_mode_manager is None:
        _call_mode_manager = CallModeManager()
    return _call_mode_manager


def get_mic_mix_manager() -> MicMixManager:
    global _mic_mix_manager
    if _mic_mix_manager is None:
        _mic_mix_manager = MicMixManager()
    return _mic_mix_manager


def get_watch_along_manager() -> WatchAlongManager:
    global _watch_along_manager
    if _watch_along_manager is None:
        _watch_along_manager = WatchAlongManager()
    return _watch_along_manager


def get_care_manager() -> CareManager:
    global _care_manager
    if _care_manager is None:
        _care_manager = CareManager()
    return _care_manager


def get_loopback_speech_listener() -> LoopbackSpeechListener:
    global _loopback_speech_listener
    if _loopback_speech_listener is None:
        _loopback_speech_listener = LoopbackSpeechListener()
    return _loopback_speech_listener
