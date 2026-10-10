"""desktop.core.platform.windows — реализация Platform для Windows.

Фаза 0: перенесён только простой пользователя (agent/core/idle.py).
Остальные методы переносятся из agent/core/hands.py, presence.py и
music_listener.py в Фазе 1.1 и до тех пор бросают NotImplementedError.
"""
import ctypes
import sys

from ._stub import make_stub

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
