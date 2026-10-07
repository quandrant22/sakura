"""tests/test_overlay_game_theme.py — _apply_game_theme пишет self._panel_bg."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.overlay import Overlay, _PANEL_BG

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


def test_no_theme_keeps_default_panel():
    _get_app()
    o = Overlay()
    # Без game_theme _panel_bg не выставляется — paintEvent рисует дефолт
    assert getattr(o, "_panel_bg", None) is None
    o.set_mood({"color": "#ffb36b"})
    assert getattr(o, "_panel_bg", None) is None


def test_game_theme_sets_panel_bg():
    _get_app()
    o = Overlay()
    o.set_mood({"color": "#ffb36b",
                "game_theme": {"orb": "#ff0000", "color": "#112233"}})
    bg = o._panel_bg
    assert (bg.red(), bg.green(), bg.blue(), bg.alpha()) == (0x11, 0x22, 0x33, 210)
    assert bg != _PANEL_BG
