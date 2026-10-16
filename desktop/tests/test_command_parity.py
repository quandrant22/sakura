"""Полнота команд: все 62 агентных действия реестра (sakura_core/capabilities.yaml,
executor: agent) в том виде, в каком их шлёт сервер (tests/fixtures/agent_wire_actions.json),
доходят из Agent._run_command до исполнителя и возвращают command_result без ошибки.

Шаг 1: Agent._run_command с записывающими фейками исполнителей.
Шаг 2: если команда ушла в hands.execute_command — та же строка проходит через
настоящий execute_command (побочные эффекты подменены) и не даёт «неизвестная …».
"""
import asyncio
import inspect
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from desktop.core import agent as agent_module
from desktop.core import browser, hands, kettle, music, yamusic_app
from desktop.core.platform import windows

ROOT = Path(__file__).resolve().parents[2]
_CAPS_TEXT = (ROOT / "sakura_core" / "capabilities.yaml").read_text(encoding="utf-8")
AGENT_CAPS = [c for c in yaml.safe_load(_CAPS_TEXT) if c.get("executor") == "agent"]
WIRE = json.loads((Path(__file__).parent / "fixtures" / "agent_wire_actions.json")
                  .read_text(encoding="utf-8"))["wire"]
# computer.do — только вместе с серверным computer_step (решение владельца).
KNOWN_UNSUPPORTED = {"computer.do"}
EXPECTED_DOMAINS = {"browser": 10, "app": 2, "close_window": 1, "ext": 2, "game_mode": 2,
                    "music": 20, "system": 6, "open": 1, "screenshot": 2, "youtube": 12,
                    "kettle": 5, "files": 6, "window": 7, "power": 3, "process": 2, "clipboard": 3,
                    "display": 2, "audio": 1, "net": 2, "keys": 3, "ui": 4, "computer": 1}


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))


def _sync(calls, name, result=None):
    def f(*a, **k):
        calls.append((name, a))
        return {"result": "ok", "ok": True} if result is None else result
    return f


def _async(calls, name, result=None):
    async def f(*a, **k):
        calls.append((name, a))
        return {"ok": True} if result is None else result
    return f


@pytest.fixture
def rec(monkeypatch):
    calls = []
    for n in ("execute_command", "_switch_to_app", "_hotkey", "_type_text", "_focus_window",
              "_powershell"):
        monkeypatch.setattr(agent_module, n, _sync(calls, n))
    monkeypatch.setattr(agent_module, "_nudge_volume", _sync(calls, "_nudge_volume", "ok"))
    monkeypatch.setattr(music, "music_command", _async(calls, "music.music_command"))
    monkeypatch.setattr(browser, "youtube_player_cmd", _sync(calls, "browser.youtube_player_cmd", "ok"))
    monkeypatch.setattr(yamusic_app, "open_wave", _sync(calls, "yamusic_app.open_wave", True))
    monkeypatch.setattr(yamusic_app, "play_pause", _sync(calls, "yamusic_app.play_pause", True))
    monkeypatch.setattr(kettle, "kettle_command", _async(calls, "kettle.kettle_command"))

    class Remote:  # пульт приложения Яндекс.Музыки (SMTC, сессия)
        async def control(self, op, value=None):
            calls.append(("yandex_remote." + op, (value,)))
            return {"ok": True, "status": "done", "detail": op}
    monkeypatch.setattr(agent_module, "_yamusic_remote", Remote)
    # Управление ПК (control) — только запись: тест не должен ничего делать с компьютером (power.lock и т.п.).
    from desktop.core import control

    def fake_execute(action, arg="", confirmed=False):
        calls.append(("control.execute", (action, arg, confirmed)))
        return {"ok": True, "status": "done", "detail": "ok"}
    monkeypatch.setattr(control, "execute", fake_execute)
    ext = SimpleNamespace(is_connected=lambda: True, send_command=_async(calls, "extension.send_command"))
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server", ext)
    return calls


