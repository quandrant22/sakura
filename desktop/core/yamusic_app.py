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
import asyncio
import logging
import time
import threading
from typing import Optional

log = logging.getLogger("sakura.yamusic_app")


try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _MediaManager,
    )
    _SMTC_OK = True
except ImportError:
    _MediaManager = None
    _SMTC_OK = False
    # ЯВНОЕ предупреждение вместо молчаливой деградации.
    # Полная проверка всех зависимостей — core/dep_check.py при старте агента.
    log.warning("[agent] winsdk не установлен — управление музыкой недоступно")

try:
    import win32gui, win32con, win32api
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

# Единая нормализация названий (кириллица → латиница) из корня репо.
# В автономной PyInstaller-сборке modules/ может отсутствовать — тогда
# работаем на прямых подстроках (кириллица+латиница) без транслита.
try:
    from modules.translit import transliterate as _translit
except ImportError:
    try:
        from translit import transliterate as _translit
    except ImportError:
        _translit = None


# ── Deep link-форматы (из аккаунта Мастера / Яндекс API) ───────────────
_YANDEX_DEEP = "yandexmusic://"

# Реальный AUMID на машине Мастера — 'Яндекс Музыка.exe' КИРИЛЛИЦЕЙ,
# поэтому матчим и кириллицу, и латиницу, и транслит.
_YAMUSIC_TOKENS = ("яндекс", "yandex", "музыка")
# Транслит-варианты: 'яндекс'→'yandeks' (кс→x!), 'музыка'→'muzyka'
_YAMUSIC_TRANSLIT_TOKENS = ("yandex", "yandeks", "music", "muzyka")
# Браузеры НЕ матчим: рядом может висеть сессия Opera с ютубом —
# пауза уйдёт не туда. Проверяются ДО музыкальных токенов.
_BROWSER_TOKENS = (
    "opera", "chrome", "chromium", "msedge", "edge", "firefox",
    "browser", "браузер", "brave", "vivaldi", "safari", "arc",
)


def is_yandex_music_aumid(aumid: str) -> bool:
    """True, если AUMID — это десктопное приложение Яндекс Музыки.

    Сопоставляет варианты 'яндекс'/'yandex'/'музыка'/'music'
    регистронезависимо, в кириллице и латинице (+ транслит).
    Гарантированно НЕ матчит браузеры (opera.exe и т.п.).
    """
    if not aumid:
        return False
    low = (aumid or "").lower()
    # Сначала браузеры — чтобы 'Яндекс Браузер' не прошел по 'яндекс'
    if any(t in low for t in _BROWSER_TOKENS):
        return False
    if any(t in low for t in _YAMUSIC_TOKENS):
        return True
    if _translit is not None:
        tr = _translit(low)  # 'яндекс музыка.exe' → 'yandeks muzyka.exe'
        if any(t in tr for t in _YAMUSIC_TRANSLIT_TOKENS):
            return True
    return False


def _match_yamusic_session(sessions) -> Optional[object]:
    """Ищет сессию Яндекс Музыки в уже полученном списке сессий."""
    for s in sessions:
        try:
            aumid = s.source_app_user_model_id or ""
        except Exception:
            continue
        if is_yandex_music_aumid(aumid):
            return s
    return None


async def _find_yandex_session_async():
    """Рабочий вариант (проверен на машине):
        mgr = await M.request_async()
        for s in mgr.get_sessions(): ...
    """
    mgr = await _MediaManager.request_async()
    if mgr is None:
        return None
    try:
        return _match_yamusic_session(mgr.get_sessions())
    except Exception as e:
        log.debug(f"[yamusic] SMTC enumerate: {e}")
        return None


