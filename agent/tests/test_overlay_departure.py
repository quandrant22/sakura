"""tests/test_overlay_departure.py — «уход» гасит окно только без недавнего ввода."""
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer

from core import idle
from ui import overlay as ov


class _FakeWindow:
    """Только то, что трогает animate_departure: прозрачность окна."""
    def __init__(self, opacity=1.0):
        self._op = opacity

    def windowOpacity(self):
        return self._op

    def setWindowOpacity(self, op):
        self._op = op


def _run_departure(win, idle_s, floor=0.7, idle_limit=120.0):
    # QTimer.singleShot выполняем сразу — анимация доходит до конца синхронно.
    with patch.object(idle, "idle_seconds", return_value=idle_s), \
         patch.object(QTimer, "singleShot", side_effect=lambda _ms, fn: fn()), \
         patch.object(ov.config, "OVERLAY_DEPARTURE_OPACITY", floor, create=True), \
         patch.object(ov.config, "OVERLAY_DEPART_IDLE_S", idle_limit, create=True):
        ov.Overlay.animate_departure(win)
    return win.windowOpacity()


def test_recent_input_keeps_opacity():
    assert _run_departure(_FakeWindow(1.0), idle_s=5) == 1.0


def test_no_input_fades_to_floor_not_below():
    assert abs(_run_departure(_FakeWindow(1.0), idle_s=600) - 0.7) < 1e-9


def test_floor_one_means_no_dimming():
    assert _run_departure(_FakeWindow(1.0), idle_s=600, floor=1.0) == 1.0


def test_thresholds_follow_limits():
    assert _run_departure(_FakeWindow(1.0), idle_s=30, idle_limit=10, floor=0.5) == 0.5
    assert _run_departure(_FakeWindow(1.0), idle_s=30, idle_limit=60, floor=0.5) == 1.0


def test_env_changes_config_values(monkeypatch):
    monkeypatch.setenv("OVERLAY_DEPARTURE_OPACITY", "0.9")
    monkeypatch.setenv("OVERLAY_DEPART_IDLE_S", "15")
    monkeypatch.setenv("OVERLAY_PANEL_ALPHA", "250")
    path = Path(__file__).resolve().parents[1] / "config.py"
    spec = importlib.util.spec_from_file_location("cfg_overlay_env", path)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    assert cfg.OVERLAY_DEPARTURE_OPACITY == 0.9
    assert cfg.OVERLAY_DEPART_IDLE_S == 15
    assert cfg.OVERLAY_PANEL_ALPHA == 250
