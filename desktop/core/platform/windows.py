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
except ImportError:
    win32gui = None

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

    def media_key(self, kind: str) -> None:
        vk = MEDIA_VK.get(kind)
        if vk is None:
            raise ValueError(f"неизвестная медиа-команда: {kind}")
        if not self.press_virtual_key(vk):
            raise OSError("медиаклавиша не отправлена")

    # ── окна ───────────────────────────────────────────────────────
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
        cmd = POWER_COMMANDS.get(action)
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


KEYEVENTF_KEYUP = 0x0002
MEDIA_VK = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1,
            "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF}
# Подтверждение выключения уже получено на сервере (modules/ws_handlers.py).
POWER_COMMANDS = {
    "shutdown": ["shutdown", "/s", "/t", "0", "/c", "Команда Сакуры"],
    "restart": ["shutdown", "/r", "/t", "0", "/c", "Команда Сакуры"],
    "shutdown_cancel": ["shutdown", "/a"],
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
}
