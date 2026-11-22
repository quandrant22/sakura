"""desktop.core.game_hud.telemetry.ets2 — Провайдер телеметрии для Euro Truck Simulator 2."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Optional

from desktop.core.game_hud.telemetry.base import TelemetryProvider
from desktop.core.game_hud.types import GameState

log = logging.getLogger("sakura.game_hud.ets2")

ETS2_LOCAL_API = "http://127.0.0.1:25555/api/ets2/telemetry"


class Ets2TelemetryProvider(TelemetryProvider):
    def __init__(self, api_url: str = ETS2_LOCAL_API):
        self.api_url = api_url
        self.active = False
        self._last_state: Optional[GameState] = None
        self._last_fetch: float = 0.0

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.api_url, headers={"User-Agent": "Sakura-HUD"})
            with urllib.request.urlopen(req, timeout=0.4) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start(self) -> None:
        self.active = True
        log.info("[ets2] Провайдер телеметрии ETS2 активирован")

    def stop(self) -> None:
        self.active = False
        log.info("[ets2] Провайдер телеметрии ETS2 остановлен")

    def get_state(self) -> Optional[GameState]:
        now = time.time()
        # Ограничение частоты опроса до ~5 раз в секунду
        if now - self._last_fetch < 0.18 and self._last_state:
            return self._last_state

        try:
            req = urllib.request.Request(self.api_url, headers={"User-Agent": "Sakura-HUD"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            truck = data.get("truck") or {}
            game = data.get("game") or {}

            speed = round(float(truck.get("speed", 0.0)), 1)
            gear = int(truck.get("displayedGear", 0))
            rpm = int(truck.get("engineRpm", 0))
            fuel_pct = round(float(truck.get("fuel", 0.0)) / max(1.0, float(truck.get("fuelCapacity", 1.0))) * 100.0, 1)
            wear_engine = round(float(truck.get("wearEngine", 0.0)) * 100.0, 1)
            wear_truck = round(float(truck.get("wearTransmission", 0.0) + truck.get("wearCabin", 0.0) + truck.get("wearChassis", 0.0)) / 3.0 * 100.0, 1)

            metrics = {
                "speed": speed,
                "gear": gear,
                "rpm": rpm,
                "fuel_pct": fuel_pct,
                "damage_engine": wear_engine,
                "damage_truck": wear_truck,
                "cruise_control": bool(truck.get("cruiseControlOn", False)),
            }

            trends = {}
            if self._last_state:
                old_spd = self._last_state.metrics.get("speed", 0.0)
                if speed - old_spd > 15:
                    trends["speed"] = "accelerating_fast"
                elif old_spd - speed > 25:
                    trends["speed"] = "braking_hard"

            st = GameState(
                game_id="ets2",
                game_name="Euro Truck Simulator 2",
                metrics=metrics,
                trends=trends,
                timestamp=now,
                source="telemetry",
            )
            st.update_summary()
            self._last_state = st
            self._last_fetch = now
            return st

        except Exception as e:
            log.debug("[ets2] Ошибка чтения телеметрии: %s", e)
            return self._last_state
