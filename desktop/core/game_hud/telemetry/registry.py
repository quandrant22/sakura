"""desktop.core.game_hud.telemetry.registry — Реестр адаптеров нативной телеметрии."""

from __future__ import annotations

from typing import Optional

from desktop.core.game_hud.telemetry.base import TelemetryProvider
from desktop.core.game_hud.telemetry.ets2 import Ets2TelemetryProvider
from desktop.core.game_hud.telemetry.gsi import ValveGsiTelemetryProvider
from desktop.core.game_hud.telemetry.lol import LolTelemetryProvider

_ets2_provider: Optional[Ets2TelemetryProvider] = None


def get_telemetry_provider(game_key: str, gsi_server=None, lol_poller=None) -> Optional[TelemetryProvider]:
    """Возвращает адаптер телеметрии для игры, если она поддерживает нативный API."""
    global _ets2_provider
    k = (game_key or "").lower().strip()

    if "eurotrucks2.exe" in k or "ets2" in k:
        if _ets2_provider is None:
            _ets2_provider = Ets2TelemetryProvider()
        return _ets2_provider

    if "cs2.exe" in k:
        return ValveGsiTelemetryProvider("cs2", "Counter-Strike 2", gsi_server)

    if "dota2.exe" in k:
        return ValveGsiTelemetryProvider("dota2", "Dota 2", gsi_server)

    if "league of legends.exe" in k:
        return LolTelemetryProvider(lol_poller)

    return None
