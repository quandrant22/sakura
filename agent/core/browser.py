"""
core/browser.py — управление Opera GX и Яндекс Музыкой в фоне.

Стратегия фона:
  - URL: subprocess с STARTF_USESHOWWINDOW + SW_SHOWNOACTIVATE
  - Opera получает URL через --new-tab без захвата фокуса
  - Хоткеи: временный фокус с немедленным возвратом фокуса исходному окну
  - Медиаклавиши: keybd_event — не трогают фокус вообще

Полная Яндекс Музыка:
  play/pause, next, prev, like, dislike, volume, seek,
  track search, artist, playlist, wave, shuffle, repeat
"""

import ctypes
import logging
import subprocess
import time
import webbrowser
from urllib.parse import quote

log = logging.getLogger("sakura.browser")

OPERA_TITLES     = ("Opera GX", "Opera", "opera")
YANDEX_MUSIC_URL = "https://music.yandex.ru"
YANDEX_UID       = "adebtrern"
OPERA_EXE        = r"C:\Users\mgrah\AppData\Local\Programs\Opera GX\opera.exe"

try:
    import win32gui, win32con, win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


# ── Поиск окна ────────────────────────────────────────────────────────

def _find_opera_hwnd() -> int | None:
    if not HAS_WIN32:
        return None
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if any(t in title for t in OPERA_TITLES):
                found.append(hwnd)
    win32gui.EnumWindows(_cb, None)
    return found[0] if found else None


def _get_foreground() -> int:
    return win32gui.GetForegroundWindow() if HAS_WIN32 else 0


# ── Открытие URL в фоне ───────────────────────────────────────────────

def _open_url_background(url: str) -> bool:
    if not url.startswith("http"):
        url = "https://" + url
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags    = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 4  # SW_SHOWNOACTIVATE
        subprocess.Popen(
            [OPERA_EXE, "--new-tab", url],
            startupinfo=si,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception as e:
        log.debug(f"[browser] subprocess: {e}")
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False


# ── Хоткеи с возвратом фокуса ────────────────────────────────────────

def _hotkey_bg(*keys) -> bool:
    """
    Временно фокусирует Opera, шлёт хоткей, возвращает фокус исходному окну.
    Моргание минимальное — Opera появляется на ~150мс.
    """
    if not HAS_WIN32 or not HAS_PYAUTOGUI:
        return False
    hwnd = _find_opera_hwnd()
    if not hwnd:
        return False
    prev_hwnd = _get_foreground()
    try:
        # Восстанавливаем если свёрнута
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.12)
        pyautogui.hotkey(*keys)
        time.sleep(0.08)
        # Возвращаем фокус
        if prev_hwnd and prev_hwnd != hwnd:
            try:
                win32gui.SetForegroundWindow(prev_hwnd)
            except Exception:
                pass
        return True
    except Exception as e:
        log.debug(f"[browser] hotkey {keys}: {e}")
        return False


def _type_in_addressbar(text: str) -> bool:
    """Вводит текст в адресную строку Opera и нажимает Enter, затем возвращает фокус."""
    if not HAS_WIN32 or not HAS_PYAUTOGUI:
        return False
    hwnd = _find_opera_hwnd()
    if not hwnd:
        return False
    prev_hwnd = _get_foreground()
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.12)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        if HAS_PYPERCLIP:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        else:
            pyautogui.typewrite(text, interval=0.02)
        time.sleep(0.08)
        pyautogui.press("enter")
        time.sleep(0.1)
        if prev_hwnd and prev_hwnd != hwnd:
            try:
                win32gui.SetForegroundWindow(prev_hwnd)
            except Exception:
                pass
        return True
    except Exception as e:
        log.debug(f"[browser] addressbar: {e}")
        return False


# ── Команды браузера ─────────────────────────────────────────────────

def open_youtube_active(url: str) -> str:
    """
    Открывает YouTube URL в Opera и оставляет вкладку активной.
    Используется когда пользователь целенаправленно идёт смотреть YouTube.
    """
    if not url.startswith("http"):
        url = "https://" + url
    try:
        import subprocess as _sp
        _sp.Popen([OPERA_EXE, "--new-tab", url])
        return f"открыла {url}"
    except Exception as e:
        log.debug(f"[browser] open_youtube_active: {e}")
        try:
            import webbrowser
            webbrowser.open(url)
            return f"открыла {url}"
        except Exception:
            return str(e)


def browser_tab_new() -> str:
    return "новая вкладка" if _hotkey_bg("ctrl", "t") else "Opera не найдена"

def browser_tab_close() -> str:
    return "вкладка закрыта" if _hotkey_bg("ctrl", "w") else "Opera не найдена"

