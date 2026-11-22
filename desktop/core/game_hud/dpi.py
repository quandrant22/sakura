"""desktop.core.game_hud.dpi — Windows DPI Awareness для согласования координат окон и захвата экрана."""

import logging
import sys

log = logging.getLogger("sakura.game_hud.dpi")

_dpi_set = False


def ensure_dpi_aware() -> bool:
    """Устанавливает Per-Monitor DPI Awareness для текущего процесса Python на Windows.
    Гарантирует, что win32gui.GetClientRect / GetWindowRect возвращают реальные физические пиксели,
    совпадающие с буфером захвата mss / dxcam.
    """
    global _dpi_set
    if _dpi_set:
        return True
    if sys.platform != "win32":
        _dpi_set = True
        return True

    try:
        import ctypes
        # 1. Попытка вызвать Per-Monitor V2 (Windows 10 Creators Update+)
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            _dpi_set = True
            log.debug("[dpi] Per-Monitor V2 DPI awareness установлен")
            return True
        except Exception:
            pass

        # 2. Попытка вызвать SetProcessDpiAwareness (Windows 8.1+)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            _dpi_set = True
            log.debug("[dpi] Per-Monitor DPI awareness установлен через shcore")
            return True
        except Exception:
            pass

        # 3. Fallback: базовый SetProcessDPIAware (Vista+)
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _dpi_set = True
            log.debug("[dpi] System DPI awareness установлен через user32")
            return True
        except Exception:
            pass

    except Exception as e:
        log.warning("[dpi] Ошибка установки DPI awareness: %s", e)

    return False