# ── Выделенный поток для SMTC ─────────────────────────────────────────
# winsdk-awaitable нельзя дожидать через run_coroutine_threadsafe().result()
# ИЗ потока, на котором крутится loop агента: loop заблокирован в .result()
# и coroutine никогда не выполнится (взаимоблокировка до timeout). Поэтому
# все синхронные SMTC-вызовы уходят в выделенный worker-поток со своим loop.
_smtc_loop: Optional[asyncio.AbstractEventLoop] = None
_smtc_loop_lock = threading.Lock()


def _get_smtc_loop() -> "asyncio.AbstractEventLoop":
    """Собственный event loop в daemon-потоке — только для winsdk/SMTC."""
    global _smtc_loop
    with _smtc_loop_lock:
        if _smtc_loop is not None and not _smtc_loop.is_closed():
            return _smtc_loop
        ready = threading.Event()

        def _worker():
            global _smtc_loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _smtc_loop = loop
            ready.set()
            loop.run_forever()

        threading.Thread(target=_worker, daemon=True, name="smtc-worker").start()
        if not ready.wait(timeout=5.0):
            raise RuntimeError("smtc-worker не запустился за 5с")
        return _smtc_loop


def _run_smtc(awaitable, timeout: float = 3.0):
    """Дожидается winsdk-awaitable из синхронного кода БЕЗ блокировки loop'а агента.

    winsdk-методы возвращают awaitable (IAsyncOperation), а не coroutine —
    заворачиваем в coroutine. Выполнение всегда идёт в выделенном
    smtc-worker-потоке: вызывающий поток (даже если это loop агента)
    блокируется максимум на timeout, но main-loop продолжает работать.
    """
    import asyncio

    async def _call():
        return await awaitable

    import concurrent.futures
    try:
        fut = asyncio.run_coroutine_threadsafe(_call(), _get_smtc_loop())
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        log.warning(f"[yamusic] SMTC вызов не уложился в {timeout}с")
        raise


def _yandex_smtc_session():
    """Возвращает SMTC-сессию Яндекс Музыки или None.

    Важно: адресуем именно Яндекс Музыку, а не 'текущую' сессию,
    чтобы не отправлять play/pause в браузер или игру.
    """
    if not _SMTC_OK:
        return None
    try:
        return _run_smtc(_find_yandex_session_async())
    except Exception as e:
        log.debug(f"[yamusic] SMTC session: {e}")
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

def _resolve(awaitable):
    """winsdk-awaitable → результат: await (рабочий вариант с машины),
    fallback на блокирующий .get() (моки в тестах / синхронные объекты)."""
    import inspect
    if inspect.isawaitable(awaitable):
        return _run_smtc(awaitable)
    get = getattr(awaitable, "get", None)
    return get() if callable(get) else awaitable


def now_playing() -> dict:
    """Текущий трек из SMTC: {title, artist, album, status} или {}."""
    s = _yandex_smtc_session()
    if not s:
        return {}
    try:
        # рабочий вариант: props = await s.try_get_media_properties_async()
        props = _resolve(s.try_get_media_properties_async())
        pb = s.get_playback_info()
        # WinRT GlobalSystemMediaTransportControlsSessionPlaybackStatus:
        #   0=Closed, 1=Opened, 2=Changed, 3=Stopped, 4=Playing, 5=Paused
        # (прежняя карта {0:'остановлен',1:'играет',2:'пауза',3:'переключение',
        # 4:'закрыт'} была НЕВЕРНОЙ — играющий трек (4) помечался как 'закрыт',
        # а пауза (5) проваливалась в дефолт 'играет')
        _st_map = {0: "закрыт", 1: "открыт", 2: "переключение",
                   3: "остановлен", 4: "играет", 5: "пауза"}
        st_code = getattr(pb, "playback_status", 4)
        st_code = int(st_code) if not isinstance(st_code, int) else st_code
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
    s = _yandex_smtc_session()
    if not s:
        return False
    try:
        # winsdk-методы возвращают awaitable (IAsyncOperation) —
        # дожидаемся через _resolve (await в живом loop / .get() в моках).
        result = _resolve(getattr(s, method)())
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


