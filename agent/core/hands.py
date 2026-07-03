"""core/hands.py — руки: приложения, громкость, медиа, диктовка, скриншот, ссылки.

Скан приложений из четырёх источников:
  - меню «Пуск» (.lnk)
  - Get-StartApps (Microsoft Store / UWP + установленные) → shell:AppsFolder
  - Steam (по манифестам) → steam://rungameid/<appid>
  - папки с играми-пиратками (.exe) из config.GAME_DIRS
Ручные «запомни» (apps.json) имеют наивысший приоритет.

Открытие — единая цепочка resolve_and_open: что бы ни пришло (готовый таргет от
VPS или сырое разговорное имя), агент доводит сам: приложение (точно/подстрока/
фаззи по полному скану) → файл из индекса по всему диску → отдать ОС как есть.

v2.0: Integrates with command registry for declarative command definitions.
"""

import base64
import io
import json
import logging
import os
import re
import subprocess
import time
import webbrowser
from difflib import get_close_matches
from urllib.parse import quote

import config
from core.file_index import FileIndex
from core.commands import CommandRegistry, load_builtin_commands

try:    import win32gui, win32con
except ImportError: win32gui = win32con = None
try:    import pyperclip
except ImportError: pyperclip = None
try:    import pyautogui; pyautogui.FAILSAFE = False
except ImportError: pyautogui = None
try:    from PIL import ImageGrab
except ImportError: ImageGrab = None

log = logging.getLogger("sakura.hands")

# Command registry for declarative command matching
_command_registry: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    """Get or initialize the command registry."""
    global _command_registry
    if _command_registry is None:
        _command_registry = CommandRegistry()
        # Load built-in commands
        load_builtin_commands(_command_registry)
        # Load custom commands from commands directory
        commands_dir = os.path.join(config.BASE_DIR, "commands")
        if os.path.isdir(commands_dir):
            _command_registry.load_from_dir(commands_dir)
        log.info(f"Command registry initialized: {_command_registry.hash[:8]}")
    return _command_registry

# Служебные .exe, которые не являются играми
_SKIP_EXE = ("unins", "setup", "redist", "vcredist", "dxsetup", "directx",
             "crashpad", "crashreport", "launcher_helper", "dotnet", "support",
             "config", "editor", "benchmark", "cleanup", "activation", "report")

# Полный результат последнего скана — для фаззи-резолва приложений на месте.
_app_cache: dict = {}

# Индекс файлов по всему диску. Запуск — init_index() из агента при старте.
file_index = FileIndex(
    cache_path=os.path.join(os.path.dirname(config.APPS_FILE) or ".", "file_index.json")
)


def init_index():
    """Запустить фоновую сборку/обновление файлового индекса. Звать раз при старте."""
    file_index.start()


# ── реестр приложений ───────────────────────────────────────────────
def _load_apps() -> dict:
    try:
        if os.path.exists(config.APPS_FILE):
            with open(config.APPS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_apps(apps: dict):
    try:
        with open(config.APPS_FILE, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"save apps: {e}")


def _scan_start_menu() -> dict:
    apps = {}
    roots = [
        os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""),     r"Microsoft\Windows\Start Menu\Programs"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(".lnk"):
                    apps[os.path.splitext(fn)[0].lower()] = os.path.join(dirpath, fn)
    return apps


def _scan_start_apps() -> dict:
    """Get-StartApps: Store/UWP + установленные. Запуск через shell:AppsFolder\\<AppID>."""
    apps = {}
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
          "Get-StartApps | ConvertTo-Json -Compress")
    try:
        # читаем БАЙТАМИ и декодируем сами — иначе поток subprocess падает
        # на кириллице (PowerShell отдаёт не UTF-8 по умолчанию)
        out  = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=30,
        )
        text = out.stdout.decode("utf-8", "replace").strip()
        if not text:
            return apps
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        for entry in data:
            name  = (entry.get("Name") or "").strip()
            appid = (entry.get("AppID") or "").strip()
            if name and appid:
                apps[name.lower()] = f"shell:AppsFolder\\{appid}"
    except Exception as e:
        log.error(f"Get-StartApps: {e}")
    return apps


