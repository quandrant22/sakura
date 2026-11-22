"""desktop.core.game_hud.telemetry.lol — Провайдер Riot Live Client Data API (League of Legends)."""

from __future__ import annotations

import logging
import time
from typing import Optional

from desktop.core.game_hud.telemetry.base import TelemetryProvider
from desktop.core.game_hud.types import GameState

log = logging.getLogger("sakura.game_hud.lol")


class LolTelemetryProvider(TelemetryProvider):
    def __init__(self, lol_poller=None):
        self.lol_poller = lol_poller
        self._last_state: Optional[GameState] = None

    def is_available(self) -> bool:
        return self.lol_poller is not None

    def start(self) -> None:
        if self.lol_poller:
            self.lol_poller.start()

    def stop(self) -> None:
        if self.lol_poller:
            self.lol_poller.stop()

    def get_state(self) -> Optional[GameState]:
        if not self.lol_poller:
            return None
        cur = getattr(self.lol_poller, "last_data", {}) or {}
        if not cur:
            return self._last_state

        now = time.time()
        active_player = cur.get("activePlayer") or {}
        champ_stats = active_player.get("championStats") or {}

        metrics = {}
        cur_hp = champ_stats.get("currentHealth")
        max_hp = champ_stats.get("maxHealth")
        if cur_hp is not None and max_hp:
            metrics["hp"] = round(float(cur_hp) / max(1.0, float(max_hp)) * 100.0, 1)

        cur_mana = champ_stats.get("resourceValue")
        max_mana = champ_stats.get("resourceMax")
        if cur_mana is not None and max_mana:
            metrics["mana"] = round(float(cur_mana) / max(1.0, float(max_mana)) * 100.0, 1)

        scores = cur.get("scores") or {}
        if "kills" in scores:
            metrics["kills"] = int(scores["kills"])
        if "deaths" in scores:
            metrics["deaths"] = int(scores["deaths"])

        st = GameState(
            game_id="league_of_legends",
            game_name="League of Legends",
            metrics=metrics,
            timestamp=now,
            source="telemetry",
        )
        st.update_summary()
        self._last_state = st
        return st
