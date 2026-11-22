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
            "low_hp": 0.0,
        }
        self.old_mean: float = 0.0
        self.old_red_ratio: float = 0.0
        self.is_first_frame = True

        # Отслеживание полоски HP (Scrap Mechanic, Souls, RPG, Action)
        self.hp_bar_locked: Optional[dict] = None
        self.hp_bar_candidate: Optional[dict] = None
        self.hp_bar_candidate_frames: int = 0
        self.low_hp_warned: bool = False

    def reset(self):
        self.old_mean = 0.0
        self.old_red_ratio = 0.0
        self.is_first_frame = True
        for k in self.last_event_time:
            self.last_event_time[k] = 0.0
        self.hp_bar_locked = None
        self.hp_bar_candidate = None
        self.hp_bar_candidate_frames = 0
        self.low_hp_warned = False

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

        # Насыщенный кроваво-красный (виньетка урона): красный доминирует, зеленый и синий низкие
        # Отсекает желтые/оранжевые стены, дерево и элементы интерфейса
        blood_red = (b_red > 130) & (b_green < 80) & (b_blue < 80) & (b_red > (b_green + b_blue) * 1.5)
        red_ratio = float(np.sum(blood_red)) / float(b_red.size)

        if red_ratio > 0.20 and (red_ratio - self.old_red_ratio) > 0.10:
            if ts - self.last_event_time["hurt"] >= self.cooldown:
                events.append(GameSenseEvent(kind="hurt", strength=red_ratio, timestamp=ts, message="Получен урон!"))

        # 4. HP Bar Tracker: полоска здоровья в HUD (Scrap Mechanic, Souls, RPG, Action)
        hp_events = self._check_health_bar(sample, blue, green, red, ts)
        events.extend(hp_events)

        self.old_mean = mean_val
        self.old_red_ratio = red_ratio
        self.is_first_frame = False

        return events

    def _check_health_bar(
        self,
        sample: np.ndarray,
        blue: np.ndarray,
        green: np.ndarray,
        red: np.ndarray,
        ts: float,
    ) -> list[GameSenseEvent]:
        h, w = sample.shape[0], sample.shape[1]
        events: list[GameSenseEvent] = []

        # Цветовые маски здоровья:
        # 1. Лайм / Зеленый (Scrap Mechanic, GTA, Left 4 Dead и др.)
        lime_mask = (green > 110) & (green > red * 1.05) & (green > blue * 1.3) & (blue < 100)
        # 2. Красный (Souls-игры, Cyberpunk, Witcher, Diablo и др.)
        red_mask = (red > 130) & (red > green * 1.4) & (red > blue * 1.4) & (green < 80) & (blue < 80)

        regions = [
            ("bottom_left", int(h * 0.80), int(h * 0.99), int(w * 0.01), int(w * 0.35)),
            ("top_left", int(h * 0.01), int(h * 0.20), int(w * 0.01), int(w * 0.35)),
        ]

        bar_found = None
        max_span = 0

        for reg_name, y1, y2, x1, x2 in regions:
            for color_name, mask in [("lime", lime_mask[y1:y2, x1:x2]), ("red", red_mask[y1:y2, x1:x2])]:
                for ry in range(mask.shape[0]):
                    row = mask[ry, :]
                    cols = np.where(row)[0]
                    if len(cols) >= 3:
                        span = cols.max() - cols.min() + 1
                        density = len(cols) / span
                        if density >= 0.70 and span >= 3:
                            if span > max_span:
                                max_span = span
                                bar_found = {
                                    "region": reg_name,
                                    "color": color_name,
                                    "y": y1 + ry,
                                    "x_start": x1 + cols.min(),
                                    "width": int(span),
                                }

        if self.hp_bar_locked is None:
            if bar_found:
                cand = self.hp_bar_candidate
                if (
                    cand
                    and cand["region"] == bar_found["region"]
                    and cand["color"] == bar_found["color"]
                    and abs(cand["y"] - bar_found["y"]) <= 1
                    and abs(cand["x_start"] - bar_found["x_start"]) <= 2
                ):
                    self.hp_bar_candidate_frames += 1
                    if self.hp_bar_candidate_frames >= 2:
                        self.hp_bar_locked = {
                            "region": bar_found["region"],
                            "color": bar_found["color"],
                            "y": bar_found["y"],
                            "x_start": bar_found["x_start"],
                            "max_w": max(int(bar_found["width"]), 8),
                            "last_w": int(bar_found["width"]),
                        }
                        log.debug("[gamesense] Обнаружена полоска HP: %s", self.hp_bar_locked)
                else:
                    self.hp_bar_candidate = bar_found
                    self.hp_bar_candidate_frames = 1
        else:
            lb = self.hp_bar_locked
            curr_w = 0
            if (
                bar_found
                and bar_found["region"] == lb["region"]
                and bar_found["color"] == lb["color"]
                and abs(bar_found["y"] - lb["y"]) <= 2
            ):
                curr_w = int(bar_found["width"])

            if curr_w > lb["max_w"]:
                lb["max_w"] = curr_w

            drop = (lb["last_w"] - curr_w) / float(lb["max_w"])
            ratio = float(curr_w) / float(lb["max_w"])

            # 1. Резкое падение здоровья
            if drop >= 0.15 and lb["last_w"] > 0:
                if ts - self.last_event_time["hurt"] >= self.cooldown:
                    events.append(
                        GameSenseEvent(
                            kind="hurt",
                            strength=drop,
                            timestamp=ts,
                            message=f"Потеряно {int(drop * 100)}% здоровья!",
                        )
                    )

            # 2. Критически мало здоровья (чуть не умер!)
            if ratio <= 0.28:
                if not self.low_hp_warned or (ts - self.last_event_time["low_hp"] >= 15.0):
                    self.low_hp_warned = True
                    self.last_event_time["low_hp"] = ts
                    events.append(
                        GameSenseEvent(
                            kind="low_hp",
                            strength=ratio,
                            timestamp=ts,
                            message=f"Критически мало здоровья ({int(ratio * 100)}%)!",
                        )
                    )
            elif ratio > 0.40:
                self.low_hp_warned = False

            lb["last_w"] = curr_w

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
            if r > 130 and g < 80 and b < 80 and r > (g + b) * 1.5:
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

        if red_ratio > 0.20 and (red_ratio - self.old_red_ratio) > 0.10:
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
        fps: int = 2,
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
            "low_hp": [
                "Мастер, у тебя почти не осталось ХП! Срочно отхилься!",
                "Осторожно, ты на волоске от смерти!",
                "Здоровье на нуле! Спрячься или лечись, скорее!",
                "ХП горит! Еще один удар — и всё!",
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
        try:
            from desktop.core.screens import FastGrabber
            grabber = FastGrabber()
        except Exception:
            grabber = None

        interval = 1.0 / max(1, min(self.fps, 4))
        try:
            while self.active:
                t0 = time.time()
                try:
                    if grabber is not None:
                        small = grabber.grab_small((160, 90))
                    else:
                        from PIL import ImageGrab
                        img = ImageGrab.grab()
                        small = img.resize((160, 90))
                    rgba = small.convert("RGBA").tobytes()
                    bgra = bytearray(rgba)
                    bgra[0::4], bgra[2::4] = bgra[2::4], bgra[0::4]
                    self.detector.feed_frame(bytes(bgra), 160, 90, t0)
                except Exception as e:
                    log.debug("[gamesense] Capture loop error: %s", e)

                elapsed = time.time() - t0
                sleep_t = max(0.05, interval - elapsed)
                time.sleep(sleep_t)
        finally:
            if grabber is not None:
                grabber.close()

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