def _steam_path() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, "SteamPath")[0]
    except Exception:
        for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
            if os.path.isdir(p):
                return p
    return None


def _scan_steam() -> dict:
    """Игры Steam по манифестам всех библиотек. Запуск через steam://rungameid/<appid>."""
    apps = {}
    base = _steam_path()
    if not base:
        return apps
    libs = [os.path.join(base, "steamapps")]
    vdf  = os.path.join(base, "steamapps", "libraryfolders.vdf")
    try:
        if os.path.exists(vdf):
            txt = open(vdf, encoding="utf-8", errors="ignore").read()
            for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
                libs.append(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps"))
    except Exception:
        pass
    seen = set()
    for lib in libs:
        if not os.path.isdir(lib):
            continue
        for fn in os.listdir(lib):
            if not (fn.startswith("appmanifest_") and fn.endswith(".acf")):
                continue
            try:
                txt   = open(os.path.join(lib, fn), encoding="utf-8", errors="ignore").read()
                appid = re.search(r'"appid"\s*"(\d+)"', txt)
                name  = re.search(r'"name"\s*"([^"]+)"', txt)
                if appid and name and appid.group(1) not in seen:
                    seen.add(appid.group(1))
                    apps[name.group(1).strip().lower()] = f"steam://rungameid/{appid.group(1)}"
            except Exception:
                pass
    return apps


def _scan_game_dirs() -> dict:
    """Пиратки: .exe в config.GAME_DIRS. Имя папки → самый крупный .exe (обычно сама игра)."""
    apps = {}
    for root in config.GAME_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            exes = [f for f in files if f.lower().endswith(".exe")
                    and not any(s in f.lower() for s in _SKIP_EXE)]
            if not exes:
                continue
            try:
                best = max(exes, key=lambda f: os.path.getsize(os.path.join(dirpath, f)))
            except OSError:
                best = exes[0]
            apps.setdefault(os.path.basename(dirpath).lower(), os.path.join(dirpath, best))
            for e in exes:
                apps.setdefault(os.path.splitext(e)[0].lower(), os.path.join(dirpath, e))
    return apps


def scan_apps() -> dict:
    """Собирает все источники. Более «играбельные» переопределяют общие, ручные — поверх всех."""
    apps = {}
    for source in (_scan_start_menu, _scan_start_apps, _scan_steam, _scan_game_dirs):
        try:
            apps.update(source())
        except Exception as e:
            log.error(f"scan {source.__name__}: {e}")
    apps.update(_load_apps())
    global _app_cache
    _app_cache = apps                      # запомнить для фаззи-резолва на месте
    log.info(f"Найдено приложений и игр: {len(apps)}")
    return apps


# ── открытие: единая цепочка ────────────────────────────────────────
def _is_target(s: str) -> bool:
    """Уже готовая для запуска строка (таргет от VPS), а не разговорное имя."""
    low = s.lower()
    return (low.startswith(("shell:", "steam:", "http://", "https://"))
            or os.path.exists(s)
            or (len(s) > 2 and s[1] == ":"))           # путь вида C:\...


def _launch(target: str) -> bool:
    try:
        if target.startswith("shell:"):
            subprocess.Popen(["explorer.exe", target])
        else:
            os.startfile(target)                       # путь, .lnk, steam://, http
        return True
    except Exception:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
            return True
        except Exception:
            return False


def _resolve_target(name: str) -> str | None:
    """Разговорное имя → таргет. Ручные → полный скан: точно, подстрока, фаззи."""
    key = name.lower()
    manual = _load_apps()
    if key in manual:
        return manual[key]
    if key in _app_cache:
        return _app_cache[key]
    for k, v in _app_cache.items():
        if key in k:
            return v
    hit = get_close_matches(key, list(_app_cache.keys()), n=1, cutoff=0.6)
    return _app_cache[hit[0]] if hit else None


def open_app(name: str) -> str:
    """Открывает приложение ИЛИ файл по имени. Что бы ни пришло — доводит до конца."""
    name = name.strip()

    # 1. Готовый таргет от VPS — запускаем как есть.
    if _is_target(name):
        return f"открыл {name}" if _launch(name) else f"app_not_found:{name}"

    # 2. Разговорное имя → приложение (точно / подстрока / фаззи по полному скану).
    target = _resolve_target(name)
    if target and _launch(target):
        return f"открыл {name}"

    # 3. Не приложение — ищем файл по всему диску в индексе.
    opened = file_index.open(name)
    if opened:
        return f"открыл файл {os.path.basename(opened)}"

    # 4. Последняя попытка — отдать ОС как есть.
    return f"открыл {name}" if _launch(name) else f"app_not_found:{name}"


def open_file(name: str) -> str:
    """Явное открытие файла по имени из индекса по всему диску."""
    opened = file_index.open(name.strip())
    return f"открыл файл {os.path.basename(opened)}" if opened else f"file_not_found:{name}"


def find_file(name: str, limit: int = 5) -> list[str]:
    """Список путей-кандидатов (например, чтобы переспросить «какой именно»)."""
    return file_index.search(name.strip(), limit=limit)


def close_window(query: str) -> str:
    if not win32gui:
        return "нет доступа к окнам"
    query  = query.strip().lower()
    closed = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and query in title.lower():
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                closed.append(title)

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as e:
        return f"ошибка: {e}"
    return f"закрыл: {closed[0]}" if closed else f"окно «{query}» не найдено"


def remember_app(pair: str) -> str:
    if "=" not in pair:
        return "формат remember_app:имя=путь"
    name, path = pair.split("=", 1)
    apps = _load_apps()
    apps[name.strip().lower()] = path.strip()
    _save_apps(apps)
    return f"запомнил {name.strip()}"


# ── громкость ───────────────────────────────────────────────────────
def _volume_iface():
    import comtypes
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    speakers = AudioUtilities.GetSpeakers()
    dev      = getattr(speakers, "_dev", speakers)   # новые pycaw оборачивают IMMDevice
    iface    = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def set_volume(percent: int) -> str:
    try:
        _volume_iface().SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100.0, None)
        return f"громкость {percent}%"
    except Exception as e:
        return f"громкость недоступна: {e}"


