"""desktop.core.platform.fso — WinAPI и реестр для полноэкранных игр (логика — desktop/core/fullscreen.py).

Только здесь (правило «windll/winreg — только в platform/», tests/test_platform.py):
  • notification_state() — SHQueryUserNotificationState (эксклюзивное D3D-приложение = 3);
  • read_layer / write_layer — AppCompatFlags\\Layers (галка «Отключить оптимизацию во весь экран»);
  • fse_behavior_mode / set_fse_behavior_mode — GameConfigStore (FSO для всех игр).
Вне Windows — нейтральные значения.
"""
from __future__ import annotations

import sys

LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
GAMECONFIG_KEY = r"System\GameConfigStore"
IS_WINDOWS = sys.platform == "win32"


def notification_state() -> int | None:
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        state = ctypes.c_int(0)
        hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        return state.value if hr == 0 else None
    except Exception:  # noqa: BLE001
        return None


def read_layer(exe_path: str, machine: bool = False) -> str:
    if not IS_WINDOWS or not exe_path:
        return ""
    import winreg
    hive = winreg.HKEY_LOCAL_MACHINE if machine else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(hive, LAYERS_KEY) as k:
            value, _ = winreg.QueryValueEx(k, exe_path)
            return str(value or "")
    except OSError:
        return ""


def write_layer(exe_path: str, value: str) -> None:
    """Записать слои совместимости игры в HKCU; пустая строка — удалить значение. OSError — наружу."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LAYERS_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        if value:
            winreg.SetValueEx(k, exe_path, 0, winreg.REG_SZ, value)
        else:
            winreg.DeleteValue(k, exe_path)


def fse_behavior_mode() -> int | None:
    if not IS_WINDOWS:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GAMECONFIG_KEY) as k:
            mode, _ = winreg.QueryValueEx(k, "GameDVR_FSEBehaviorMode")
            return int(mode)
    except (OSError, ValueError, TypeError):
        return None


def set_fse_behavior_mode(mode: int) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GAMECONFIG_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "GameDVR_FSEBehaviorMode", 0, winreg.REG_DWORD, int(mode))
