"""desktop.core.game_hud.cv_utils — Утилиты компьютерного зрения для быстрого локального HUD-трекинга."""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger("sakura.game_hud.cv")

# Базовые цветовые профили (HSV: H=0..179, S=0..255, V=0..255)
COLOR_HINTS_HSV = {
    "lime": ([30, 80, 80], [85, 255, 255]),
    "green": ([35, 70, 70], [85, 255, 255]),
    "red": ([0, 100, 100], [10, 255, 255]),      # Red wrapping: также [170..179]
    "red_alt": ([170, 100, 100], [180, 255, 255]),
    "blue": ([95, 80, 80], [135, 255, 255]),
    "cyan": ([80, 80, 80], [105, 255, 255]),
    "yellow": ([18, 90, 90], [35, 255, 255]),
    "orange": ([10, 100, 100], [25, 255, 255]),
    "white": ([0, 0, 180], [180, 50, 255]),
}


def sample_bar_color(
    crop_bgr: np.ndarray,
    color_hint: str = "",
) -> Tuple[list[int], list[int]]:
    """Автоматически калибрует диапазон HSV для полоски по ее реальному кропу."""
    if crop_bgr is None or crop_bgr.size == 0:
        return [30, 70, 70], [85, 255, 255]

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    hint = (color_hint or "").strip().lower()

    if hint in COLOR_HINTS_HSV:
        lower, upper = COLOR_HINTS_HSV[hint]
        # Проверяем, есть ли подходящие пиксели
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        if np.sum(mask > 0) > 10:
            return list(lower), list(upper)

    # Авто-подбор по доминирующему насыщенному цвету (S > 70, V > 70)
    s_mask = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 70)
    if np.sum(s_mask) >= 15:
        h_vals = hsv[:, :, 0][s_mask]
        s_vals = hsv[:, :, 1][s_mask]
        v_vals = hsv[:, :, 2][s_mask]

        med_h = int(np.median(h_vals))
        lower_h = max(0, med_h - 18)
        upper_h = min(179, med_h + 18)
        lower_s = max(60, int(np.percentile(s_vals, 15)) - 15)
        lower_v = max(60, int(np.percentile(v_vals, 15)) - 15)

        return [lower_h, lower_s, lower_v], [upper_h, 255, 255]

    # Fallback на зеленый/лайм
    return [30, 70, 70], [85, 255, 255]


def calculate_bar_fill(
    crop_bgr: np.ndarray,
    orientation: str = "ltr",
    hsv_lower: Optional[list[int]] = None,
    hsv_upper: Optional[list[int]] = None,
    color_hint: str = "",
) -> float:
    """Вычисляет процент заполнения полоски (0.0..100.0%) по цветовой маске."""
    if crop_bgr is None or crop_bgr.size == 0:
        return 0.0

    h, w = crop_bgr.shape[:2]
    if h == 0 or w == 0:
        return 0.0

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)

    if hsv_lower and hsv_upper:
        mask = cv2.inRange(hsv, np.array(hsv_lower, dtype=np.uint8), np.array(hsv_upper, dtype=np.uint8))
        # Для красного цвета захватываем оба диапазона (0..10 и 170..179)
        if hsv_lower[0] < 15 and hsv_upper[0] < 30:
            alt_mask = cv2.inRange(hsv, np.array([170, hsv_lower[1], hsv_lower[2]]), np.array([180, 255, 255]))
            mask = cv2.bitwise_or(mask, alt_mask)
    else:
        lower, upper = sample_bar_color(crop_bgr, color_hint)
        mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))

    ori = orientation.lower()

    if ori in ("ltr", "rtl", "center_out"):
        # Горизонтальный анализ по колонкам
        col_counts = np.sum(mask > 0, axis=0)
        min_density = max(2, int(h * 0.25))
        filled_cols = np.where(col_counts >= min_density)[0]

        if len(filled_cols) == 0:
            return 0.0

        if ori == "ltr":
            # Идем слева направо: ищем длину непрерывного заполнения от левого края
            start_x = filled_cols[0]
            end_x = start_x
            for c in filled_cols:
                if c <= end_x + 3:
                    end_x = c
                else:
                    break
            total_span = w - start_x
            if total_span <= 0:
                return 0.0
            fill = (end_x - start_x + 1) / float(total_span) * 100.0
            return max(0.0, min(100.0, float(fill)))

        elif ori == "rtl":
            # Идем справа налево
            end_x = filled_cols[-1]
            start_x = end_x
            for c in reversed(filled_cols):
                if c >= start_x - 3:
                    start_x = c
                else:
                    break
            total_span = end_x + 1
            if total_span <= 0:
                return 0.0
            fill = (end_x - start_x + 1) / float(total_span) * 100.0
            return max(0.0, min(100.0, float(fill)))

        elif ori == "center_out":
            mid_x = w // 2
            left_fill = 0
            right_fill = 0
            for c in range(mid_x, -1, -1):
                if col_counts[c] >= min_density:
                    left_fill += 1
                else:
                    break
            for c in range(mid_x, w):
                if col_counts[c] >= min_density:
                    right_fill += 1
                else:
                    break
            fill = (left_fill + right_fill) / float(w) * 100.0
            return max(0.0, min(100.0, float(fill)))

    elif ori == "btt":
        # Вертикальный анализ снизу вверх
        row_counts = np.sum(mask > 0, axis=1)
        min_density = max(2, int(w * 0.25))
        filled_rows = np.where(row_counts >= min_density)[0]
        if len(filled_rows) == 0:
            return 0.0
        # Снизу вверх: максимальный y — это низ
        bot_y = filled_rows[-1]
        top_y = bot_y
        for r in reversed(filled_rows):
            if r >= top_y - 3:
                top_y = r
            else:
                break
        fill = (bot_y - top_y + 1) / float(h) * 100.0
        return max(0.0, min(100.0, float(fill)))

    # Fallback: общее соотношение пикселей
    total_px = h * w
    if total_px == 0:
        return 0.0
    return float(np.sum(mask > 0)) / float(total_px) * 100.0


def preprocess_crop(
    crop_bgr: np.ndarray,
    mode: str = "rgb",
    scale: float = 2.0,
) -> np.ndarray:
    """Подготовка кропа изображения для локального OCR."""
    if crop_bgr is None or crop_bgr.size == 0:
        return crop_bgr

    # Апскейл для повышения точности OCR на мелких игровых цифрах
    if scale > 1.0:
        h, w = crop_bgr.shape[:2]
        crop_bgr = cv2.resize(crop_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    mode = (mode or "rgb").lower()

    if mode == "otsu":
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.cvtColor(thresh, cv2.COLOR_GRAY2RGB)

    elif mode == "invert":
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        inv = cv2.bitwise_not(gray)
        return cv2.cvtColor(inv, cv2.COLOR_GRAY2RGB)

    # "rgb" — без слепой бинаризации, чтобы сохранить цвет и полупрозрачный HUD
    return cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)


def parse_number_from_text(text: str) -> Optional[float]:
    """Извлекает числовое значение из распознанного текста (например: '124 km/h' -> 124.0, '30/90' -> 30.0)."""
    if not text:
        return None
    # Очищаем текст
    t = text.strip().replace(",", ".")
    # Ищем первое число (целое или с плавающей точкой)
    m = re.search(r"[-+]?\d+(?:\.\d+)?", t)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            pass
    return None
