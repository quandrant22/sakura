"""tests/test_tray_game_mode.py — галочка трея следит за bridge.gameMode."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.app import UiBridge, build_tray

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


class _Bus:
    def subscribe(self, fn):
        self.fn = fn


class _Overlay:
    def __init__(self):
        self.calls = []

    def set_game_mode(self, on):
        self.calls.append(bool(on))


def test_tray_check_follows_bridge():
    _get_app()
    bus = _Bus()
    bridge = UiBridge(bus)
    ov = _Overlay()
    tray = build_tray(_get_app(), ov, bridge)
    menu = tray.contextMenu()
    action = [a for a in menu.actions() if a.isCheckable()][0]
    assert not action.isChecked()
    bridge.gameMode.emit(True)
    assert action.isChecked()
    # Цикла нет: синхронизация не дёргает overlay.set_game_mode
    assert ov.calls == []
    bridge.gameMode.emit(False)
    assert not action.isChecked()
    assert ov.calls == []
