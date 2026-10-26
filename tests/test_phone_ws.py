"""Телефон через настоящий ws_handler: speak:false, action_run, devices.

Run: python -m pytest tests/test_phone_ws.py -q
"""

import json

import pytest

import config
import modules.tts_server as tts
from modules import ws_auth
from tests.test_proto_devices import (
    GUEST,
    MASTER,
    MASTER2,
    connect,
    kind,
    run,
    server,  # noqa: F401  (фикстура стенда)
)


@pytest.fixture(autouse=True)
def synth(monkeypatch):
    """Синтез без сети: пакет аудио — один; tts_end настоящий."""
    calls = []

    async def fake(text, websocket, device_id, emotion="спокойная"):
        calls.append(text)
        await websocket.send(json.dumps({"type": "tts_chunk", "device_id": device_id, "data": "AA=="}))
        return 1
    monkeypatch.setattr(tts, "_synthesize_and_stream", fake)
    return calls


def _quiet(c, pred=lambda m: m.get("type") in ("tts_chunk", "tts_end")):
    return c.silent(pred, 0.6)


@pytest.mark.parametrize("via", ["voice_command", "chat_send"])
def test_speak_false_gives_reply_without_audio(server, synth, via):    # noqa: F811
    async def sc(uri):
        c = await connect(uri, MASTER)
        await c.send({"type": via, "text": "найди телефон", "speak": False})
        reply = await c.wait(kind("reply"))
        quiet = await _quiet(c)
        return reply, quiet
    reply, quiet = run(sc)
    assert reply["text"] == "Телефон не на связи" and reply["kind"] == "error"
    assert quiet, "ни tts_chunk, ни tts_end"
    assert synth == []


@pytest.mark.parametrize("via", ["voice_command", "chat_send"])
def test_without_flag_turn_is_spoken_and_closed(server, synth, via):   # noqa: F811
    async def sc(uri):
        c = await connect(uri, MASTER)
        await c.send({"type": via, "text": "найди телефон"})
        reply = await c.wait(kind("reply"))
        end = await c.wait(kind("tts_end"))
        return reply, end
    reply, end = run(sc)
    assert reply["kind"] == "error" and end["type"] == "tts_end"
    assert synth == ["Телефон не на связи"]


# ── S2: action_run ──────────────────────────────────────────────────



@pytest.fixture
def phone_master(monkeypatch):
    """phone — master и по токену (в стенде нет Noise); правило S4 проверяется в test_phone."""
    monkeypatch.setattr(ws_auth, "_MASTER_DEVICES", set(ws_auth._MASTER_DEVICES) | {"phone"})
    monkeypatch.setattr(config, "SECURE_ONLY_MASTERS", set())


async def commands(c, n=1, timeout=2.0):
    out = []
    for _ in range(n):
        out.append(await c.wait(kind("command"), timeout))
    return out


def test_action_run_phone_action_reaches_phone(server, phone_master):   # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        ph = await connect(uri, "phone")
        started = await lap.request({"type": "action_run", "action": "phone.alarm", "arg": "07:30"})
        (cmd,) = await commands(ph)
        quiet_pc = await lap.silent(kind("command"), 0.3)
        return started, cmd, quiet_pc
    started, cmd, quiet_pc = run(sc)
    assert started["type"] == "action_started" and started["action"] == "phone.alarm" and started["id"]
    assert (cmd["action"], cmd["arg"], cmd["id"]) == ("phone.alarm", "07:30", started["id"])
    assert quiet_pc, "активному ПК phone.* не уходит"


def test_action_run_agent_action_goes_to_active_pc_or_device(server):   # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        pc = await connect(uri, MASTER2)
        a = await lap.request({"type": "action_run", "action": "window.minimize"})
        (c1,) = await commands(lap)
        b = await lap.request({"type": "action_run", "action": "window.minimize", "device": MASTER2})
        (c2,) = await commands(pc)
        return a, c1, b, c2
    a, c1, b, c2 = run(sc)
    assert a["type"] == b["type"] == "action_started" and a["id"] and b["id"]
    assert c1["action"] == c2["action"] == "window.minimize" and "confirmed" not in c1


