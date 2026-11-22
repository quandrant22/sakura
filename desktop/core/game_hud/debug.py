"""desktop.core.game_hud.debug — Режим отладки и визуальной калибровки HUD-разметки."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import cv2
import numpy as np

from desktop.core.game_hud.types import GameState, HudProfile

log = logging.getLogger("sakura.game_hud.debug")

DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "debug")


def render_debug_frame(
    frame_bgr: np.ndarray,
    profile: HudProfile,
    game_state: Optional[GameState] = None,
    save_path: Optional[str] = None,
) -> str:
    """Отрисовывает поверх кадра игры границы элементов HUD, распознанные значения и статус.
    Сохраняет debug-скриншот на диск для мгновенной 5-секундной проверки.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return ""

    debug_img = frame_bgr.copy()
    h, w = debug_img.shape[:2]
    metrics = game_state.metrics if game_state else {}

    # Цветовая палитра BGR
    COLORS = {
        "bar": (50, 220, 50),       # Ярко-зеленый
        "number": (240, 180, 20),   # Бирюзово-синий
        "text": (40, 220, 240),     # Желтый
        "region": (220, 50, 220),   # Пурпурный
    }

    # 1. Отрисовка каждого элемента HUD
    for elem in profile.elements:
        x1, y1, x2, y2 = elem.bbox_px
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(x1 + 1, min(w, x2))
        y2 = max(y1 + 1, min(h, y2))

        color = COLORS.get(elem.type, (200, 200, 200))
        val = metrics.get(elem.id)

        # Рамка элемента
        cv2.rectangle(debug_img, (x1, y1), (x2, y2), color, 2)

        # Заливка для полоски
        if elem.type == "bar" and isinstance(val, (int, float)):
            fill_pct = min(100.0, max(0.0, float(val)))
            fill_w = int((x2 - x1) * fill_pct / 100.0)
            overlay = debug_img.copy()
            cv2.rectangle(overlay, (x1, y1), (x1 + fill_w, y2), color, -1)
            cv2.addWeighted(overlay, 0.35, debug_img, 0.65, 0, debug_img)
            text_val = f"{elem.label}: {val:.1f}% ({elem.orientation})"
        elif elem.type == "number":
            unit = f" {elem.unit}" if elem.unit else ""
            text_val = f"{elem.label}: {val}{unit}" if val is not None else f"{elem.label}: [?]"
        else:
            text_val = f"{elem.label}: '{val}'" if val is not None else f"{elem.label}"

        # Плашка с текстом над элементом
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (tw, th), baseline = cv2.getTextSize(text_val, font, font_scale, thickness)

        label_y1 = max(0, y1 - th - 6)
        label_y2 = y1
        label_x2 = min(w, x1 + tw + 8)

        # Темная подложка под текст
        cv2.rectangle(debug_img, (x1, label_y1), (label_x2, label_y2), (20, 20, 20), -1)
        cv2.rectangle(debug_img, (x1, label_y1), (label_x2, label_y2), color, 1)
        cv2.putText(debug_img, text_val, (x1 + 4, label_y2 - 4), font, font_scale, (255, 255, 255), thickness)

    # 2. Верхняя информационная панель со сводкой GameState
    banner_h = 36
    overlay = debug_img.copy()
    cv2.rectangle(overlay, (0, 0), (w, banner_h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.85, debug_img, 0.15, 0, debug_img)

    summary_str = game_state.summary if game_state and game_state.summary else f"{profile.game_name} ({w}x{h})"
    trends_str = f" | Тренды: {game_state.trends}" if game_state and game_state.trends else ""
    full_banner = f"Sakura Game Awareness [DEBUG] | {summary_str}{trends_str}"

    cv2.putText(debug_img, full_banner, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 240, 255), 2)

    # 3. Сохранение файла
    if not save_path:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in profile.game_id.lower())
        save_path = os.path.join(DEBUG_DIR, f"hud_debug_{safe_id}.png")

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    cv2.imwrite(save_path, debug_img)
    log.info("[hud_debug] Отладочный скриншот успешно сохранен: %s", save_path)
    return save_path
