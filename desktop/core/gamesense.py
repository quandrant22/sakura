"""desktop.core.gamesense — Сверхбыстрый локальный анализ игровых событий (GameSense).

Вдохновлен capri-desktop GameSense.cs. Кадры подаёт GameDirector (только в режиме компаньона и
только пока игра в фокусе), здесь — попиксельная математика на кадре 160×90, без модели и сети:
- "hurt": красная виньетка — края экрана заметно краснее центра и краснее, чем были последние
  секунды, два кадра подряд (красная сцена целиком, красный интерфейс или поворот камеры
  на красную стену — не урон);
- "flash": резкая белая вспышка (взрыв, светошумовая граната);
- "dark": экран ушёл в чёрное и держится — один раз на вход, снова только после того,
  как картинка вернулась (загрузки и катсцены тоже тёмные, поэтому это не «смерть»).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("sakura.gamesense")

try:
    import numpy as np
except ImportError:
    np = None

# Пороги «урона»: доля красных пикселей по краям, перевес краёв над центром, рост над фоном.
HURT_MIN_BORDER = 0.12
HURT_MIN_VIGNETTE = 0.08
HURT_MIN_RISE = 0.07
HURT_FRAMES = 2
# Фон по краям — скользящее среднее (≈2 с при 6 кадрах в секунду).
BASELINE_ALPHA = 0.15
DARK_FRAMES = 4


@dataclass
class GameSenseEvent:
    kind: str  # "hurt", "flash", "dark"
    strength: float = 1.0
    timestamp: float = field(default_factory=time.time)
    message: str = ""


class GameSenseDetector:
    """Детектор игровых событий по сырому буферу пикселей (BGRA)."""

    def __init__(
        self,
        on_event: Optional[Callable[[GameSenseEvent], None]] = None,
        cooldown: float = 4.0,
    ):
        self.on_event = on_event or (lambda ev: log.info("GameSense Event: %s (%f)", ev.kind, ev.strength))
        self.cooldown = cooldown
        self.last_event_time: dict[str, float] = {"hurt": 0.0, "flash": 0.0, "dark": 0.0}
        self.reset()

    def reset(self):
        """Сброс фона: после паузы (игра не в фокусе) первые кадры только набирают фон."""
        self.old_mean = 0.0
        self.old_red_ratio = 0.0
        self.red_baseline: Optional[float] = None
        self.hurt_streak = 0
        self.dark_streak = 0
        self.dark_fired = False
        self.is_first_frame = True

    def feed_frame(self, bgra_bytes: bytes, width: int, height: int, timestamp: Optional[float] = None) -> list[GameSenseEvent]:
        """Обрабатывает кадр шириной width и высотой height в формате BGRA (4 байта на пиксель)."""
        if not bgra_bytes or width <= 0 or height <= 0:
            return []

        ts = timestamp or time.time()
        if np is not None:
            events = self._process_numpy(bgra_bytes, width, height, ts)
        else:
            events = self._process_pure_python(bgra_bytes, width, height, ts)

        for ev in events:
            self.last_event_time[ev.kind] = ts
            self.on_event(ev)
        return events

    def _ready(self, kind: str, ts: float) -> bool:
        return ts - self.last_event_time[kind] >= self.cooldown

    def _dark(self, is_dark: bool, ratio: float, ts: float, events: list) -> None:
        if not is_dark:
            self.dark_streak = 0
            self.dark_fired = False
            return
        self.dark_streak += 1
        if self.dark_streak >= DARK_FRAMES and not self.dark_fired and self._ready("dark", ts):
            self.dark_fired = True
            events.append(GameSenseEvent(kind="dark", strength=ratio, timestamp=ts,
                                         message="Экран потемнел (смерть, загрузка или катсцена)"))

    def _process_numpy(self, bgra_bytes: bytes, width: int, height: int, ts: float) -> list[GameSenseEvent]:
        events: list[GameSenseEvent] = []
        try:
            arr = np.frombuffer(bgra_bytes, dtype=np.uint8).reshape((height, width, 4))
        except ValueError:
            return []

        # Downsample до ~160x90
        step_y = max(1, height // 90)
        step_x = max(1, width // 160)
        sample = arr[::step_y, ::step_x]  # B, G, R, A

        blue = sample[:, :, 0].astype(np.float32)
        green = sample[:, :, 1].astype(np.float32)
        red = sample[:, :, 2].astype(np.float32)
        mean_val = float(np.mean((blue + green + red) / 3.0))

        # 1. Dark: почти весь экран чёрный и держится DARK_FRAMES кадров
        black_ratio = float(np.mean((red < 15) & (green < 15) & (blue < 15)))
        self._dark(black_ratio > 0.92 and mean_val < 14, black_ratio, ts, events)

        # 2. Flash: резкий скачок средней яркости вверх
        if not self.is_first_frame:
            bright_jump = mean_val - self.old_mean
            if bright_jump > 60 and mean_val > 180 and self._ready("flash", ts):
                events.append(GameSenseEvent(kind="flash", strength=bright_jump / 100.0, timestamp=ts,
                                             message="Яркая вспышка на экране"))

        # 3. Hurt: красная виньетка — края краснее центра и краснее обычного
        h_s, w_s = red.shape
        by, bx = max(1, h_s // 6), max(1, w_s // 6)
        border = np.zeros((h_s, w_s), dtype=bool)
        border[:by, :] = True
        border[-by:, :] = True
        border[:, :bx] = True
        border[:, -bx:] = True
        center = np.zeros((h_s, w_s), dtype=bool)
        center[h_s // 3: h_s - h_s // 3, w_s // 3: w_s - w_s // 3] = True

        red_dominant = (red > 100) & (red > green * 1.5) & (red > blue * 1.5)
        rb = float(np.mean(red_dominant[border]))
        rc = float(np.mean(red_dominant[center])) if center.any() else 0.0
        self._hurt(rb, rc, ts, events)

        self.old_mean = mean_val
        self.old_red_ratio = rb
        self.is_first_frame = False
        return events

    def _hurt(self, rb: float, rc: float, ts: float, events: list) -> None:
        base = self.red_baseline
        if base is None:
            self.red_baseline = rb
            return
        hurt_like = rb >= HURT_MIN_BORDER and rb - rc >= HURT_MIN_VIGNETTE and rb - base >= HURT_MIN_RISE
        if hurt_like:
            self.hurt_streak += 1
            if self.hurt_streak == HURT_FRAMES and self._ready("hurt", ts):
                events.append(GameSenseEvent(kind="hurt", strength=rb, timestamp=ts,
                                             message="Получен урон (красные края экрана)"))
        else:
            self.hurt_streak = 0
            # Фон учится только на обычных кадрах — иначе длинная серия урона «станет нормой».
            self.red_baseline = base + BASELINE_ALPHA * (rb - base)

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

        self._dark(black_ratio > 0.92 and mean_val < 14, black_ratio, ts, events)

        if not self.is_first_frame and (mean_val - self.old_mean) > 60 and mean_val > 180 and self._ready("flash", ts):
            events.append(GameSenseEvent(kind="flash", strength=1.0, timestamp=ts))
        # Без numpy края от центра не отделить — «урон» не определяется (ложных срабатываний больше,
        # чем пользы).

        self.old_mean = mean_val
        self.old_red_ratio = red_ratio
        self.is_first_frame = False
        return events
