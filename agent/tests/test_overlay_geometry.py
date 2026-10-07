"""tests/test_overlay_geometry.py — дебаунс сохранения геометрии 500 мс."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.overlay import Overlay

_app = None


def _get_app():
    global _app
    inst = QApplication.instance()
    if inst is not None:
        _app = inst
        return inst
    if _app is None:
        _app = QApplication([])
    return _app


def test_geometry_save_debounced():
    _get_app()
    o = Overlay()
    assert o._geom_save_timer.isSingleShot()
    assert o._geom_save_timer.interval() == 500
    saved = []
    o._save_geometry = lambda: saved.append(1)
    o.show()
    o.move(10, 10)
    # Дебаунс: таймер взведён, немедленной записи нет
    assert o._geom_save_timer.isActive()
    assert saved == []
