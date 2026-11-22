"""desktop.core.game_hud.mapper — Авто-разметка интерфейса игры (Auto-HUD Mapper) через Gemini 3.5 Flash-Lite."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from typing import Any, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from desktop.core.game_hud.cv_utils import sample_bar_color
from desktop.core.game_hud.types import (
    BarOrientation,
    HudElementConfig,
    HudElementType,
    HudProfile,
    PreprocessMode,
    ReaderType,
)

log = logging.getLogger("sakura.game_hud.mapper")

PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "profiles")


def get_profile_path(game_id: str, width: int, height: int) -> str:
    safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in game_id.lower())
    return os.path.join(PROFILES_DIR, f"{safe_id}_{width}x{height}.json")


def denormalize_bbox(
    bbox_1000: list[int],
    width: int,
    height: int,
    padding: int = 6,
    is_bar: bool = False,
) -> list[int]:
    """Конвертирует нативный формат Gemini [ymin, xmin, ymax, xmax] 0..1000 в физические пиксели [x1, y1, x2, y2]."""
    if len(bbox_1000) != 4:
        return [0, 0, width, height]

    ymin, xmin, ymax, xmax = bbox_1000
    pad = 2 if is_bar else padding

    x1 = max(0, int(xmin * width / 1000.0) - pad)
    y1 = max(0, int(ymin * height / 1000.0) - pad)
    x2 = min(width, int(xmax * width / 1000.0) + pad)
    y2 = min(height, int(ymax * height / 1000.0) + pad)

    return [x1, y1, max(x1 + 1, x2), max(y1 + 1, y2)]


class AutoHudMapper:
    """Генератор разметки игрового интерфейса с кэшированием в profiles/."""

    def __init__(self, send_server_func=None):
        self.send_server = send_server_func

    def get_or_create_profile(
        self,
        game_id: str,
        game_name: str,
        frame_rgb: np.ndarray,
        force_rescan: bool = False,
        genre: str = "",
    ) -> HudProfile:
        """Загружает профиль из локального кэша или запускает 1-кратный VLM-анализ."""
        h, w = frame_rgb.shape[:2]
        profile_path = get_profile_path(game_id, w, h)

        if not force_rescan and os.path.exists(profile_path):
            loaded = HudProfile.load(profile_path)
            if loaded and len(loaded.elements) > 0:
                log.info("[hud_mapper] Загружен готовый профиль из кэша: %s (%d элементов)", profile_path, len(loaded.elements))
                return loaded

        log.info("[hud_mapper] Кэш не найден или запрошен рескан. Запуск VLM Auto-HUD Mapper для %s (%dx%d)...", game_name, w, h)
        profile = self.map_frame_with_vlm(game_id, game_name, frame_rgb, genre)
        profile.save(profile_path)
        log.info("[hud_mapper] Профиль успешно размечен и сохранен: %s", profile_path)
        return profile

    def map_frame_with_vlm(
        self,
        game_id: str,
        game_name: str,
        frame_rgb: np.ndarray,
        genre: str = "",
    ) -> HudProfile:
        """Отправляет кадр в Gemini 3.5 Flash-Lite со Structured Output JSON Schema."""
        h, w = frame_rgb.shape[:2]

        # Подтягиваем имя модели из config.py без хардкода
        try:
            import config
            model_name = getattr(config, "MAIN_MODEL", "gemini-3.5-flash-lite")
        except Exception:
            model_name = "gemini-3.5-flash-lite"

        # Системный промпт с жестким требованием формата боксов [ymin, xmin, ymax, xmax] 0..1000
        prompt = (
            f"You are an expert game HUD analyzer. Identify key HUD/UI elements for the game '{game_name}' ({genre}).\n"
            "Return a strictly valid JSON matching the schema.\n"
            "CRITICAL: Bounding boxes MUST use Gemini native format [ymin, xmin, ymax, xmax] in normalized 0..1000 coordinates.\n"
            "Find elements such as:\n"
            "- Health / HP bar (type: 'bar', color_hint: 'lime'/'green'/'red', orientation: 'ltr')\n"
            "- Shield / Armor bar (type: 'bar', color_hint: 'blue'/'cyan')\n"
            "- Stamina / Energy / Boost bar (type: 'bar', color_hint: 'yellow'/'orange')\n"
            "- Speedometer / Speed (type: 'number', unit: 'km/h')\n"
            "- Gear / RPM (type: 'number' or 'text')\n"
            "- Ammo / Magazine counter (type: 'number')\n"
            "- Hotbar / Inventory toolbar items (type: 'number' or 'region')\n"
            "- Compass / Minimap (type: 'region')"
        )

        elements_data = []

        # Попытка вызова локально через google.genai, если есть ключ
        vlm_success = False
        try:
            from sakura_core.llm import generate
            from google.genai import types as T

            # Превращаем кадр в JPEG байты
            pil_img = Image.fromarray(frame_rgb)
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            jpeg_bytes = buf.getvalue()

            schema = {
                "type": "OBJECT",
                "properties": {
                    "elements": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "id": {"type": "STRING"},
                                "type": {"type": "STRING", "enum": ["bar", "number", "text", "region"]},
                                "label": {"type": "STRING"},
                                "bbox_1000": {
                                    "type": "ARRAY",
                                    "items": {"type": "INTEGER"},
                                    "description": "[ymin, xmin, ymax, xmax] normalized 0..1000",
                                },
                                "color_hint": {"type": "STRING"},
                                "orientation": {"type": "STRING", "enum": ["ltr", "rtl", "btt", "center_out"]},
                                "preprocess": {"type": "STRING", "enum": ["rgb", "otsu", "invert"]},
                                "unit": {"type": "STRING"},
                                "reader": {"type": "STRING", "enum": ["local_cv", "local_ocr", "vlm_crop"]},
                            },
                            "required": ["id", "type", "label", "bbox_1000"],
                        },
                    }
                },
                "required": ["elements"],
            }

            import asyncio
            resp_text = asyncio.run(
                generate(
                    [
                        T.Part(inline_data=T.Blob(mime_type="image/jpeg", data=jpeg_bytes)),
                        T.Part(text=prompt),
                    ],
                    model=model_name,
                    response_mime_type="application/json",
                    max_tokens=1000,
                    safety=False,
                    thinking=False,
                )
            )

            parsed = json.loads(resp_text)
            elements_data = parsed.get("elements") or []
            vlm_success = True
            log.info("[hud_mapper] VLM успешно вернул %d элементов интерфейса", len(elements_data))

        except Exception as e:
            log.warning("[hud_mapper] Прямой VLM вызов не удался (%s). Применяем эвристическую калибровку.", e)

        # Fallback-эвристика для известных игр (например, Scrap Mechanic), если VLM недоступен
        if not vlm_success or not elements_data:
            elements_data = self._heuristic_fallback(game_id, w, h)

        # Конвертируем сырые данные в HudElementConfig с денормализацией и калибровкой HSV
        bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        configs = []

        for ed in elements_data:
            el_type = ed.get("type", "bar")
            is_bar = (el_type == "bar")
            bbox_1000 = ed.get("bbox_1000") or [0, 0, 0, 0]
            bbox_px = denormalize_bbox(bbox_1000, w, h, padding=6, is_bar=is_bar)

            x1, y1, x2, y2 = bbox_px
            crop = bgr[y1:y2, x1:x2]

            hsv_lower, hsv_upper = None, None
            color_hint = ed.get("color_hint", "")

            if is_bar:
                hsv_lower, hsv_upper = sample_bar_color(crop, color_hint)

            cfg = HudElementConfig(
                id=str(ed.get("id", f"elem_{len(configs)+1}")),
                type=el_type,
                label=str(ed.get("label", ed.get("id", ""))),
                bbox_1000=bbox_1000,
                bbox_px=bbox_px,
                color_hint=color_hint,
                hsv_lower=hsv_lower,
                hsv_upper=hsv_upper,
                orientation=str(ed.get("orientation", BarOrientation.LTR.value)),
                preprocess=str(ed.get("preprocess", PreprocessMode.RGB.value)),
                reader=str(ed.get("reader", ReaderType.LOCAL_CV.value if is_bar else ReaderType.LOCAL_OCR.value)),
                padding=6,
                unit=str(ed.get("unit", "")),
            )
            configs.append(cfg)

        return HudProfile(
            game_id=game_id,
            game_name=game_name,
            resolution=[w, h],
            elements=configs,
            version="1.0",
            created_at=time.time(),
        )

    def _heuristic_fallback(self, game_id: str, w: int, h: int) -> list[dict]:
        """Точная встроенная геометрия для Scrap Mechanic и стандартных шутеров/симуляторов."""
        gid = game_id.lower()
        if "scrap" in gid or "mechanic" in gid:
            return [
                {
                    "id": "hp_bar",
                    "type": "bar",
                    "label": "Здоровье",
                    "bbox_1000": [945, 46, 990, 150],
                    "color_hint": "lime",
                    "orientation": "ltr",
                    "preprocess": "rgb",
                    "reader": "local_cv",
                },
                {
                    "id": "hotbar_slot4_count",
                    "type": "number",
                    "label": "Слот 4 (Морковь)",
                    "bbox_1000": [940, 415, 980, 435],
                    "orientation": "ltr",
                    "preprocess": "rgb",
                    "reader": "local_ocr",
                },
            ]
        # Общий fallback: полоска здоровья в левом нижнем углу
        return [
            {
                "id": "hp_bar",
                "type": "bar",
                "label": "Здоровье",
                "bbox_1000": [920, 20, 970, 200],
                "color_hint": "lime",
                "orientation": "ltr",
                "preprocess": "rgb",
                "reader": "local_cv",
            }
        ]