def nudge_volume(delta: int) -> str:
    try:
        vol = _volume_iface()
        new = max(0, min(100, int(vol.GetMasterVolumeLevelScalar() * 100) + delta))
        vol.SetMasterVolumeLevelScalar(new / 100.0, None)
        return f"громкость {new}%"
    except Exception as e:
        return f"громкость недоступна: {e}"


# ── медиа ───────────────────────────────────────────────────────────
def media_key(kind: str) -> str:
    import ctypes
    vk = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1}.get(kind)
    if not vk:
        return "неизвестная медиа-команда"
    try:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)
        return f"медиа: {kind}"
    except Exception as e:
        return f"медиа недоступно: {e}"


# ── диктовка / скриншот / youtube ───────────────────────────────────
def dictate(text: str) -> str:
    if not (pyperclip and pyautogui):
        return "диктовка недоступна"
    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        return "вставила текст"
    except Exception as e:
        return f"диктовка недоступна: {e}"


def take_screenshot() -> str | None:
    if not ImageGrab:
        return None
    try:
        buf = io.BytesIO()
        ImageGrab.grab().convert("RGB").save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        log.error(f"screenshot: {e}")
        return None


def open_youtube(query: str) -> str:
    from core.browser import open_youtube_active
    url = f"https://www.youtube.com/results?search_query={quote(query)}"
    return open_youtube_active(url)


