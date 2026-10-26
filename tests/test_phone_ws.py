"""Телефон через настоящий ws_handler: speak:false, action_run, devices.

Run: python -m pytest tests/test_phone_ws.py -q
"""

import json

import pytest

import modules.tts_server as tts
from tests.test_proto_devices import (
    MASTER,
    connect,
    kind,
    run,
    server,  # noqa: F401  (фикстура стенда)
)


@pytest.fixture
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