def _patch_hands_side_effects(monkeypatch) -> list:
    """Настоящий hands.execute_command, но без реальных побочных эффектов."""
    calls = []
    for n in ("open_app", "open_file", "close_window", "close_browser", "set_volume", "nudge_volume",
              "take_screenshot", "remember_app", "open_youtube", "media_key"):
        monkeypatch.setattr(hands, n, _sync(calls, f"hands.{n}", "ok"))
    for n, _fn in inspect.getmembers(browser, inspect.isfunction):
        if n.startswith(("browser_", "music_", "youtube_", "open_")):
            monkeypatch.setattr(browser, n, _sync(calls, f"browser.{n}", "ok"))
    monkeypatch.setattr(hands, "switch_to_app",
                        _sync(calls, "hands.switch_to_app", {"ok": True, "detail": "ok"}))
    monkeypatch.setattr(windows.WindowsPlatform, "power", lambda self, a: calls.append(("power", (a,))))
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: False))
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


def test_registry_has_62_agent_actions_and_wire_for_each():
    assert len(AGENT_CAPS) == 97
    assert dict(Counter(c["id"].split(".")[0] for c in AGENT_CAPS)) == EXPECTED_DOMAINS
    assert sorted(WIRE) == sorted(c["id"] for c in AGENT_CAPS)


@pytest.mark.parametrize("cid", [c["id"] for c in AGENT_CAPS])
def test_action_reaches_executor(cid, rec):
    action, arg = WIRE[cid]
    a = _agent(rec)
    asyncio.run(a._run_command(action, "c1", arg))
    assert rec, f"{cid}: ни один исполнитель не вызван"
    results = [m for m in a._ws.sent if m.get("type") == "command_result"]
    assert results and results[-1]["id"] == "c1", f"{cid}: нет command_result"
    last = results[-1]
    if cid in KNOWN_UNSUPPORTED:  # осознанно не делается — честный отказ, а не ошибка
        assert last["status"] == "unsupported", f"{cid}: ожидался честный отказ, пришло {last}"
        return
    assert last.get("ok", True) is not False and "error" not in str(last.get("detail", "")), \
        f"{cid}: ошибка исполнения {last}"


@pytest.mark.parametrize("cid", [c["id"] for c in AGENT_CAPS])
def test_hands_knows_every_verb(cid, rec, monkeypatch):
    """Шаг 2: строка, ушедшая в execute_command, распознаётся настоящим hands."""
    action, arg = WIRE[cid]
    a = _agent(rec)
    asyncio.run(a._run_command(action, "c1", arg))
    sent = [args[0] for name, args in rec if name == "execute_command"]
    if not sent:
        pytest.skip(f"{cid}: исполняется не через hands.execute_command")
    side = _patch_hands_side_effects(monkeypatch)
    out = hands.execute_command(sent[-1])
    text = str(out.get("result", out))
    assert not text.startswith("неизвестная"), f"{cid}: hands не знает «{sent[-1]}» → {text}"
    assert side or "screenshot" in out, f"{cid}: hands ничего не исполнил для «{sent[-1]}»"


@pytest.mark.parametrize("cid,arg", [("app.switch_open", "telegram"), ("kettle.boil", ""), ("kettle.off", ""),
                                     ("kettle.status", ""), ("kettle.heat", "80"), ("kettle.boil_heat", "80")])
def test_registry_id_accepted_as_well_as_wire_name(cid, arg, rec, monkeypatch):
    """Расхождения id реестра и имени на проводе: клиент принимает оба (тот же исполнитель, что и провод)."""
    wire_action, wire_arg = WIRE[cid]
    a = _agent(rec)
    asyncio.run(a._run_command(wire_action, "w", wire_arg))
    via_wire = [name for name, _ in rec]
    rec.clear()
    a = _agent(rec)
    asyncio.run(a._run_command(cid, "i", arg))
    got = [name for name, _ in rec]
    # app.switch_open по id идёт прямо в _switch_to_app (как app.switch), по проводу — через hands: оба — переключение
    same = {"execute_command": "switch", "_switch_to_app": "switch"} if cid.startswith("app.") else {}
    assert [same.get(n, n) for n in got] == [same.get(n, n) for n in via_wire]
    last = [m for m in a._ws.sent if m.get("type") == "command_result"][-1]
    assert "неизвестн" not in str(last.get("detail", ""))