# ── маршрутизация команд ────────────────────────────────────────────
def execute_command(action: str) -> dict:
    verb, _, arg = action.partition(":")
    verb = verb.strip()
    if verb == "open_app":      return {"result": open_app(arg)}
    if verb == "open_file":     return {"result": open_file(arg)}
    if verb == "close_window":  return {"result": close_window(arg)}
    if verb == "remember_app":  return {"result": remember_app(arg)}
    if verb == "open_url":
        webbrowser.open(arg); return {"result": f"открыл {arg}"}
    if verb == "open_youtube_url":
        from core.browser import open_youtube_active
        return {"result": open_youtube_active(arg)}
    if verb in ("open_youtube", "youtube", "youtube_playlist"):
        return {"result": open_youtube(arg)}
    if verb == "volume":        return {"result": set_volume(int(arg or 50))}
    if verb == "volume_up":     return {"result": nudge_volume(int(arg or 20))}
    if verb == "volume_down":   return {"result": nudge_volume(-int(arg or 20))}
    # YouTube хоткеи плеера
    if verb and verb.startswith("youtube_") and verb not in ("youtube_search", "youtube_channel", "youtube_playlist"):
        from core.browser import youtube_player_cmd
        return {"result": youtube_player_cmd(verb)}

    if verb == "music":
        from core.browser import (
            music_play_pause, music_next, music_prev, music_open,
            music_wave, music_playlist, music_track, music_artist,
            music_album, music_liked, music_podcasts,
            music_like, music_dislike, music_open_and_find,
            music_shuffle, music_repeat,
            music_seek_forward, music_seek_back,
            music_volume_up, music_volume_down, music_mute,
        )
        if arg == "play_pause":    return {"result": music_play_pause()}
        if arg == "next":          return {"result": music_next()}
        if arg == "prev":          return {"result": music_prev()}
        if arg == "open":          return {"result": music_open()}
        if arg == "wave":          return {"result": music_wave()}
        if arg == "like":          return {"result": music_like()}
        if arg == "dislike":       return {"result": music_dislike()}
        if arg == "shuffle":       return {"result": music_shuffle()}
        if arg == "repeat":        return {"result": music_repeat()}
        if arg == "seek_forward":  return {"result": music_seek_forward()}
        if arg == "seek_back":     return {"result": music_seek_back()}
        if arg == "volume_up":     return {"result": music_volume_up()}
        if arg == "volume_down":   return {"result": music_volume_down()}
        if arg == "mute":          return {"result": music_mute()}
        if arg == "liked":         return {"result": music_liked()}
        if arg == "podcasts":      return {"result": music_podcasts()}
        if arg.startswith("track:"):    return {"result": music_open_and_find(arg[6:])}
        if arg.startswith("artist:"):   return {"result": music_artist(arg[7:])}
        if arg.startswith("album:"):    return {"result": music_album(arg[6:])}
        if arg.startswith("playlist:"): return {"result": music_playlist(arg[9:])}
        return {"result": f"неизвестная музыкальная команда: {arg}"}

    if verb == "browser":
        # Приоритет — расширение браузера (точнее и надёжнее хоткеев)
        import sys as _sys, logging as _log2
        _ext = _sys.modules.get("core.extension_server")
        _log2.getLogger("sakura.hands").info(f"[browser] ext={_ext is not None} connected={_ext.is_connected() if _ext else False} arg={arg!r}")
        if _ext and _ext.is_connected():
            import asyncio as _aio
            # Маппинг browser:arg → ext action
            _ext_map = {
                "tab_new":    ("tab_new",    ""),
                "tab_close":  ("tab_close",  ""),
                "tab_dup":    ("tab_dup",    ""),
                "tab_next":   ("tab_next",   ""),
                "tab_prev":   ("tab_prev",   ""),
                "back":       ("go_back",    ""),
                "forward":    ("go_forward", ""),
                "reload":     ("tab_reload", ""),
                "tab_reload": ("tab_reload", ""),
                "scroll_down":("page_scroll","down"),
                "scroll_up":  ("page_scroll","up"),
            }
            if arg in _ext_map:
                ext_action, ext_arg = _ext_map[arg]
            elif arg.startswith("url:"):
                ext_action, ext_arg = "navigate", arg[4:]
            elif arg.startswith("search:"):
                ext_action, ext_arg = "search_google", arg[7:]
            elif arg.startswith("switch:"):
                ext_action, ext_arg = "tab_switch", arg[7:]
            elif arg.startswith("switch:"):
                ext_action, ext_arg = "tab_switch", arg[7:]
            elif arg.startswith("zoom:"):
                z = arg[5:]
                ext_action = "zoom_in" if z == "in" else ("zoom_out" if z == "out" else "zoom_reset")
                ext_arg = ""
            elif arg.startswith("click:"):
                ext_action, ext_arg = "page_click", arg[6:]
            else:
                ext_action, ext_arg = None, None

            if ext_action:
                try:
                    agent_loop = getattr(_ext, '_agent_loop', None)
                    _log2.getLogger("sakura.hands").info(f"[browser] agent_loop={agent_loop}")
                    if agent_loop is None:
                        raise RuntimeError("agent loop не установлен")
                    fut    = _aio.run_coroutine_threadsafe(_ext.send_command(ext_action, ext_arg), agent_loop)
                    result = fut.result(timeout=5.0)
                    _log2.getLogger("sakura.hands").info(f"[browser] ext result: {result}")
                    return {"result": result.get("result", "ok")}
                except Exception as _e:
                    _log2.getLogger("sakura.hands").error(f"[browser] ext error: {_e}")

        # Fallback — хоткеи через браузер
        from core.browser import (
            browser_tab_new, browser_tab_close, browser_tab_dup,
            browser_tab_next, browser_tab_prev,
            browser_back, browser_forward, browser_reload,
            browser_scroll_down, browser_scroll_up,
            browser_open_url, browser_search,
        )
        if arg == "tab_new":     return {"result": browser_tab_new()}
        if arg == "tab_close":   return {"result": browser_tab_close()}
        if arg == "tab_dup":     return {"result": browser_tab_dup()}
        if arg == "tab_next":    return {"result": browser_tab_next()}
        if arg == "tab_prev":    return {"result": browser_tab_prev()}
        if arg == "back":        return {"result": browser_back()}
        if arg == "forward":     return {"result": browser_forward()}
        if arg == "reload":      return {"result": browser_reload()}
        if arg == "scroll_down": return {"result": browser_scroll_down()}
        if arg == "scroll_up":   return {"result": browser_scroll_up()}
        if arg.startswith("url:"):    return {"result": browser_open_url(arg[4:])}
        if arg.startswith("search:"): return {"result": browser_search(arg[7:])}
        return {"result": f"неизвестная команда браузера: {arg}"}

    if verb == "screenshot":    return {"screenshot": take_screenshot()}
    if verb == "dictate":       return {"result": dictate(arg)}

    # Системные команды
    if verb == "system":
        import subprocess, ctypes
        if arg == "lock":
            ctypes.windll.user32.LockWorkStation()
            return {"result": "заблокировано"}
        if arg == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "30", "/c", "Команда Сакуры"])
            return {"result": "выключение через 30 секунд"}
        if arg == "shutdown_cancel":
            subprocess.Popen(["shutdown", "/a"])
            return {"result": "выключение отменено"}
        if arg == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            return {"result": "уходим в сон"}
        return {"result": f"неизвестная системная команда: {arg}"}

    return {"result": f"неизвестная команда: {action}"}


