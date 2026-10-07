"""tests/test_overlay_eq_speaking.py — set_state переключает set_eq_speaking."""
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


def test_set_state_toggles_eq_speaking():
    _get_app()
    w = SphereCore()
    w._timer.stop()
    calls = []
    w.set_eq_speaking = lambda on: calls.append(bool(on))
    w.set_state("speaking")
    w._timer.stop()
    assert calls == [True]
    w.set_state("idle")
    w._timer.stop()
    assert calls == [True, False]
    w.set_state("thinking")
    w._timer.stop()
    assert calls == [True, False, False]
