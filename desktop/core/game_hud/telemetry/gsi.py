"""desktop.core.game_hud.telemetry.gsi — Провайдер Valve Game State Integration (CS2, Dota 2)."""

from __future__ import annotations

import logging
import time
from typing import Optional

from desktop.core.game_hud.telemetry.base import TelemetryProvider
from desktop.core.game_hud.types import GameState

log = logging.getLogger("sakura.game_hud.gsi")


class ValveGsiTelemetryProvider(TelemetryProvider):
    def __init__(self, game_id: str, game_name: str, gsi_server=None):
        self.game_id = game_id
        self.game_name = game_name
        self.gsi_server = gsi_server
        self._last_state: Optional[GameState] = None

    def is_available(self) -> bool:
        return self.gsi_server is not None and getattr(self.gsi_server, "_running", False)

    def start(self) -> None:
        if self.gsi_server and not getattr(self.gsi_server, "_running", False):
            self.gsi_server.start()

    def stop(self) -> None:
        pass

    def get_state(self) -> Optional[GameState]:
        if not self.gsi_server:
            return None
        cur = getattr(self.gsi_server, "last_state", {}) or {}
        if not cur:
            return self._last_state

        now = time.time()
        player = cur.get("player") or {}
        state = player.get("state") or {}

        metrics = {}
        if "health" in state:
            metrics["hp"] = float(state["health"])
        if "armor" in state:
            metrics["armor"] = float(state["armor"])
        if "round_kills" in state:
            metrics["kills"] = int(state["round_kills"])
        if "money" in state:
            metrics["money"] = int(state["money"])

        trends = {}
        if self._last_state and "hp" in metrics and "hp" in self._last_state.metrics:
            diff = self._last_state.metrics["hp"] - metrics["hp"]
            if diff >= 20:
                trends["hp"] = "dropping_fast"

        st = GameState(
            game_id=self.game_id,
            game_name=self.game_name,
            metrics=metrics,
            trends=trends,
            timestamp=now,
            source="telemetry",
        )
        st.update_summary()
        self._last_state = st
        return st
