"""desktop.core.game_hud.tracker — Быстрый локальный трекер игрового HUD (3-5 FPS) на OpenCV и RapidOCR."""

from __future__ import annotations

import collections
import io
import logging
import time
from typing import Any, Callable, Optional

import cv2
import numpy as np
from PIL import Image

from desktop.core.game_hud.cv_utils import calculate_bar_fill, parse_number_from_text, preprocess_crop
from desktop.core.game_hud.types import GameState, HudElementConfig, HudProfile, ReaderType

log = logging.getLogger("sakura.game_hud.tracker")

# Ленивая инициализация RapidOCR, чтобы не тратить память, если игра использует телеметрию
_rapid_ocr = None


def get_ocr():
    global _rapid_ocr
    if _rapid_ocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_ocr = RapidOCR()
            log.info("[hud_tracker] RapidOCR успешно загружен")
        except Exception as e:
            log.warning("[hud_tracker] Ошибка загрузки RapidOCR: %s", e)
            _rapid_ocr = False
    return _rapid_ocr if _rapid_ocr is not False else None


class HudTracker:
    """Выполняет быстрый ROI-захват и распознавание метрик по кэшированному профилю."""

    def __init__(self, profile: HudProfile, vlm_crop_reader: Optional[Callable[[bytes], str]] = None):
        self.profile = profile
        self.vlm_crop_reader = vlm_crop_reader
        # Буфер последних 3 измерений для медианного сглаживания (debounce)
        self._history: dict[str, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=3))
        # История для вычисления трендов (падение ХП, ускорение)
        self._time_series: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
        self.last_state: Optional[GameState] = None

    def process_frame(self, frame_bgr: np.ndarray, timestamp: Optional[float] = None) -> GameState:
        """Обрабатывает текущий кадр и возвращает актуальный GameState."""
        ts = timestamp or time.time()
        metrics: dict[str, Any] = {}
        trends: dict[str, str] = {}

        if frame_bgr is None or frame_bgr.size == 0:
            return self.last_state or GameState(
                game_id=self.profile.game_id,
                game_name=self.profile.game_name,
                metrics={},
                timestamp=ts,
            )

        h_frame, w_frame = frame_bgr.shape[:2]

        for elem in self.profile.elements:
            if not elem.active:
                continue

            x1, y1, x2, y2 = elem.bbox_px
            # Проверка границ кропа
            x1 = max(0, min(w_frame - 1, x1))
            y1 = max(0, min(h_frame - 1, y1))
            x2 = max(x1 + 1, min(w_frame, x2))
            y2 = max(y1 + 1, min(h_frame, y2))

            crop = frame_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            val: Any = None

            # 1. Полоска (Bar) через OpenCV HSV
            if elem.type == "bar":
                raw_fill = calculate_bar_fill(
                    crop,
                    orientation=elem.orientation,
                    hsv_lower=elem.hsv_lower,
                    hsv_upper=elem.hsv_upper,
                    color_hint=elem.color_hint,
                )
                self._history[elem.id].append(raw_fill)
                # Медианный фильтр по 3 кадрам сглаживает единичные помехи
                val = round(float(np.median(self._history[elem.id])), 1)

            # 2. Число (Number) или Текст (Text)
            elif elem.type in ("number", "text"):
                raw_text = ""

                # Опциональный VLM-Crop для стилизованных игровых шрифтов
                if elem.reader == ReaderType.VLM_CROP.value and self.vlm_crop_reader:
                    try:
                        # Конвертируем маленький кроп в компактный JPEG (2-4 КБ)
                        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                        pil_crop = Image.fromarray(crop_rgb)
                        buf = io.BytesIO()
                        pil_crop.save(buf, format="JPEG", quality=85)
                        raw_text = self.vlm_crop_reader(buf.getvalue())
                    except Exception as e:
                        log.debug("[hud_tracker] vlm_crop error on %s: %s", elem.id, e)

                # Стандартный локальный OCR (RapidOCR)
                if not raw_text:
                    ocr = get_ocr()
                    if ocr is not None:
                        # Препроцессинг без слепой бинаризации Otsu по умолчанию
                        prepared = preprocess_crop(crop, mode=elem.preprocess, scale=2.0)
                        try:
                            results, _ = ocr(prepared)
                            if results and len(results) > 0:
                                raw_text = " ".join(r[1] for r in results if len(r) > 1 and r[1])
                        except Exception as e:
                            log.debug("[hud_tracker] OCR inference error: %s", e)

                if elem.type == "number":
                    parsed_num = parse_number_from_text(raw_text)
                    if parsed_num is not None:
                        self._history[elem.id].append(parsed_num)
                        val = float(np.median(self._history[elem.id]))
                    elif len(self._history[elem.id]) > 0:
                        # Если в текущем кадре не прочиталось, держим предыдущее значение
                        val = self._history[elem.id][-1]
                    else:
                        val = None
                else:
                    val = raw_text.strip()

            if val is not None:
                metrics[elem.id] = val

                # Запись в историю для вычисления трендов
                if isinstance(val, (int, float)):
                    self._record_time_series(elem.id, ts, float(val))

        # Вычисление трендов (падение HP, резкое ускорение/торможение)
        trends = self._compute_trends(ts)

        st = GameState(
            game_id=self.profile.game_id,
            game_name=self.profile.game_name,
            metrics=metrics,
            trends=trends,
            timestamp=ts,
            source="hud",
        )
        st.update_summary()
        self.last_state = st
        return st

    def _record_time_series(self, metric_id: str, ts: float, val: float):
        history = self._time_series[metric_id]
        history.append((ts, val))
        # Храним историю за последние 3 секунды
        self._time_series[metric_id] = [pt for pt in history if ts - pt[0] <= 3.0]

    def _compute_trends(self, now: float) -> dict[str, str]:
        trends = {}
        # Тренд здоровья
        for hp_key in ("hp", "hp_bar", "health", "health_bar"):
            if hp_key in self._time_series:
                pts = self._time_series[hp_key]
                if len(pts) >= 2:
                    oldest_val = pts[0][1]
                    newest_val = pts[-1][1]
                    delta = oldest_val - newest_val
                    time_span = pts[-1][0] - pts[0][0]
                    if delta >= 15.0 and time_span <= 2.5:
                        trends[hp_key] = "dropping_fast"
                    elif newest_val <= 25.0:
                        trends[hp_key] = "critical"
                    elif newest_val > oldest_val + 10.0:
                        trends[hp_key] = "healing"

        # Тренд скорости
        for spd_key in ("speed", "speedometer"):
            if spd_key in self._time_series:
                pts = self._time_series[spd_key]
                if len(pts) >= 2:
                    diff = pts[-1][1] - pts[0][1]
                    if diff > 25.0:
                        trends[spd_key] = "accelerating_fast"
                    elif diff < -35.0:
                        trends[spd_key] = "braking_hard"

        return trends
