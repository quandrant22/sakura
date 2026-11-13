"""desktop.core.gamesense — Сверхбыстрый локальный анализ игровых событий (GameSense).

Вдохновлен capri-desktop GameSense.cs:
Анализирует сырые кадры экрана (10-20 FPS) попиксельной математикой без отправки в LLM:
- "hurt": резкое покраснение краев/экрана (получение урона).
- "flash": резкая белая вспышка (взрыв / светошумовая граната).
- "dark": экран потемнел почти до нуля (смерть персонажа / fade to black).
- "bar_drop": резкое падение заполненности полоски (HP, щит, выносливость).
- "cut": смена сцены / катсцена.

При обнаружении вызывает коллбэки для мгновенных реплик или звуков Сакуры.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("sakura.gamesense")

try:
    import numpy as np
except ImportError:
    np = None


@dataclass
class GameSenseEvent:
    kind: str  # "hurt", "flash", "dark", "bar_drop", "cut"
    strength: float = 1.0
    timestamp: float = field(default_factory=time.time)
    message: str = ""


class GameSenseDetector:
    """Детектор игровых событий по сырому буферу пикселей (BGRA / RGBA)."""

    def __init__(
        self,
        on_event: Optional[Callable[[GameSenseEvent], None]] = None,
        cooldown: float = 2.5,
    ):
        self.on_event = on_event or (lambda ev: log.info("GameSense Event: %s (%f)", ev.kind, ev.strength))
        self.cooldown = cooldown
        self.last_event_time: dict[str, float] = {
            "hurt": 0.0,
            "flash": 0.0,
            "dark": 0.0,
            "bar_drop": 0.0,
            "cut": 0.0,
        }
        self.old_mean: float = 0.0
        self.old_red_ratio: float = 0.0
        self.is_first_frame = True

    def reset(self):
        self.old_mean = 0.0
        self.old_red_ratio = 0.0
        self.is_first_frame = True
        for k in self.last_event_time:
            self.last_event_time[k] = 0.0

    def feed_frame(self, bgra_bytes: bytes, width: int, height: int, timestamp: Optional[float] = None) -> list[GameSenseEvent]:
        """Обрабатывает кадр шириной width и высотой height в формате BGRA (4 байта на пиксель)."""
        if not bgra_bytes or width <= 0 or height <= 0:
            return []

        ts = timestamp or time.time()
        events: list[GameSenseEvent] = []

        if np is not None:
            events = self._process_numpy(bgra_bytes, width, height, ts)
        else:
            events = self._process_pure_python(bgra_bytes, width, height, ts)

        for ev in events:
            self.last_event_time[ev.kind] = ts
            self.on_event(ev)

        return events

    def _process_numpy(self, bgra_bytes: bytes, width: int, height: int, ts: float) -> list[GameSenseEvent]:
        events: list[GameSenseEvent] = []
        try:
            arr = np.frombuffer(bgra_bytes, dtype=np.uint8).reshape((height, width, 4))
        except ValueError:
            return []

        # Downsample для ультрабыстрого анализа (например, 160x90)
        step_y = max(1, height // 90)
        step_x = max(1, width // 160)
        sample = arr[::step_y, ::step_x]  # B, G, R, A

        blue = sample[:, :, 0].astype(np.float32)
        green = sample[:, :, 1].astype(np.float32)
        red = sample[:, :, 2].astype(np.float32)

        mean_val = float(np.mean((blue + green + red) / 3.0))

        # 1. Dark / Death: >90% пикселей почти черные (<15) и средняя яркость < 12
        black_pixels = np.sum((red < 15) & (green < 15) & (blue < 15))
        total_pixels = red.size
        black_ratio = float(black_pixels) / float(total_pixels)

        if black_ratio > 0.92 and mean_val < 14:
            if ts - self.last_event_time["dark"] >= self.cooldown:
                events.append(GameSenseEvent(kind="dark", strength=black_ratio, timestamp=ts, message="Экран потемнел (смерть или катсцена)"))

        # 2. Flash: резкий скачок средней яркости вверх
        if not self.is_first_frame:
            bright_jump = mean_val - self.old_mean
            if bright_jump > 60 and mean_val > 180:
                if ts - self.last_event_time["flash"] >= self.cooldown:
                    events.append(GameSenseEvent(kind="flash", strength=bright_jump / 100.0, timestamp=ts, message="Яркая вспышка на экране!"))

        # 3. Hurt: резкое покраснение краев экрана (урон в шутерах/экшенах)
        # Проверяем виньетку: полосы сверху/снизу/по бокам
        h_s, w_s = sample.shape[0], sample.shape[1]
        border_mask = np.zeros((h_s, w_s), dtype=bool)
        border_size_y = max(1, h_s // 6)
        border_size_x = max(1, w_s // 6)
        border_mask[:border_size_y, :] = True
        border_mask[-border_size_y:, :] = True
        border_mask[:, :border_size_x] = True
        border_mask[:, -border_size_x:] = True

        b_red = red[border_mask]
        b_green = green[border_mask]
        b_blue = blue[border_mask]

        # Пиксели, где красный существенно преобладает над синим и зеленым
        red_dominant = (b_red > 100) & (b_red > (b_green * 1.5)) & (b_red > (b_blue * 1.5))
        red_ratio = float(np.sum(red_dominant)) / float(b_red.size)

        if red_ratio > 0.15 and (red_ratio - self.old_red_ratio) > 0.08:
            if ts - self.last_event_time["hurt"] >= self.cooldown:
                events.append(GameSenseEvent(kind="hurt", strength=red_ratio, timestamp=ts, message="Получен урон!"))

        self.old_mean = mean_val
        self.old_red_ratio = red_ratio
        self.is_first_frame = False

        return events

    def _process_pure_python(self, bgra_bytes: bytes, width: int, height: int, ts: float) -> list[GameSenseEvent]:
        events: list[GameSenseEvent] = []
        # Fallback без numpy
        stride = 4 * max(1, width // 80)
        total_samples = 0
        sum_val = 0
        red_dominant_count = 0
        black_count = 0

        for i in range(0, len(bgra_bytes), stride):
            if i + 3 >= len(bgra_bytes):
                break
            b = bgra_bytes[i]
            g = bgra_bytes[i + 1]
            r = bgra_bytes[i + 2]
            lum = (b + g + r) // 3
            sum_val += lum
            total_samples += 1
            if r < 15 and g < 15 and b < 15:
                black_count += 1
            if r > 100 and r > (g * 1.5) and r > (b * 1.5):
                red_dominant_count += 1

        if total_samples == 0:
            return []

        mean_val = sum_val / total_samples
        black_ratio = black_count / total_samples
        red_ratio = red_dominant_count / total_samples

        if black_ratio > 0.92 and mean_val < 14:
            if ts - self.last_event_time["dark"] >= self.cooldown:
                events.append(GameSenseEvent(kind="dark", strength=black_ratio, timestamp=ts))

        if not self.is_first_frame and (mean_val - self.old_mean) > 60 and mean_val > 180:
            if ts - self.last_event_time["flash"] >= self.cooldown:
                events.append(GameSenseEvent(kind="flash", strength=1.0, timestamp=ts))

        if red_ratio > 0.15 and (red_ratio - self.old_red_ratio) > 0.08:
            if ts - self.last_event_time["hurt"] >= self.cooldown:
                events.append(GameSenseEvent(kind="hurt", strength=red_ratio, timestamp=ts))

        self.old_mean = mean_val
        self.old_red_ratio = red_ratio
        self.is_first_frame = False
        return events


class GameSenseRunner:
    """Фоновый захват экрана и анализ игровых событий (Hurt, Flash, Dark/Death)."""

    def __init__(
        self,
        detector: Optional[GameSenseDetector] = None,
        on_reaction: Optional[Callable[[GameSenseEvent, str], None]] = None,
        on_event: Optional[Callable[[GameSenseEvent], None]] = None,
        fps: int = 10,
    ):
        self.detector = detector or GameSenseDetector()
        self.on_reaction = on_reaction
        self.on_event = on_event
        self.fps = fps
        self.active = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_reaction_time = 0.0
        self.reaction_gap = 4.0  # минимум 4 секунды между репликами Сакуры

        # Подключаем внутренний обработчик детектора
        self.detector.on_event = self._handle_event

    def start(self):
        with self._lock:
            if self.active:
                return
            self.active = True
            self.detector.reset()
            self._thread = threading.Thread(target=self._run_loop, name="GameSenseRunner", daemon=True)
            self._thread.start()
            log.info("[gamesense] Фоновый анализатор запущен (fps=%d)", self.fps)

    def stop(self):
        with self._lock:
            self.active = False
            self._thread = None
            log.info("[gamesense] Фоновый анализатор остановлен")

    def _handle_event(self, ev: GameSenseEvent):
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception as e:
                log.debug("[gamesense] on_event error: %s", e)

        now = time.time()
        if now - self.last_reaction_time < self.reaction_gap:
            return

        import random
        phrases = {
            "hurt": [
                "Мастер, аккуратнее, тебя задели!",
                "Куда под пули прёшь?! ХП улетает!",
                "Тебя коцают, отойди в укрытие!",
            ],
            "flash": [
                "Ой, мои глаза! Кто светошумовую кинул?!",
                "Белый экран! Осторожно, ты ослеп!",
            ],
            "dark": [
                "Ну вот, приехали. Опять на респаун?",
                "Великолепный тактический ход... прямо на кладбище.",
                "Капец. Ты погиб, Мастер.",
            ],
        }

        choices = phrases.get(ev.kind)
        if choices:
            self.last_reaction_time = now
            chosen = random.choice(choices)
            log.info("[gamesense] Реакция на %s: %s", ev.kind, chosen)
            if self.on_reaction:
                try:
                    self.on_reaction(ev, chosen)
                except Exception as e:
                    log.warning("[gamesense] on_reaction error: %s", e)

    def _run_loop(self):
        from PIL import ImageGrab
        interval = 1.0 / max(1, self.fps)
        while self.active:
            t0 = time.time()
            try:
                # Быстрый захват кадра и сжатие в 160x90 для минимального использования процессора
                img = ImageGrab.grab()
                small = img.resize((160, 90))
                # RGBA байты
                rgba = small.convert("RGBA").tobytes()
                # Для BGRA переставляем каналы (или подаем напрямую в детектор)
                # В numpy-версии детектора sample[:, :, 0] = Blue, 1 = Green, 2 = Red
                # Преобразуем RGBA в BGRA байты
                bgra = bytearray(rgba)
                bgra[0::4], bgra[2::4] = bgra[2::4], bgra[0::4]
                self.detector.feed_frame(bytes(bgra), 160, 90, t0)
            except Exception as e:
                log.debug("[gamesense] Capture loop error: %s", e)

            elapsed = time.time() - t0
            sleep_t = max(0.02, interval - elapsed)
            time.sleep(sleep_t)


# Синглтон
_gamesense_runner: Optional[GameSenseRunner] = None


def get_gamesense_runner() -> GameSenseRunner:
    global _gamesense_runner
    if _gamesense_runner is None:
        _gamesense_runner = GameSenseRunner()
    return _gamesense_runner
