"""desktop.core.ocr — текст с экрана встроенным OCR Windows (Windows.Media.Ocr), без сети и без модели.

Нужен Lookout («скажи, когда будет 100 %») и игровым подсказкам: кадр выбранного монитора
(screens.grab) → текст. Языки — языки профиля Windows (русский и английский, если установлены).
На других системах или без winsdk — None (Lookout честно сообщает, что следить нечем).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

log = logging.getLogger("sakura.ocr")

# Больше OCR не нужно: мелкий текст читается и при 2560 по длинной стороне, а время растёт квадратично.
MAX_SIDE = 2560

_engine = None
_unavailable = False


def available() -> bool:
    try:
        import winsdk.windows.media.ocr  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _get_engine():
    global _engine, _unavailable
    if _engine is None and not _unavailable:
        try:
            from winsdk.windows.media.ocr import OcrEngine
            _engine = OcrEngine.try_create_from_user_profile_languages()
            if _engine is None:
                _unavailable = True
                log.warning("[ocr] в Windows нет языков распознавания (Параметры → Время и язык → Язык)")
        except Exception as e:  # noqa: BLE001
            _unavailable = True
            log.info("[ocr] Windows OCR недоступен: %s", type(e).__name__)
    return _engine


def _prepare(img: Any):
    img = img.convert("RGBA")
    w, h = img.size
    k = min(1.0, MAX_SIDE / max(w, h))
    if k < 1.0:
        img = img.resize((max(1, int(w * k)), max(1, int(h * k))))
    return img


async def recognize_async(img: Any) -> Optional[str]:
    engine = _get_engine()
    if engine is None:
        return None
    from winsdk.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winsdk.windows.storage.streams import DataWriter

    img = _prepare(img)
    w, h = img.size
    writer = DataWriter()
    writer.write_bytes(img.tobytes("raw", "BGRA"))
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
    result = await engine.recognize_async(bitmap)
    return (result.text or "") if result is not None else ""


def recognize(img: Any) -> Optional[str]:
    """Синхронно (из рабочего потока): текст кадра или None, если OCR недоступен."""
    if _get_engine() is None:
        return None
    try:
        return asyncio.run(recognize_async(img))
    except Exception as e:  # noqa: BLE001
        log.warning("[ocr] не распознано: %s", type(e).__name__)
        return None


def screen_text() -> Optional[str]:
    """Текст выбранного монитора (screens.grab) — для Lookout."""
    from desktop.core import screens
    try:
        img = screens.grab()
    except Exception as e:  # noqa: BLE001
        log.warning("[ocr] захват экрана: %s", type(e).__name__)
        return None
    return recognize(img)
