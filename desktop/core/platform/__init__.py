"""desktop.core.platform — платформенный слой (единственное место для вызовов ОС).

get_platform() возвращает реализацию для текущей ОС. Прямые вызовы
ctypes.windll и т.п. вне этого пакета запрещены (проверяется тестом).
"""
import sys

from .base import Platform

_instance: Platform | None = None


def get_platform() -> Platform:
    global _instance
    if _instance is None:
        if sys.platform == "win32":
            from .windows import WindowsPlatform as cls
        elif sys.platform == "darwin":
            from .macos import MacosPlatform as cls
        else:
            from .linux import LinuxPlatform as cls
        _instance = cls()
    return _instance
