"""desktop.core.vision_capture — кадр экрана по запросу сервера (vision.capture).

Протокол — docs/VISION.md. Ядро экран само не снимает: только в ответ на
vision.capture от сервера (или window_ask по кнопке пользователя).

Порядок, строго:
  1. purpose не «ask» и пользователь не разрешил поглядывать → skipped/disabled;
  2. приватное окно на переднем плане → skipped/private_window, экран НЕ снимается;
  3. снять экран; не вышло → capture_failed; чёрный кадр → no_display;
  4. need_change и отпечаток 64×36 не изменился → skipped/unchanged (JPEG не кодируется);
  5. JPEG ≤ MAX_B64 → status ok.

Кадр не пишется на диск и в лог: в лог — purpose, размер, итог.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any, Callable

log = logging.getLogger("sakura.vision")

PURPOSES = ("ask", "glance", "watch")
MAX_B64 = 2_000_000
PRINT_SIZE = (64, 36)
SIDE_RANGE = (320, 1920)
QUALITY_RANGE = (30, 90)
TITLE_MAX = 200

# Настройки интерфейса (desktop/core/service.py, SETTINGS_KEYS).
ALLOW_KEY = "vision_glance_allowed"     # bool, по умолчанию False
PRIVATE_KEY = "vision_private"          # [str] — свои приватные окна/программы


def fingerprint(img) -> bytes:
    """64×36 RGB — для «изменился ли экран»."""
    return img.convert("RGB").resize(PRINT_SIZE).tobytes()


def changed(before: bytes | None, after: bytes) -> bool:
    """Порог как в docs/VISION.md: сумма разниц > 64·36·6 или ≥ 24 пикселя с разницей > 24."""
    if before is None or len(before) != len(after):
        return True
    total = moved = 0
    for i in range(0, len(after) - 2, 3):
        d = max(abs(after[i] - before[i]), abs(after[i + 1] - before[i + 1]), abs(after[i + 2] - before[i + 2]))
        total += d
        if d > 24:
            moved += 1
    return total > PRINT_SIZE[0] * PRINT_SIZE[1] * 6 or moved >= 24


def is_black(print_: bytes) -> bool:
    """Экран заблокирован или выключен: почти весь отпечаток чёрный."""
    return max(print_, default=0) < 12


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _default_grab():
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=False)


def _default_foreground() -> dict:
    from desktop.core.platform import get_platform
    return get_platform().foreground_window() or {}


class VisionCapture:
    def __init__(self, settings=None, *, grab: Callable[[], Any] | None = None,
                 foreground: Callable[[], dict] | None = None,
                 password_focused: Callable[[], bool] | None = None,
                 on_look: Callable[[str, bool], None] | None = None):
        self.settings = settings
        self._grab = grab or _default_grab
        self._foreground = foreground or _default_foreground
        if password_focused is None:
            from desktop.core.vision_privacy import password_focused as _pf
            password_focused = _pf
        self._password_focused = password_focused
        self._on_look = on_look or (lambda purpose, active: None)
        self._prints: dict[str, bytes] = {}

    # ── настройки ──────────────────────────────────────────────────
    def allowed(self) -> bool:
        s = self.settings
        return bool(s.get_bool(ALLOW_KEY, False)) if s is not None else False

    def private_list(self) -> list[str]:
        s = self.settings
        items = s.get_list(PRIVATE_KEY, []) if s is not None else []
        return [str(x) for x in items if str(x).strip()][:100]

    # ── запрос ─────────────────────────────────────────────────────
    def capture(self, msg: dict) -> dict:
        """vision.capture → тело vision.frame (без device_id/token)."""
        rid = msg.get("request_id")
        purpose = msg.get("purpose") if msg.get("purpose") in PURPOSES else "ask"
        t0 = time.monotonic()
        out = self._capture(purpose, msg)
        out = {"type": "vision.frame", "request_id": rid, **out}
        if out["status"] == "ok":
            log.info("[vision] %s: кадр %d КиБ за %.2f с", purpose, len(out["image"]) * 3 // 4 // 1024,
                     time.monotonic() - t0)
        else:
            log.info("[vision] %s: пропуск (%s)", purpose, out["reason"])
        return out

    def _capture(self, purpose: str, msg: dict) -> dict:
        from desktop.core.vision_privacy import is_private
        if purpose != "ask" and not self.allowed():
            return {"status": "skipped", "reason": "disabled"}
        try:
            win = self._foreground() or {}
        except Exception:
            win = {}
        title = str(win.get("title") or "")[:TITLE_MAX]
        process = str(win.get("process") or "")
        if is_private(title, process, self.private_list()) or self._password_focused():
            return {"status": "skipped", "reason": "private_window"}
        if purpose != "ask":
            self._on_look(purpose, True)
        try:
            try:
                img = self._grab()
            except Exception as e:
                log.warning("[vision] снять экран не вышло: %s", type(e).__name__)
                return {"status": "skipped", "reason": "capture_failed"}
            if img is None:
                return {"status": "skipped", "reason": "no_display"}
            img = img.convert("RGB")
            print_ = fingerprint(img)
            if is_black(print_):
                return {"status": "skipped", "reason": "no_display"}
            if msg.get("need_change") is True:
                before = self._prints.get(purpose)
                self._prints[purpose] = print_
                if not changed(before, print_):
                    return {"status": "skipped", "reason": "unchanged"}
            data = self._jpeg(img, _clamp(msg.get("max_side"), *SIDE_RANGE, 1280),
                              _clamp(msg.get("quality"), *QUALITY_RANGE, 70))
            if data is None:
                return {"status": "skipped", "reason": "capture_failed"}
            return {"status": "ok", "image": data,
                    "window": {"title": title, "process": process[:80]}, "changed": True}
        finally:
            if purpose != "ask":
                self._on_look(purpose, False)

    @staticmethod
    def _jpeg(img, max_side: int, quality: int) -> str | None:
        from PIL import Image
        long_side = max(img.width, img.height)
        if long_side > max_side:
            scale = max_side / long_side
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        q = quality
        while q >= QUALITY_RANGE[0]:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q)
            b64 = base64.b64encode(buf.getvalue()).decode()
            if len(b64) <= MAX_B64:
                return b64
            q -= 15
        return None