# ── Новые примитивы (этап 4) ──────────────────────────────────────────

_ALLOWED_KEYS = frozenset({
    "ctrl", "alt", "shift", "win", "windows", "enter", "esc", "escape",
    "tab", "space", "backspace", "delete", "insert", "home", "end",
    "pageup", "pagedown", "up", "down", "left", "right",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12", "f13", "f14", "f15", "f16", "f17", "f18", "f19", "f20",
    "f21", "f22", "f23", "f24",
})
# Буквы/цифры добавляются динамически
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    _ALLOWED_KEYS.add(_c)


def hotkey(combo: str) -> dict:
    """Нажать комбинацию клавиш (ctrl+shift+esc и т.д.)."""
    if not pyautogui:
        return {"ok": False, "detail": "pyautogui недоступен"}
    keys = [k.strip().lower() for k in combo.split("+")]
    if not keys:
        return {"ok": False, "detail": "пустая комбинация"}
    for k in keys:
        if k not in _ALLOWED_KEYS:
            return {"ok": False, "detail": f"неизвестная клавиша: {k}"}
    try:
        pyautogui.hotkey(*keys)
        return {"ok": True, "detail": f"нажала {combo}"}
    except Exception as e:
        return {"ok": False, "detail": f"ошибка хоткея: {e}"}


