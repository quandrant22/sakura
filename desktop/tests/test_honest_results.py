"""Честность результатов: серверу уходит {ok, status, detail}, ok=true только при status=done."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from desktop.core import agent as agent_mod
from desktop.core import kettle, music
from desktop.core.agent import Agent


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def _agent():
    a = Agent.__new__(Agent)
    a._ws = FakeWS()
    a.bus = SimpleNamespace(emit=lambda *a, **k: None)
    a.media = None
    return a


def _run(a, action, arg=""):
    asyncio.run(a._run_command(action, "c1", arg))
    res = [m for m in a._ws.sent if m["type"] == "command_result"]
    assert len(res) == 1
    return res[0]


def test_music_no_active_player_is_not_ok(monkeypatch):
    async def fake(cmd):
        return {"ok": False, "result": "Нет активного плеера"}
    monkeypatch.setattr(music, "music_command", fake)
    r = _run(_agent(), "music.next")
    assert (r["ok"], r["status"], r["detail"]) == (False, "noop", "Нет активного плеера")


def test_music_done(monkeypatch):
    async def fake(cmd):
        return {"ok": True, "result": "следующий"}
    monkeypatch.setattr(music, "music_command", fake)
    assert _run(_agent(), "music.next")["status"] == "done"


@pytest.mark.parametrize("legacy,status", [
    ("неизвестная команда: foo", "unsupported"),
    ("Opera не найдена", "failed"),
    ("громкость 50%", "done"),
])
def test_fallback_execute_command(monkeypatch, legacy, status):
    monkeypatch.setattr(agent_mod, "execute_command", lambda full: {"result": legacy})
    r = _run(_agent(), "some_legacy_verb")
    assert r["status"] == status and r["ok"] is (status == "done")


def test_empty_action_is_failed():
    a = _agent()
    asyncio.run(a._run_command("", "c9"))
    assert a._ws.sent[0]["ok"] is False and a._ws.sent[0]["status"] == "failed"


def test_screenshot_failure_reported(monkeypatch):
    monkeypatch.setattr(agent_mod, "execute_command", lambda full: {"screenshot": None})
    r = _run(_agent(), "screenshot.run")
    assert r["ok"] is False and r["status"] == "failed"


def test_extension_not_connected_is_unsupported(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: False, send_command=None))
    r = _run(_agent(), "ext.page_content")
    assert r["status"] == "unsupported" and "расширение" in r["detail"]


def test_kettle_not_paired_is_quiet_unsupported(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(kettle, "KEY_FILE", str(tmp_path / "nokey.json"))
    monkeypatch.setattr(kettle._config, "KETTLE_PAIR", False)
    called = []
    monkeypatch.setattr(kettle.KettleClient, "run", lambda self, a: called.append(a))
    out = asyncio.run(kettle.kettle_command("boil"))
    assert out == {"ok": False, "status": "unsupported", "detail": "чайник не сопряжён с этим компьютером"}
    assert called == [] and not [r for r in caplog.records if r.levelname == "ERROR"]


def test_kettle_watch_only_after_success(monkeypatch):
    spawned = []
    monkeypatch.setattr(agent_mod, "spawn", lambda coro, name=None: (spawned.append(name), coro.close()))

    async def failed(action):
        return {"ok": False, "result": "Не удалось включить"}

    async def ok(action):
        return {"ok": True, "result": "Чайник кипятится"}

    monkeypatch.setattr(kettle, "kettle_command", failed)
    assert _run(_agent(), "kettle:boil")["ok"] is False
    assert spawned == []  # раньше `a and b or c` запускал наблюдение и после неудачи

    monkeypatch.setattr(kettle, "kettle_command", ok)
    assert _run(_agent(), "kettle:boil")["ok"] is True
    assert spawned == ["kettle-watch"]


def test_key_path_is_absolute():
    import os
    assert os.path.isabs(kettle.KEY_FILE)


def test_shutdown_announces_pending_and_cancel(monkeypatch):
    # Подставной исполнитель: execute_command не выключает компьютер.
    events = []
    a = _agent()
    a.bus = SimpleNamespace(emit=lambda ev, **k: events.append((ev, k)))
    monkeypatch.setattr(agent_mod, "execute_command", lambda full: {"result": "выключение через 30 с"})
    _run(a, "system.shutdown")
    assert ("power_pending", {"action": "shutdown", "seconds": 30}) in events
    a2 = _agent()
    a2.bus = a.bus
    monkeypatch.setattr(agent_mod, "execute_command", lambda full: {"result": "выключение отменено"})
    _run(a2, "system.shutdown_cancel")
    assert ("power_cancelled", {}) in events