def browser_tab_dup() -> str:
    return "вкладка дублирована" if _hotkey_bg("ctrl", "shift", "d") else "Opera не найдена"

def browser_tab_next() -> str:
    return "следующая вкладка" if _hotkey_bg("ctrl", "tab") else "Opera не найдена"

def browser_tab_prev() -> str:
    return "предыдущая вкладка" if _hotkey_bg("ctrl", "shift", "tab") else "Opera не найдена"

def browser_back() -> str:
    return "назад" if _hotkey_bg("alt", "left") else "Opera не найдена"

def browser_forward() -> str:
    return "вперёд" if _hotkey_bg("alt", "right") else "Opera не найдена"

def browser_reload() -> str:
    return "обновила" if _hotkey_bg("ctrl", "r") else "Opera не найдена"

def browser_scroll_down() -> str:
    return "прокрутила вниз" if _hotkey_bg("space") else "Opera не найдена"

def browser_scroll_up() -> str:
    return "прокрутила вверх" if _hotkey_bg("shift", "space") else "Opera не найдена"

def browser_open_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    _open_url_background(url)
    return f"открыла {url}"

def browser_search(query: str) -> str:
    if not query:
        return "нет запроса"
    _open_url_background(f"https://www.google.com/search?q={quote(query)}")
    return f"ищу: {query}"


# ── Медиаклавиши (не трогают фокус) ──────────────────────────────────

def _media(vk_code: int):
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk_code, 0, 0x0002, 0)

def music_play_pause() -> str:
    _media(0xB3); return "пауза/воспроизведение"

def music_next() -> str:
    _media(0xB0); return "следующий трек"

def music_prev() -> str:
    _media(0xB1); return "предыдущий трек"

def music_volume_up() -> str:
    _media(0xAF); return "громче"

def music_volume_down() -> str:
    _media(0xAE); return "тише"

def music_mute() -> str:
    _media(0xAD); return "mute"


# ── Яндекс Музыка — навигация ─────────────────────────────────────────

def music_open() -> str:
    _open_url_background(YANDEX_MUSIC_URL)
    return "открыла Яндекс Музыку"

def music_wave() -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/users/{YANDEX_UID}/radio/user/onyourwave")
    return "открыла Мою волну"

def music_playlist(kind_id: str) -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/users/{YANDEX_UID}/playlists/{kind_id}")
    return f"открыла плейлист {kind_id}"

def music_artist(query: str) -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/search?text={quote(query)}&type=artist")
    return f"ищу исполнителя: {query}"

def music_album(query: str) -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/search?text={quote(query)}&type=album")
    return f"ищу альбом: {query}"

def music_track(query: str) -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/search?text={quote(query)}&type=all")
    return f"ищу: {query}"

def music_liked() -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/users/{YANDEX_UID}/playlists/3")
    return "открыла любимые треки"

def music_podcasts() -> str:
    _open_url_background(f"{YANDEX_MUSIC_URL}/users/{YANDEX_UID}/podcast-subscriptions")
    return "открыла подкасты"


# ── Яндекс Музыка — управление через хоткеи ──────────────────────────
# Яндекс Музыка поддерживает глобальные hotkey когда вкладка активна.
# Мы кратковременно фокусируем вкладку и возвращаем фокус.

def _ym_hotkey(*keys) -> bool:
    """Шлёт хоткей в Яндекс Музыку и возвращает фокус."""
    if not HAS_WIN32 or not HAS_PYAUTOGUI:
        return False
    # Ищем окно Opera с Яндекс Музыкой
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if any(t.lower() in title for t in OPERA_TITLES) and (
                "яндекс музыка" in title or "yandex music" in title or
                "music.yandex" in title
            ):
                found.append(hwnd)
    win32gui.EnumWindows(_cb, None)

    # Если вкладка ЯМ не активна — шлём медиаклавишу как fallback
    hwnd = found[0] if found else _find_opera_hwnd()
    if not hwnd:
        return False

    prev_hwnd = _get_foreground()
    try:
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.12)
        pyautogui.hotkey(*keys)
        time.sleep(0.08)
        if prev_hwnd and prev_hwnd != hwnd:
            try:
                win32gui.SetForegroundWindow(prev_hwnd)
            except Exception:
                pass
        return True
    except Exception as e:
        log.debug(f"[ym] hotkey {keys}: {e}")
        return False


def music_like() -> str:
    # L — лайк в Яндекс Музыке (работает когда страница ЯМ в фокусе)
    ok = _ym_hotkey("l")
    return "лайк" if ok else "Яндекс Музыка не открыта"

def music_dislike() -> str:
    ok = _ym_hotkey("d")
    return "дизлайк" if ok else "Яндекс Музыка не открыта"

