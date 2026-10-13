"""desktop.core.platform.windows — реализация Platform для Windows.

Перенесено из agent/core: простой (idle.py), медиаклавиши (hands.media_key,
browser._media), питание (hands.execute_command «system»), путь Steam
(hands._steam_path), активация окна (hands._activate_hwnd).
Методы, которые ещё не перенесены, бросают NotImplementedError (заглушка).
"""
import ctypes
import os
import subprocess
import sys
import time

from ._stub import make_stub

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = win32process = None

# Браузеры: окно ищется по исполняемому файлу И классу окна. Только класс не годится —
# Chrome_WidgetWin_1 есть и у Electron-приложений (VS Code, сама Сакура).
BROWSER_EXES = frozenset({"chrome.exe", "msedge.exe", "opera.exe", "brave.exe", "browser.exe",
                          "firefox.exe", "vivaldi.exe", "yandex.exe"})
BROWSER_CLASSES = frozenset({"Chrome_WidgetWin_1", "MozillaWindowClass"})


def pick_browser_window(windows):
    """Из окон в порядке z-order (верхнее первым) — первое окно браузера.

    windows: [(hwnd, title, exe, cls)]. Возвращает (hwnd, title) или None.
    """
    for hwnd, title, exe, cls in windows:
        if title and (exe or "").lower() in BROWSER_EXES and cls in BROWSER_CLASSES:
            return hwnd, title
    return None