@pytest.mark.parametrize("msg,code", [
    ({}, "bad_request"),
    ({"action": ""}, "bad_request"),
    ({"action": 5}, "bad_request"),
    ({"action": "window.minimize", "arg": 7}, "bad_request"),
    ({"action": "window.minimize", "device": ["pc"]}, "bad_request"),
    ({"action": "phone.notify", "arg": "x" * 2001}, "bad_request"),
    ({"action": "нет.такого"}, "not_found"),
    ({"action": "window.minimize", "device": "pc"}, "not_found"),      # pc не в сети
    ({"action": "window.minimize", "device": "phone"}, "not_found"),   # телефон — не ПК
    ({"action": "phone.find", "device": MASTER2}, "not_found"),        # pc — не телефон
])
def test_action_run_errors(server, phone_master, msg, code):         # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        return await lap.request({"type": "action_run", **msg})
    r = run(sc)
    assert (r["type"], r["code"]) == ("error", code)


def test_action_run_phone_offline_is_reply_not_error(server, phone_master):   # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        started = await lap.request({"type": "action_run", "action": "phone.find"})
        reply = await lap.wait(kind("reply"))
        return started, reply
    started, reply = run(sc)
    assert started["type"] == "action_started" and started["id"] is None
    assert (reply["text"], reply["kind"]) == ("Телефон не на связи", "error")


def test_action_run_not_master(server):                              # noqa: F811
    async def sc(uri):
        g = await connect(uri, GUEST)
        return await g.request({"type": "action_run", "action": "window.minimize"})
    assert run(sc)["code"] == "not_master"


def test_action_run_confirm_action_asks_then_yes_runs_with_confirmed(server):   # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        started = await lap.request({"type": "action_run", "action": "files.delete", "arg": "черновик"})
        ask = await lap.wait(kind("reply"))
        quiet = await lap.silent(kind("command"), 0.3)
        await lap.send({"type": "voice_command", "text": "да", "channel": "text", "speak": False})
        (cmd,) = await commands(lap)
        return started, ask, quiet, cmd
    started, ask, quiet, cmd = run(sc)
    assert started["id"] is None and ask["kind"] == "confirm"
    assert quiet, "без «да» команда не уходит"
    assert cmd["action"] == "files.delete" and cmd["confirmed"] is True and cmd["arg"] == "черновик"


def test_yes_from_phone_runs_on_the_pc_not_on_phone(server, phone_master):   # noqa: F811
    async def sc(uri):
        pc = await connect(uri, MASTER2)
        ph = await connect(uri, "phone")
        await ph.request({"type": "action_run", "action": "files.delete", "arg": "черновик", "device": MASTER2})
        ask = await ph.wait(kind("reply"))
        await ph.send({"type": "voice_command", "text": "да", "channel": "text", "speak": False})
        (cmd,) = await commands(pc)
        phone_got = await ph.silent(kind("command"), 0.3)
        return ask, cmd, phone_got
    ask, cmd, phone_quiet = run(sc)
    assert ask["kind"] == "confirm"
    assert cmd["action"] == "files.delete" and cmd["confirmed"] is True
    assert phone_quiet, "ПК-команда на телефон не уходит"


def test_action_run_power_uses_power_confirm_with_kind_confirm(server):   # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        pc = await connect(uri, MASTER2)
        started = await lap.request({"type": "action_run", "action": "system.shutdown", "device": MASTER2})
        ask = await lap.wait(kind("reply"))
        quiet = await pc.silent(kind("command"), 0.3)
        await lap.send({"type": "voice_command", "text": "да", "channel": "text", "speak": False})
        (cmd,) = await commands(pc)
        return started, ask, quiet, cmd
    started, ask, quiet, cmd = run(sc)
    assert started["type"] == "action_started" and started["id"] is None
    assert (ask["text"], ask["kind"]) == ("Выключить игровой компьютер? Да или нет?", "confirm")
    assert quiet
    assert cmd["action"] == "system.shutdown" and cmd["confirmed"] is True


def test_action_run_power_no_without_confirmation_sends_nothing(server):   # noqa: F811
    async def sc(uri):
        lap = await connect(uri, MASTER)
        pc = await connect(uri, MASTER2)
        await lap.request({"type": "action_run", "action": "power.sleep"})      # активный ПК
        ask = await lap.wait(kind("reply"))
        await lap.send({"type": "voice_command", "text": "нет", "channel": "text", "speak": False})
        quiet = await pc.silent(kind("command"), 0.5) and await lap.silent(kind("command"), 0.2)
        return ask, quiet
    ask, quiet = run(sc)
    assert ask["text"].startswith("Усыпить ") and ask["kind"] == "confirm" and quiet
