"""desktop.core.screens — «экран Сакуры»: какой монитор она смотрит, на каком рисует и где живёт оверлей.

Мониторов может быть несколько. Интерфейс (Electron знает все дисплеи) сохраняет выбор в настройке
`target_display` = {"id", "label", "x", "y", "width", "height"} — границы в физических пикселях
виртуального рабочего стола Windows. Без выбора — основной монитор (как раньше).

Все захваты экрана в ядре (скриншот для модели, зрение, Lookout, клипы, игровой анализ) берут кадр
через grab() — то есть с выбранного монитора. Координаты рисования (Ink) задаются в пикселях
последнего снимка: оверлей сам переводит их в свои, поэтому DPI и масштаб снимка не важны.

Быстрый захват для игр (fast_grabber): mss, если установлен (десятки кадров в секунду), иначе PIL.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

log = logging.getLogger("sakura.screens")

SETTING_KEY = "target_display"


@dataclass(frozen=True)
class Bounds:
    x: int
    y: int
    width: int
    height: int

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


_lock = threading.Lock()
_target: Optional[Bounds] = None
_target_meta: dict = {}
# Размер последнего снимка, ушедшего модели (после уменьшения) — система координат для Ink.
_last_shot_size: Optional[tuple[int, int]] = None


def parse_target(value: Any) -> Optional[Bounds]:
    """Настройка target_display → Bounds; мусор и нулевые размеры → None (основной монитор)."""
    if not isinstance(value, dict):
        return None
    try:
        b = Bounds(int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"]))
    except (KeyError, TypeError, ValueError):
        return None
    if b.width < 64 or b.height < 64 or b.width > 20000 or b.height > 20000:
        return None
    return b


def set_target(value: Any) -> Optional[Bounds]:
    """Применить выбор монитора (из настроек). None — основной монитор."""
    global _target, _target_meta
    b = parse_target(value)
    with _lock:
        _target = b
        _target_meta = {k: value.get(k) for k in ("id", "label")} if (b and isinstance(value, dict)) else {}
    log.info("[screens] экран Сакуры: %s", f"{b.width}x{b.height} @ {b.x},{b.y}" if b else "основной")
    return b


def target() -> Optional[Bounds]:
    with _lock:
        return _target


def describe() -> dict:
    """Для статуса и ответов: какой монитор выбран."""
    b = target()
    with _lock:
        meta = dict(_target_meta)
    return {"selected": b is not None, **meta, **(b.as_dict() if b else {})}


def grab(grabber: Callable[..., Any] | None = None):
    """Кадр выбранного монитора (PIL.Image) или основного, если выбора нет."""
    if grabber is None:
        from PIL import ImageGrab
        grabber = ImageGrab.grab
    b = target()
    if b is None:
        return grabber(all_screens=False)
    return grabber(bbox=b.bbox, all_screens=True)


def note_shot_size(width: int, height: int) -> None:
    """Запомнить размер снимка, который увидела модель: её координаты для Ink — в этих пикселях."""
    global _last_shot_size
    if width > 0 and height > 0:
        _last_shot_size = (int(width), int(height))


def ink_space() -> dict:
    """Система координат рисования: размер снимка, который видела модель, иначе — размер монитора."""
    if _last_shot_size:
        return {"w": _last_shot_size[0], "h": _last_shot_size[1]}
    b = target()
    if b:
        return {"w": b.width, "h": b.height}
    return {"w": 0, "h": 0}  # 0 — оверлей считает точки своими пикселями


class FastGrabber:
    """Частый захват выбранного монитора для игрового анализа: mss (быстро) или PIL (запасной путь).

    grab_small(size) — уменьшенный RGB-кадр (PIL.Image) для попиксельной математики GameSense.
    """

    def __init__(self, backend: str | None = None):
        self._mss = None
        self.backend = "pil"
        if backend in (None, "mss"):
            try:
                import mss  # type: ignore
                self._mss = mss.mss()
                self.backend = "mss"
            except Exception:  # noqa: BLE001 — нет mss или нет дисплея
                self._mss = None

    def _region(self) -> dict | None:
        b = target()
        if b is not None:
            return {"left": b.x, "top": b.y, "width": b.width, "height": b.height}
        if self._mss is not None:
            mons = self._mss.monitors
            return dict(mons[1]) if len(mons) > 1 else dict(mons[0])
        return None

    def grab(self):
        from PIL import Image
        if self._mss is not None:
            region = self._region()
            shot = self._mss.grab(region)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return grab()

    def grab_small(self, size: tuple[int, int] = (160, 90)):
        img = self.grab().convert("RGB")
        return img.resize(size)

    def close(self):
        try:
            if self._mss is not None:
                self._mss.close()
        except Exception:  # noqa: BLE001
            pass
