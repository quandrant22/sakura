"""Полнота команд: все агентные действия реестра (sakura_core/capabilities.yaml,
executor: agent) доходят из Agent._run_command до исполнителя и возвращают
command_result. Исполнители подменены записывающими фейками — ничего не
запускается по-настоящему.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from desktop.core import agent as agent_module
from desktop.core import browser, kettle, music, yamusic_app

CAPS = Path(__file__).resolve().parents[2] / "sakura_core" / "capabilities.yaml"
AGENT_CAPS = [c for c in yaml.safe_load(CAPS.read_text(encoding="utf-8"))
              if c.get("executor") == "agent"]
EXPECTED_DOMAINS = {"browser": 10, "app": 2, "close_window": 1, "ext": 2, "game_mode": 2,
                    "music": 18, "system": 6, "open": 1, "screenshot": 2, "youtube": 12,
                    "kettle": 5, "files": 1}
ARGS = {"system.volume": "50", "kettle.heat": "80", "kettle.boil_heat": "80",
        "open.app": "telegram", "files.open": "отчёт", "app.switch": "telegram",
        "app.switch_open": "telegram", "music.volume_up": "20", "music.volume_down": "5"}


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))


@pytest.fixture
def rec(monkeypatch):
    calls = []

    def sync(name, result=None):
        def f(*a, **k):
            calls.append((name, a))
            return {"result": "ok", "ok": True} if result is None else result
        return f

    def asyn(name, result=None):
        async def f(*a, **k):
            calls.append((name, a))
            return {"ok": True} if result is None else result
        return f

    for n in ("execute_command", "_switch_to_app", "_hotkey", "_type_text", "_focus_window",
              "_powershell"):
        monkeypatch.setattr(agent_module, n, sync(n))
    monkeypatch.setattr(agent_module, "_nudge_volume", sync("_nudge_volume", "ok"))
    monkeypatch.setattr(music, "music_command", asyn("music.music_command"))
    monkeypatch.setattr(browser, "music_action", sync("browser.music_action", "ok"))
    monkeypatch.setattr(browser, "youtube_player_cmd", sync("browser.youtube_player_cmd", "ok"))
    monkeypatch.setattr(yamusic_app, "open_wave", sync("yamusic_app.open_wave", True))
    monkeypatch.setattr(yamusic_app, "play_pause", sync("yamusic_app.play_pause", True))
    monkeypatch.setattr(kettle, "kettle_command", asyn("kettle.kettle_command"))
    ext = SimpleNamespace(is_connected=lambda: True, send_command=asyn("extension.send_command"))
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server", ext)
    return calls


def _agent(calls):
    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = FakeWS()
    # game_mode исполняется событием шины (оверлей/интерфейс) — тоже записываем.
    a.bus = SimpleNamespace(emit=lambda ev, **k: calls.append(("bus." + ev, (k,))))
    a.server_link = None
    a._loop = None
    a._state = "idle"
    a._turn_gen = 0
    return a


def test_registry_has_62_agent_actions():
    from collections import Counter
    assert len(AGENT_CAPS) == 62
    assert dict(Counter(c["id"].split(".")[0] for c in AGENT_CAPS)) == EXPECTED_DOMAINS


@pytest.mark.parametrize("cid", [c["id"] for c in AGENT_CAPS])
def test_action_reaches_executor(cid, rec):
    a = _agent(rec)
    asyncio.run(a._run_command(cid, "c1", ARGS.get(cid, "")))
    assert rec, f"{cid}: ни один исполнитель не вызван"
    results = [m for m in a._ws.sent if m.get("type") == "command_result"]
    assert results and results[-1]["id"] == "c1", f"{cid}: нет command_result"


def test_system_restart_dispatches_restart(rec):
    a = _agent(rec)
    asyncio.run(a._run_command("system.restart", "c1", ""))
    assert ("execute_command", ("system:restart",)) in rec
