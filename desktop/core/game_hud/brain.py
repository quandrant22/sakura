"""desktop.core.game_hud.brain — Менеджер Game Awareness, триггеры событий и diff-рассылка GameState."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

import cv2
import numpy as np

from desktop.core.game_hud.debug import render_debug_frame
from desktop.core.game_hud.dpi import ensure_dpi_aware
from desktop.core.game_hud.mapper import AutoHudMapper
from desktop.core.game_hud.telemetry.registry import get_telemetry_provider
from desktop.core.game_hud.tracker import HudTracker
from desktop.core.game_hud.types import GameState, HudProfile

log = logging.getLogger("sakura.game_hud.brain")


class GameHudDirector:
    """Оркестратор игрового интерфейса: объединяет телеметрию, Fast HUD Tracker, триггеры и diff-рассылку."""

    def __init__(
        self,
        on_event: Optional[Callable[[str, str], None]] = None,
        on_state_update: Optional[Callable[[dict], None]] = None,
        fps: float = 3.0,
    ):
        self.on_event = on_event or (lambda kind, detail: log.info("[hud_brain] Event: %s (%s)", kind, detail))
        self.on_state_update = on_state_update or (lambda state_dict: None)
        self.fps = fps
        self.active = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self.current_game_key: str = ""
        self.current_game_name: str = ""
        self.active_profile: Optional[HudProfile] = None
        self.telemetry_provider = None
        self.tracker: Optional[HudTracker] = None
        self.mapper = AutoHudMapper()

        self.last_state: Optional[GameState] = None
        self.last_sent_state: Optional[GameState] = None
        self.last_heartbeat_time: float = 0.0
        self.heartbeat_interval: float = 12.0  # Редкий heartbeat (12 сек)

        # Кулдауны событий
        self.cooldowns: dict[str, float] = {
            "low_hp": 15.0,
            "hurt": 2.5,
            "out_of_ammo": 10.0,
            "overspeed": 20.0,
            "crash": 15.0,
        }
        self.last_event_time: dict[str, float] = {k: 0.0 for k in self.cooldowns}
        self.low_hp_warned: bool = False

        # Windows DPI Awareness
        ensure_dpi_aware()

    def start_session(self, game_key: str, game_name: str, fg_info: Optional[dict] = None):
        """Запуск сессии слежения за игрой."""
        with self._lock:
            self.current_game_key = game_key
            self.current_game_name = game_name
            self.last_state = None
            self.last_sent_state = None
            self.low_hp_warned = False
            self.active = True
            self._stop.clear()

            # 1. Проверяем наличие адаптера нативной телеметрии (CS2, LoL, ETS2)
            self.telemetry_provider = get_telemetry_provider(game_key)
            if self.telemetry_provider:
                log.info("[hud_brain] Используется нативная телеметрия для %s", game_name)
                self.telemetry_provider.start()
            else:
                log.info("[hud_brain] Нативная телеметрия отсутствует, активируется Auto-HUD Tracker для %s", game_name)
                self.telemetry_provider = None

            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="GameHudBrain", daemon=True)
                self._thread.start()

    def stop_session(self):
        """Остановка сессии слежения."""
        with self._lock:
            self.active = False
            self._stop.set()
            if self.telemetry_provider:
                self.telemetry_provider.stop()
                self.telemetry_provider = None
            self.tracker = None
            self.active_profile = None
            log.info("[hud_brain] Сессия HUD-трекинга остановлена")

    def rescan_hud(self):
        """Принудительное пересканирование HUD через VLM по хоткею или команде."""
        with self._lock:
            if not self.active or not self.current_game_key:
                return
            log.info("[hud_brain] Принудительное пересканирование интерфейса для %s...", self.current_game_name)
            self.active_profile = None
            self.tracker = None

    def capture_debug(self, save_path: Optional[str] = None) -> str:
        """Делает моментальный снимок игры и сохраняет визуальный debug-скриншот."""
        try:
            from desktop.core.screens import FastGrabber
            grabber = FastGrabber()
            pil_img = grabber.grab()
            grabber.close()

            arr_rgb = np.array(pil_img)
            bgr = cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2BGR)

            if not self.active_profile:
                # Если профиль еще не создан, создаем/загружаем его
                self.active_profile = self.mapper.get_or_create_profile(
                    self.current_game_key or "game",
                    self.current_game_name or "Игра",
                    arr_rgb,
                )

            st = self.last_state
            if not st and self.tracker:
                st = self.tracker.process_frame(bgr)

            return render_debug_frame(bgr, self.active_profile, st, save_path)
        except Exception as e:
            log.warning("[hud_brain] Ошибка захвата debug-кадра: %s", e)
            return ""

    def _loop(self):
        from desktop.core.screens import FastGrabber
        grabber = FastGrabber()
        interval = 1.0 / max(1.0, min(self.fps, 10.0))

        log.info("[hud_brain] Цикл HUD-трекинга запущен (FPS=%.1f)", self.fps)

        try:
            while self.active and not self._stop.is_set():
                t0 = time.time()
                try:
                    state: Optional[GameState] = None

                    # Вариант А: Чтение из TelemetryProvider
                    if self.telemetry_provider:
                        state = self.telemetry_provider.get_state()

                    # Вариант Б: Захват экрана и локальный HUD Tracker
                    else:
                        pil_img = grabber.grab()
                        arr_rgb = np.array(pil_img)
                        bgr = cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2BGR)

                        if self.active_profile is None:
                            self.active_profile = self.mapper.get_or_create_profile(
                                self.current_game_key,
                                self.current_game_name,
                                arr_rgb,
                            )
                            self.tracker = HudTracker(self.active_profile)

                        if self.tracker is not None:
                            state = self.tracker.process_frame(bgr, timestamp=t0)

                    if state is not None:
                        self.last_state = state
                        # 1. Проверяем и запускаем триггеры событий
                        self._check_triggers(state, t0)
                        # 2. Diff-рассылка по WebSocket (+ редкий heartbeat)
                        self._check_diff_broadcast(state, t0)

                except Exception as e:
                    log.debug("[hud_brain] Ошибка в цикле трекинга: %s", e)

                elapsed = time.time() - t0
                sleep_t = max(0.02, interval - elapsed)
                time.sleep(sleep_t)

        finally:
            grabber.close()
            log.info("[hud_brain] Цикл HUD-трекинга завершен")

    def _check_triggers(self, state: GameState, now: float):
        """Проверка пороговых значений и запуск реплик Сакуры с защитой от спама."""
        metrics = state.metrics
        trends = state.trends

        # 1. Здоровье: критически мало (low_hp)
        hp = metrics.get("hp") or metrics.get("hp_bar") or metrics.get("health")
        if hp is not None and isinstance(hp, (int, float)):
            if hp <= 25.0:
                if not self.low_hp_warned or (now - self.last_event_time["low_hp"] >= self.cooldowns["low_hp"]):
                    self.low_hp_warned = True
                    self.last_event_time["low_hp"] = now
                    self.on_event("low_hp", f"{int(hp)}% HP")
            elif hp > 40.0:
                self.low_hp_warned = False

            # Резкое падение ХП
            if trends.get("hp") == "dropping_fast" or trends.get("hp_bar") == "dropping_fast":
                if now - self.last_event_time["hurt"] >= self.cooldowns["hurt"]:
                    self.last_event_time["hurt"] = now
                    self.on_event("hurt", f"резко упало до {int(hp)}%")

        # 2. Патроны: закончились
        ammo = metrics.get("ammo") or metrics.get("ammo_counter")
        if ammo is not None and isinstance(ammo, (int, float)) and ammo == 0:
            if now - self.last_event_time["out_of_ammo"] >= self.cooldowns["out_of_ammo"]:
                self.last_event_time["out_of_ammo"] = now
                self.on_event("out_of_ammo", "патроны на нуле")

        # 3. Скорость: превышение или резкое торможение/авария
        speed = metrics.get("speed") or metrics.get("speedometer")
        if speed is not None and isinstance(speed, (int, float)):
            if trends.get("speed") == "braking_hard" or trends.get("speedometer") == "braking_hard":
                if now - self.last_event_time["crash"] >= self.cooldowns["crash"]:
                    self.last_event_time["crash"] = now
                    self.on_event("crash", f"резкая остановка с {int(speed)} км/ч")

    def _check_diff_broadcast(self, state: GameState, now: float):
        """Отправка состояния только при реальном изменении (diff) или по таймеру heartbeat."""
        should_send = False

        if state.has_changed_significantly(self.last_sent_state):
            should_send = True
        elif now - self.last_heartbeat_time >= self.heartbeat_interval:
            should_send = True

        if should_send:
            self.last_sent_state = state
            self.last_heartbeat_time = now
            payload = {
                "type": "game_state_update",
                "game_id": state.game_id,
                "game_name": state.game_name,
                "source": state.source,
                "metrics": dict(state.metrics),
                "trends": dict(state.trends),
                "summary": state.summary,
                "timestamp": state.timestamp,
            }
            try:
                self.on_state_update(payload)
            except Exception as e:
                log.debug("[hud_brain] Ошибка on_state_update: %s", e)