IDLE_UNKNOWN = 10 ** 9


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _query_idle() -> float:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        raise OSError("GetLastInputInfo failed")
    # Оба счётчика 32-битные: разница по модулю 2^32 переживает переполнение.
    ms = (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
    return ms / 1000.0


_SESSION_EXPIRED = 2  # AudioSessionStateExpired


def pick_app_sessions(sessions, names, procs) -> list:
    """Громкости сессий приложения: сессия процесса, чьё имя или имя предка совпадает с names.

    Chromium/Electron играет звук из дочернего процесса (audio service), у главного сессии нет.
    sessions: [(pid, state, volume)], procs: {pid: (имя в нижнем регистре, ppid)}.
    Истёкшие сессии пропускаются; активные — первыми (по ним читается громкость).
    """
    wanted = tuple(n.lower() for n in names)

    def belongs(pid) -> bool:
        seen = set()
        while pid and pid not in seen and pid in procs:
            seen.add(pid)
            name, ppid = procs[pid]
            if any(w in name for w in wanted):
                return True
            pid = ppid
        return False
    hits = [(state, vol) for pid, state, vol in sessions if state != _SESSION_EXPIRED and belongs(pid)]
    hits.sort(key=lambda h: h[0] != 1)  # 1 — AudioSessionStateActive
    return [vol for _, vol in hits]


class WindowsPlatform(make_stub("windows")):
    name = "windows"

    def idle_seconds(self) -> float:
        if sys.platform != "win32":
            return float(IDLE_UNKNOWN)
        try:
            return _query_idle()
        except Exception:
            return float(IDLE_UNKNOWN)

    # ── клавиши ────────────────────────────────────────────────────
    def press_virtual_key(self, vk: int, hold: float = 0.0) -> bool:
        if os.name != "nt":
            return False
        try:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            if hold:
                time.sleep(hold)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception:
            return False

    # ── громкость отдельного приложения (сессия микшера, ISimpleAudioVolume) ──
    @staticmethod
    def _app_sessions(names):
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        import psutil
        from pycaw.pycaw import AudioUtilities
        procs = {}
        for p in psutil.process_iter(["pid", "name", "ppid"]):
            procs[p.info["pid"]] = ((p.info["name"] or "").lower(), p.info["ppid"])
        sessions = [(s.ProcessId, s.State, s.SimpleAudioVolume) for s in AudioUtilities.GetAllSessions()]
        return pick_app_sessions(sessions, names, procs)

    def app_volume_get(self, names):
        try:
            vols = self._app_sessions(names)
        except Exception:
            return None
        return round(vols[0].GetMasterVolume() * 100) if vols else None

    def app_volume_set(self, names, percent):
        try:
            vols = self._app_sessions(names)
        except Exception:
            return None
        if not vols:
            return None
        level = max(0, min(100, int(percent)))
        for v in vols:  # у приложения бывает несколько сессий — двигаем все
            v.SetMasterVolume(level / 100.0, None)
        return level

    def media_key(self, kind: str) -> None:
        vk = MEDIA_VK.get(kind)
        if vk is None:
            raise ValueError(f"неизвестная медиа-команда: {kind}")
        if not self.press_virtual_key(vk):
            raise OSError("медиаклавиша не отправлена")

    # ── окна ───────────────────────────────────────────────────────
    def _top_level_windows(self):
        """Видимые окна верхнего уровня в порядке z-order: [(hwnd, title, exe, cls)]."""
        import psutil
        out = []

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                exe = psutil.Process(pid).name()
            except Exception:
                exe = ""
            out.append((hwnd, win32gui.GetWindowText(hwnd), exe, win32gui.GetClassName(hwnd)))
        win32gui.EnumWindows(_cb, None)
        return out

    def close_browser_window(self) -> str | None:
        if not win32gui:
            return None
        hit = pick_browser_window(self._top_level_windows())
        if hit is None:
            return None
        hwnd, title = hit
        WM_CLOSE = 0x0010
        win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
        return title

    # ── окна (п. 2.3) ──────────────────────────────────────────────
    def windows(self) -> list[dict]:
        if not win32gui:
            return []
        return [{"hwnd": h, "title": t, "process": exe} for h, t, exe, _cls in self._top_level_windows() if t]

    def foreground_window(self) -> dict | None:
        if not win32gui:
            return None
        h = win32gui.GetForegroundWindow()
        if not h:
            return None
        exe = ""
        try:
            import psutil
            _, pid = win32process.GetWindowThreadProcessId(h)
            exe = psutil.Process(pid).name()
        except Exception:
            pass
        return {"hwnd": h, "title": win32gui.GetWindowText(h), "process": exe}

    def window_show(self, hwnd: int, state: str) -> bool:
        cmd = {"minimize": 6, "maximize": 3, "restore": 9}.get(state)  # SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE
        if cmd is None or not win32gui:
            return False
        win32gui.ShowWindow(hwnd, cmd)
        return True

    @staticmethod
    def _monitors() -> list[tuple[int, int, int, int]]:
        import win32api
        out = []
        for hmon, _hdc, _rect in win32api.EnumDisplayMonitors():
            out.append(tuple(win32api.GetMonitorInfo(hmon)["Work"]))
        return out

    def window_snap(self, hwnd: int, side: str) -> bool:
        import win32api
        if not win32gui or side not in ("left", "right", "top"):
            return False
        info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))
        x0, y0, x1, y1 = info["Work"]
        if side == "top":
            win32gui.ShowWindow(hwnd, 3)
            return True
        win32gui.ShowWindow(hwnd, 9)
        half = (x1 - x0) // 2
        x = x0 if side == "left" else x0 + half
        win32gui.MoveWindow(hwnd, x, y0, half, y1 - y0, True)
        return True

    def window_to_monitor(self, hwnd: int, target: str) -> bool:
        import win32api
        if not win32gui:
            return False
        mons = self._monitors()
        if len(mons) < 2:
            return False
        cur = tuple(win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))["Work"])
        idx = mons.index(cur) if cur in mons else 0
        if target == "next":
            dst = mons[(idx + 1) % len(mons)]
        elif target.isdigit() and 1 <= int(target) <= len(mons):
            dst = mons[int(target) - 1]
        else:
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = min(right - left, dst[2] - dst[0]), min(bottom - top, dst[3] - dst[1])
        # То же смещение от угла рабочей области, но окно целиком на новом мониторе.
        x = dst[0] + max(0, min(left - cur[0], dst[2] - dst[0] - w))
        y = dst[1] + max(0, min(top - cur[1], dst[3] - dst[1] - h))
        win32gui.ShowWindow(hwnd, 9)
        win32gui.MoveWindow(hwnd, x, y, w, h, True)
        return True

    # ── экран, звук, сеть, файлы (п. 2.3) ──────────────────────────
    def display_off(self) -> None:
        HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER = 0xFFFF, 0x0112, 0xF170
        ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)

    def set_brightness(self, percent: int) -> bool:
        # WMI: работает для встроенного экрана ноутбука; внешний монитор без DDC/CI — False.
        level = max(0, min(100, int(percent)))
        cmd = ("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop)"
               f" | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}}")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10)
        return r.returncode == 0

    def mic_mute(self, mute: bool | None) -> bool | None:
        try:
            import comtypes
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            mic = AudioUtilities.GetMicrophone()
            if mic is None:
                return None
            vol = cast(mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
            target = (not vol.GetMute()) if mute is None else bool(mute)
            vol.SetMute(int(target), None)
            return bool(vol.GetMute())
        except Exception:
            return None

    def radio(self, kind: str, on: bool) -> bool:
        # Windows.Devices.Radios — как переключатель в Центре уведомлений, без прав администратора.
        import asyncio as _aio

        from winsdk.windows.devices.radios import Radio, RadioKind, RadioState
        want = {"wifi": RadioKind.WI_FI, "bluetooth": RadioKind.BLUETOOTH}.get(kind)
        if want is None:
            return False

        async def go():
            await Radio.request_access_async()
            radios = [r for r in await Radio.get_radios_async() if r.kind == want]
            if not radios:
                return False
            for r in radios:
                await r.set_state_async(RadioState.ON if on else RadioState.OFF)
            return True
        return bool(_aio.run(go()))

    def recycle(self, path: str) -> bool:
        # SHFileOperationW + FOF_ALLOWUNDO — только в корзину, без окна подтверждения Windows.
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16),
                        ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
        FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
        op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None,
                             FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted

    def reveal(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        subprocess.Popen(["explorer", "/select,", os.path.abspath(path)])
        return True

    def focused_is_password(self) -> bool:
        try:
            from desktop.core.platform import uia
            return uia.focused_is_password()
        except Exception:
            return True  # не удалось проверить — считаем полем пароля и не печатаем

    def activate_window_handle(self, hwnd: int) -> bool:
        """Вывести окно вперёд с обходом блокировки переднего плана Windows."""
        if not win32gui:
            return False
        try:
            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            VK_MENU = 0x12
            try:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, SW_RESTORE)
            except Exception:
                pass
            try:
                fg = user32.GetForegroundWindow()
                fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                cur_tid = user32.GetCurrentThreadId()
                attached = False
                if fg and fg_tid and fg_tid != cur_tid:
                    try:
                        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
                    except Exception:
                        attached = False
                try:
                    user32.keybd_event(VK_MENU, 0, 0, 0)
                    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                except Exception:
                    pass
                try:
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
                try:
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        try:
                            user32.AttachThreadInput(cur_tid, fg_tid, False)
                        except Exception:
                            pass
            except Exception:
                win32gui.SetForegroundWindow(hwnd)
            try:
                return user32.GetForegroundWindow() == hwnd
            except Exception:
                return True
        except Exception:
            return False

    # ── система ────────────────────────────────────────────────────
    def power(self, action: str) -> None:
        if action == "lock":
            ctypes.windll.user32.LockWorkStation()
            return
        if action == "sleep":
            # Прямой вызов API: bHibernate=False — именно сон. rundll32 передавал строку вместо трёх
            # BOOL, и при включённой гибернации компьютер уходил в гибернацию.
            ctypes.windll.powrprof.SetSuspendState(False, True, False)
            return
        cmd = power_command(action)
        if cmd is None:
            raise ValueError(f"неизвестная системная команда: {action}")
        subprocess.Popen(cmd)

    def steam_path(self) -> str | None:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                return winreg.QueryValueEx(k, "SteamPath")[0]
        except Exception:
            for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
                if os.path.isdir(p):
                    return p
        return None

    def open_path(self, target: str) -> bool:
        try:
            os.startfile(target)  # программа по умолчанию для файла / URL
            return True
        except OSError:
            return False

    def restrict_to_current_user(self, path: str) -> None:
        # Убрать наследуемые права и выдать полный доступ только текущему пользователю.
        user = os.environ.get("USERNAME") or os.getlogin()
        domain = os.environ.get("USERDOMAIN")
        who = f"{domain}\\{user}" if domain else user
        subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", f"{who}:F"],
                       check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


KEYEVENTF_KEYUP = 0x0002
MEDIA_VK = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1,
            "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF}
# Подтверждение выключения уже получено на сервере (modules/ws_handlers.py); выключение и
# перезагрузка — с задержкой SHUTDOWN_DELAY_S, чтобы «отмени выключение» (shutdown /a) успело.
def power_command(action: str, delay_s: int | None = None) -> list[str] | None:
    from desktop.core import config
    delay = str(max(0, int(config.SHUTDOWN_DELAY_S if delay_s is None else delay_s)))
    return {
        "shutdown": ["shutdown", "/s", "/t", delay, "/c", "Команда Сакуры"],
        "restart": ["shutdown", "/r", "/t", delay, "/c", "Команда Сакуры"],
        "shutdown_cancel": ["shutdown", "/a"],
    }.get(action)
