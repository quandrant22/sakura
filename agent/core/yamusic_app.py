"""
core/yamusic_app.py — управление десктопным приложением Яндекс Музыки.

Каналы:
  SMTC     — play/pause/next/prev/now_playing (глобально, без фокуса)
  deep links — yandexmusic:// (wave, playlist, album, artist, search)
  hotkeys  — like/dislike (focus_window + возврат фокуса)

Автовыбор: music_target() определяет канал по активной SMTC-сессии.
Браузерный путь (browser.py) НЕ удаляется — остаётся как fallback.
"""
import os
import logging
import time
from typing import Optional

log = logging.getLogger("sakura.yamusic_app")


try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _MediaManager,
    )
    _SMTC_OK = True
except ImportError:
    _SMTC_OK = False
    log.debug("[yamusic] winsdk не установлен")

try:
    import win32gui, win32con, win32api
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False


# ── Deep link-форматы (из аккаунта Мастера / Яндекс API) ───────────────
_YANDEX_DEEP = "yandexmusic://"


def _yandex_smtc_session():
    """Возвращает SMTC-сессию Яндекс Музыки или None.

    Важно: адресуем именно Яндекс Музыку, а не 'текущую' сессию,
    чтобы не отправлять play/pause в браузер или игру.
    """
    if not _SMTC_OK:
        return None
    try:
        sessions = _MediaManager.request_async()
        if sessions is None:
            return None
        sl = sessions.get_sessions() if hasattr(sessions, "get_sessions") else sessions
        for s in sl:
            try:
                aumid = s.source_app_user_model_id or ""
            except Exception:
                aumid = ""
            if "yandex" in aumid.lower() or "music" in aumid.lower():
                return s
    except Exception as e:
        log.debug(f"[yamusic] SMTC enumerate: {e}")
    return None


def _get_foreground() -> int:
    return win32gui.GetForegroundWindow() if _HAS_WIN32 else 0


def _find_yamusic_hwnd() -> Optional[int]:
    """Ищет HWND окна Яндекс Музыки."""
    if not _HAS_WIN32:
        return None
    found = []
    for needle in ("Yandex Music", "Яндекс Музыка"):
        hwnd = win32gui.FindWindow(None, needle)
        if hwnd:
            return hwnd
    def _enum(h, _):
        t = win32gui.GetWindowText(h).lower()
        if "yandex music" in t or "яндекс музыка" in t:
            found.append(h)
    win32gui.EnumWindows(_enum, None)
    return found[0] if found else None


# ── 2.1 — SMTC команды (глобально, без фокуса) ────────────────────────

def now_playing() -> dict:
    """Текущий трек из SMTC: {title, artist, album, status} или {}."""
    s = _yandex_smtc_session()
    if not s:
        return {}
    try:
        props = s.try_get_media_properties_async()
        props = props.get() if hasattr(props, "get") else props
        pb = s.get_playback_info()
        _st_map = {0: "остановлен", 1: "играет", 2: "пауза",
                   3: "переключение", 4: "закрыт"}
        st_code = getattr(pb, "playback_status", 1)
        return {
            "title":  getattr(props, "title", "") or "",
            "artist": getattr(props, "artist", "") or "",
            "album":  getattr(props, "album_title", "") or "",
            "status": _st_map.get(st_code, "играет"),
        }
    except Exception as e:
        log.debug(f"[yamusic] now_playing: {e}")
        return {}


def _smtc_control(method: str) -> bool:
    """Вызов SMTC-метода на сессии Яндекс Музыки (а НЕ на текущей сессии!)."""
    import asyncio
    s = _yandex_smtc_session()
    if not s:
        return False
    try:
        coro = getattr(s, method)
        # winsdk-методы возвращают awaitable (IAsyncOperation), а не coroutine —
        # заворачиваем, чтобы работали оба пути (запущенный loop и синхронный).
        async def _call():
            return await coro()
        loop = asyncio.get_event_loop()
        if loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(_call(), loop)
            result = fut.result(timeout=3.0)
        else:
            result = loop.run_until_complete(_call())
        # TrySkipNextAsync возвращает bool
        return bool(result) if not isinstance(result, bool) else result
    except Exception as e:
        log.debug(f"[yamusic] {method}: {e}")
        return False


def play_pause():
    return _smtc_control("TryTogglePlayPauseAsync")

def next_track():
    return _smtc_control("TrySkipNextAsync")

def prev_track():
    return _smtc_control("TrySkipPreviousAsync")


# ── 2.2 — Deep links (без фокуса) ──────────────────────────────────────

def _deep(url: str) -> bool:
    """Запуск deep link через os.startfile (без фокуса вручную управляется системой)."""
    try:
        os.startfile(url)
        return True
    except Exception as e:
        log.debug(f"[yamusic] deep link: {e}")
        return False


def open_wave():
    """Моя волна в десктопном приложении."""
    return _deep(f"{_YANDEX_DEEP}radio/user/onyourwave")

def open_playlist(pid):
    return _deep(f"{_YANDEX_DEEP}playlist/{pid}")

def open_album(aid):
    return _deep(f"{_YANDEX_DEEP}album/{aid}")

def open_artist(artid):
    return _deep(f"{_YANDEX_DEEP}artist/{artid}")


# ── 2.3 — Хоткеи с возвратом фокуса ────────────────────────────────────

_HOTKEYS = {
    "like":    "l",
    "dislike": "d",
}


def _hotkey_to_window(hwnd: int, key_char: str) -> bool:
    """Фокус на окно, шлёт WM_CHAR, возвращает фокус исходному окну."""
    _prev = _get_foreground()
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.12)
        win32api.PostMessage(hwnd, win32con.WM_CHAR, ord(key_char.upper()), 0)
        time.sleep(0.06)
        return True
    except Exception as e:
        log.debug(f"[yamusic] hotkey: {e}")
        return False
    finally:
        if _prev and _prev != hwnd:
            try:
                win32gui.SetForegroundWindow(_prev)
            except Exception:
                pass


def like() -> bool:
    hwnd = _find_yamusic_hwnd()
    if not hwnd:
        return False
    return _hotkey_to_window(hwnd, _HOTKEYS["like"])

def dislike() -> bool:
    hwnd = _find_yamusic_hwnd()
    if not hwnd:
        return False
    return _hotkey_to_window(hwnd, _HOTKEYS["dislike"])


# ── 2.4 — Автовыбор канала ────────────────────────────────────────────

def music_target() -> str:
    """Определяет, где играет музыка: 'app' | 'browser'.

    1. SMTC-сессия Яндекс Музыки активна → 'app'
    2. иначе — фоллбэк на браузерный путь (browser.py)
    """
    if _yandex_smtc_session():
        return "app"
    return "browser"


