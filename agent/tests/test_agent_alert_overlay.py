"""tests/test_agent_alert_overlay.py — событие agent_alert доходит до оверлея."""
import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core import agent as agent_module
from ui.app import UiBridge
from ui.overlay import Overlay

ALERT = "Не задан WS_TOKEN (.env) — агент не подключается"

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
    """Мини-шина: как core EventBus — subscribe + emit(event, **data)."""

    def __init__(self):
        self._subs = []

    def subscribe(self, fn):
        self._subs.append(fn)

    def emit(self, event, **data):
        for fn in self._subs:
            fn(event, data)


def test_empty_token_alert_reaches_overlay(monkeypatch):
    _get_app()
    monkeypatch.setattr(agent_module.config, "WS_TOKEN", "")
    bus = _Bus()
    bridge = UiBridge(bus)
    o = Overlay()
    bridge.agentAlert.connect(o.add_system_message)

    a = agent_module.Agent.__new__(agent_module.Agent)
    a.bus = bus
    asyncio.run(a.run())           # возвращается, приложение живёт дальше

    assert any(ALERT in m for m in o._messages)
    assert ALERT in o.last_msg.text()          # всплывающая реплика
