"""desktop.core.game_hud.types — Типы данных и схемы для Game Awareness & HUD Tracking."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class HudElementType(str, Enum):
    BAR = "bar"
    NUMBER = "number"
    TEXT = "text"
    REGION = "region"


class BarOrientation(str, Enum):
    LTR = "ltr"          # Слева направо (стандарт)
    RTL = "rtl"          # Справа налево
    BTT = "btt"          # Снизу вверх (вертикальные бары)
    CENTER_OUT = "center_out"  # От центра к краям


class PreprocessMode(str, Enum):
    RGB = "rgb"          # Без бинаризации — сохраняет цвета полупрозрачного HUD
    OTSU = "otsu"        # Адаптивный порог Otsu для высококонтрастных цифр
    INVERT = "invert"    # Инверсия (для светлых цифр на темном фоне)


class ReaderType(str, Enum):
    LOCAL_CV = "local_cv"    # OpenCV HSV/контуры (для баров)
    LOCAL_OCR = "local_ocr"  # RapidOCR-ONNX (быстрый локальный)
    VLM_CROP = "vlm_crop"    # Gemini 3.1 Flash-Lite для стилизованных/сложных шрифтов


@dataclass
class HudElementConfig:
    id: str
    type: str  # "bar", "number", "text", "region"
    label: str
    bbox_1000: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # [ymin, xmin, ymax, xmax] 0..1000
    bbox_px: list[int] = field(default_factory=lambda: [0, 0, 0, 0])    # [x1, y1, x2, y2] в пикселях окна
    color_hint: str = ""
    hsv_lower: Optional[list[int]] = None  # [H, S, V] lower
    hsv_upper: Optional[list[int]] = None  # [H, S, V] upper
    orientation: str = BarOrientation.LTR.value
    preprocess: str = PreprocessMode.RGB.value
    reader: str = ReaderType.LOCAL_CV.value
    padding: int = 6
    unit: str = ""
    min_val: float = 0.0
    max_val: float = 100.0
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HudElementConfig:
        return cls(
            id=str(data.get("id", "element")),
            type=str(data.get("type", "bar")),
            label=str(data.get("label", "")),
            bbox_1000=list(data.get("bbox_1000") or [0, 0, 0, 0]),
            bbox_px=list(data.get("bbox_px") or [0, 0, 0, 0]),
            color_hint=str(data.get("color_hint", "")),
            hsv_lower=list(data["hsv_lower"]) if data.get("hsv_lower") is not None else None,
            hsv_upper=list(data["hsv_upper"]) if data.get("hsv_upper") is not None else None,
            orientation=str(data.get("orientation", BarOrientation.LTR.value)),
            preprocess=str(data.get("preprocess", PreprocessMode.RGB.value)),
            reader=str(data.get("reader", ReaderType.LOCAL_CV.value if data.get("type") == "bar" else ReaderType.LOCAL_OCR.value)),
            padding=int(data.get("padding", 6)),
            unit=str(data.get("unit", "")),
            min_val=float(data.get("min_val", 0.0)),
            max_val=float(data.get("max_val", 100.0)),
            active=bool(data.get("active", True)),
        )


@dataclass
class HudProfile:
    game_id: str
    game_name: str
    resolution: list[int]  # [width, height]
    elements: list[HudElementConfig] = field(default_factory=list)
    version: str = "1.0"
    created_at: float = field(default_factory=time.time)
    custom_edited: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "game_name": self.game_name,
            "resolution": self.resolution,
            "version": self.version,
            "created_at": self.created_at,
            "custom_edited": self.custom_edited,
            "elements": [e.to_dict() for e in self.elements],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HudProfile:
        elements = [HudElementConfig.from_dict(e) for e in (data.get("elements") or [])]
        return cls(
            game_id=str(data.get("game_id", "")),
            game_name=str(data.get("game_name", "")),
            resolution=list(data.get("resolution") or [1920, 1080]),
            elements=elements,
            version=str(data.get("version", "1.0")),
            created_at=float(data.get("created_at", time.time())),
            custom_edited=bool(data.get("custom_edited", False)),
        )

    def save(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        tmp = filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)

    @classmethod
    def load(cls, filepath: str) -> Optional[HudProfile]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception:
            return None


@dataclass
class GameState:
    game_id: str
    game_name: str
    metrics: dict[str, Any] = field(default_factory=dict)
    trends: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = "hud"  # "hud" или "telemetry"
    summary: str = ""

    def update_summary(self) -> str:
        parts = []
        for k, v in self.metrics.items():
            if isinstance(v, float):
                parts.append(f"{k}: {v:.1f}")
            else:
                parts.append(f"{k}: {v}")
        self.summary = f"{self.game_name} | " + ", ".join(parts) if parts else self.game_name
        return self.summary

    def has_changed_significantly(self, other: Optional[GameState], threshold: float = 2.0) -> bool:
        """Проверяет, изменилось ли состояние достаточно сильно для отправки по WebSocket (diff-based)."""
        if other is None:
            return True
        if self.game_id != other.game_id or self.source != other.source:
            return True

        # Сравниваем метрики
        for k, v in self.metrics.items():
            if k not in other.metrics:
                return True
            ov = other.metrics[k]
            if isinstance(v, (int, float)) and isinstance(ov, (int, float)):
                if abs(float(v) - float(ov)) >= threshold:
                    return True
            elif v != ov:
                return True

        for k in other.metrics:
            if k not in self.metrics:
                return True

        return False
