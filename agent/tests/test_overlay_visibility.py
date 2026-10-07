"""tests/test_overlay_visibility.py — таймер спит когда окно скрыто."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.overlay import SphereCore

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


def test_hidden_window_stops_timer_and_ignores_mic():
    _get_app()
    w = SphereCore()
    w.show()
    assert w._timer.isActive()
    before = list(w._eq_target)
    w.hide()
    assert not w._timer.isActive()
    w.set_audio_level([0.9] * 8)
    assert list(w._eq_target) == before
    w.show()
    assert w._timer.isActive()
    w.set_audio_level([0.9] * 8)
    assert list(w._eq_target) != before


def test_set_state_hidden_does_not_start_timer():
    _get_app()
    w = SphereCore()
    w.hide()
    w.set_state("thinking")
    assert not w._timer.isActive()
    w.show()
    assert w._timer.isActive()
    assert w._timer.interval() == 33