def music_shuffle() -> str:
    ok = _ym_hotkey("s")
    return "перемешать" if ok else "Яндекс Музыка не открыта"

def music_repeat() -> str:
    ok = _ym_hotkey("r")
    return "повтор" if ok else "Яндекс Музыка не открыта"

def music_seek_forward() -> str:
    ok = _ym_hotkey("shift", "right")
    return "перемотка вперёд" if ok else "Яндекс Музыка не открыта"

def music_seek_back() -> str:
    ok = _ym_hotkey("shift", "left")
    return "перемотка назад" if ok else "Яндекс Музыка не открыта"


# ── YouTube хоткеи плеера ────────────────────────────────────────────
# Работают когда вкладка YouTube активна в Opera.
# Временно фокусируем вкладку, шлём хоткей, возвращаем фокус.

_YT_HOTKEYS = {
    "youtube_pause":       ("k",),
    "youtube_fullscreen":  ("f",),
    "youtube_forward":     ("l",),
    "youtube_rewind":      ("j",),
    "youtube_forward5":    ("right",),
    "youtube_rewind5":     ("left",),
    "youtube_next":        ("shift", "n"),
    "youtube_mute":        ("m",),
    "youtube_sub_toggle":  ("c",),
    "youtube_volume_up":   ("up",),
    "youtube_volume_down": ("down",),
    "youtube_speed_up":    ("shift", "."),
    "youtube_speed_down":  ("shift", ","),
    "youtube_like":        ("shift", "/"),   # нет стандартного хоткея — открываем меню
    "youtube_mini":        ("i",),
    "youtube_theater":     ("t",),
}


def _find_youtube_hwnd() -> int | None:
    """Ищет окно Opera с открытым YouTube."""
    if not HAS_WIN32:
        return None
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if any(t.lower() in title for t in OPERA_TITLES) and "youtube" in title:
                found.append(hwnd)
    win32gui.EnumWindows(_cb, None)
    # Если вкладки YouTube нет — берём любую Opera (могут переключиться на YT)
    return found[0] if found else _find_opera_hwnd()


def youtube_player_cmd(action: str) -> str:
    """
    Выполняет YouTube команду.
    Приоритет: расширение браузера → хоткеи (fallback).
    """
    # Через расширение — надёжно, без фокуса
    try:
        from core.extension_server import is_connected, send_command
        import asyncio
        if is_connected():
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(send_command(action))
            if result.get("ok") is not False:
                log.info(f"[yt] {action} via extension → {result.get('result', 'ok')}")
                return f"youtube: {action}"
    except RuntimeError:
        pass  # event loop не запущен — используем хоткеи
    except Exception as e:
        log.debug(f"[yt] extension: {e}")

    # Fallback — хоткеи
    keys = _YT_HOTKEYS.get(action)
    if not keys:
        return f"неизвестная команда: {action}"
    hwnd      = _find_youtube_hwnd()
    if not hwnd:
        return "Opera не найдена"
    prev      = _get_foreground()
    prev_pos  = None
    try:
        import time as _t
        if HAS_PYAUTOGUI:
            prev_pos = pyautogui.position()
        win32gui.SetForegroundWindow(hwnd)
        _t.sleep(0.15)
        if HAS_PYAUTOGUI:
            try:
                rect = win32gui.GetClientRect(hwnd)
                cx   = (rect[2] - rect[0]) // 2
                cy   = (rect[3] - rect[1]) // 2 + 100
                pt   = win32gui.ClientToScreen(hwnd, (cx, cy))
                pyautogui.click(pt[0], pt[1])
                _t.sleep(0.1)
            except Exception:
                pass
            pyautogui.press(keys[0]) if len(keys) == 1 else pyautogui.hotkey(*keys)
        _t.sleep(0.08)
        if prev and prev != hwnd:
            try: win32gui.SetForegroundWindow(prev)
            except Exception: pass
        if prev_pos and HAS_PYAUTOGUI:
            try: pyautogui.moveTo(prev_pos.x, prev_pos.y)
            except Exception: pass
        return f"youtube: {action}"
    except Exception as e:
        log.debug(f"[yt] hotkey {action}: {e}")
        return str(e)


def music_open_and_find(query: str) -> str:
    if not _is_yandex_music_open():
        music_open()
        time.sleep(2.0)
    return music_track(query)

def _is_yandex_music_open() -> bool:
    if not HAS_WIN32:
        return False
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if any(t.lower() in title for t in OPERA_TITLES) and (
                "яндекс музыка" in title or "yandex music" in title
            ):
                found.append(hwnd)
    win32gui.EnumWindows(_cb, None)
    return bool(found)