_TYPE_TEXT_MAX = 2000


def type_text(text: str) -> dict:
    """Напечатать текст в активное окно через буфер обмена + Ctrl+V."""
    if not (pyperclip and pyautogui):
        return {"ok": False, "detail": "pyperclip/pyautogui недоступны"}
    if len(text) > _TYPE_TEXT_MAX:
        return {"ok": False, "detail": f"текст слишком длинный ({len(text)} > {_TYPE_TEXT_MAX})"}
    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        return {"ok": True, "detail": f"напечатала {len(text)} символов"}
    except Exception as e:
        return {"ok": False, "detail": f"ошибка вставки: {e}"}


def focus_window(name: str) -> dict:
    """Найти окно по подстроке заголовка и активировать его."""
    name_lower = name.strip().lower()
    if not name_lower:
        return {"ok": False, "detail": "пустое имя окна"}

    # Попытка через win32gui
    if win32gui:
        found_hwnd = None
        found_title = None

        def _cb(hwnd, _):
            nonlocal found_hwnd, found_title
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and name_lower in title.lower():
                    found_hwnd = hwnd
                    found_title = title

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            pass

        if found_hwnd:
            try:
                win32gui.SetForegroundWindow(found_hwnd)
                return {"ok": True, "detail": f"фокус: {found_title}"}
            except Exception as e:
                return {"ok": False, "detail": f"не удалось активировать окно: {e}"}

    # Fallback через pyautogui
    if pyautogui:
        try:
            wins = pyautogui.getWindowsWithTitle(name)
            if wins:
                wins[0].activate()
                return {"ok": True, "detail": f"фокус: {wins[0].title}"}
        except Exception as e:
            return {"ok": False, "detail": f"pyautogui фокус: {e}"}

    return {"ok": False, "detail": f"окно не найдено: {name}"}


_POWERSHELL_BLOCKLIST = (
    "remove-item -recurse", "remove-item -r",
    "format-", "rd /s", "rd /s /q",
    "del /f /s /q", "del /s /q",
    "stop-computer", "restart-computer",
    "set-executionpolicy", "invoke-webrequest", "iwr ",
    "curl ", "invoke-expression", "iex ",
    "new-service", "schtasks", "reg add", "reg delete",
)


def powershell(cmd: str) -> dict:
    """Выполнить команду в PowerShell с проверкой стоп-листа."""
    cmd_stripped = cmd.strip().lower()
    for blocked in _POWERSHELL_BLOCKLIST:
        if blocked in cmd_stripped:
            return {"ok": False, "detail": f"заблокировано стоп-листом: содержит «{blocked.strip()}»"}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, timeout=15,
        )
        output = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        detail = output[-300:] if len(output) > 300 else output
        ok = r.returncode == 0
        return {"ok": ok, "detail": detail.strip() or ("выполнено" if ok else "ошибка")}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "таймаут 15 секунд"}
    except Exception as e:
        return {"ok": False, "detail": f"ошибка: {e}"}


# ── Command Registry Integration ──────────────────────────────────────

def match_voice_command(text: str, lang: str = "ru") -> dict | None:
    """Match a voice command against the command registry.

    Returns {"action": str, "args": str, "confidence": float} or None.
    This can be used by the VPS to pre-process commands before sending.
    """
    registry = get_command_registry()
    result = registry.match(text, lang)
    if result:
        return {
            "action": result.action,
            "args": result.args,
            "confidence": result.confidence,
            "command_id": result.command.id,
            "slots": result.slots,
        }
    return None


def get_capabilities() -> list[str]:
    """Return list of capabilities this agent supports."""
    caps = []
    if sd:
        caps.append("voice")
    if sd:
        caps.append("tts")
    if ImageGrab:
        caps.append("screenshot")
    if win32gui:
        caps.extend(["apps", "browser", "music", "system"])
    if pyperclip and pyautogui:
        caps.append("dictate")
    return caps