"""desktop.core.game_hud.dpi — Windows DPI Awareness для согласования координат окон и захвата экрана."""

import logging

from desktop.core.platform import get_platform

log = logging.getLogger("sakura.game_hud.dpi")

_dpi_set = False


def ensure_dpi_aware() -> bool:
    """Устанавливает Per-Monitor DPI Awareness для текущего процесса Python через платформенный слой.
    Гарантирует, что win32gui.GetClientRect / GetWindowRect возвращают реальные физические пиксели,
    совпадающие с буфером захвата mss / dxcam.
    """
    global _dpi_set
    if _dpi_set:
        return True
    try:
        if get_platform().enable_dpi_awareness():
            _dpi_set = True
            log.debug("[dpi] Per-Monitor DPI awareness установлен")
            return True
    except NotImplementedError:
        _dpi_set = True
        return True
    except Exception as e:
        log.warning("[dpi] Ошибка установки DPI awareness: %s", e)
    return False
