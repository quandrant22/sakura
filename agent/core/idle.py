"""core/idle.py — сколько секунд пользователь ничего не вводил (клавиатура/мышь).

Windows: GetLastInputInfo + GetTickCount. Если вызов не удался — большое
число (считаем, что пользователь отошёл).
"""
import ctypes
import sys

IDLE_UNKNOWN = 10 ** 9


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _query() -> float:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        raise OSError("GetLastInputInfo failed")
    # Оба счётчика 32-битные: разница по модулю 2^32 переживает переполнение.
    ms = (kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
    return ms / 1000.0


def idle_seconds() -> float:
    if sys.platform != "win32":
        return float(IDLE_UNKNOWN)
    try:
        return _query()
    except Exception:
        return float(IDLE_UNKNOWN)
