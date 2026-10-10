import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

from desktop.core import agent as agent_module


def test_voice_send_logs_wake_to_websocket_completion(monkeypatch, caplog):
    future = Future()
    outbox = SimpleNamespace(
        put=lambda _message: True,
        flush=lambda _ws: asyncio.sleep(0),
    )
    agent = agent_module.Agent.__new__(agent_module.Agent)
    agent._outbox = outbox
    agent._ws = object()
    agent._loop = SimpleNamespace(is_running=lambda: True)
    monkeypatch.setattr(agent_module.asyncio, "run_coroutine_threadsafe",
                        lambda coro, _loop: (coro.close(), future)[1])
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 12.5)

    with caplog.at_level("INFO", logger="sakura.agent"):
        agent.send_threadsafe({"type": "voice_command"}, wake_detected_at=10.0)
        future.set_result(None)

    assert "[timeline] wake_to_send_ms=2500.0 status=sent" in caplog.text


def test_voice_send_logs_vad_speech_end_and_recording_durations(monkeypatch, caplog):
    future = Future()
    outbox = SimpleNamespace(
        put=lambda _message: True,
        flush=lambda _ws: asyncio.sleep(0),
    )
    agent = agent_module.Agent.__new__(agent_module.Agent)
    agent._outbox = outbox
    agent._ws = object()
    agent._loop = SimpleNamespace(is_running=lambda: True)
    monkeypatch.setattr(agent_module.asyncio, "run_coroutine_threadsafe",
                        lambda coro, _loop: (coro.close(), future)[1])
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: 12.5)
    timeline = {
        "id": 7,
        "wake": 1.0,
        "vad_start": 1.1,
        "speech_end": 1.5,
        "recording_end": 2.5,
        "stt_ready": 2.7,
    }

    with caplog.at_level("INFO", logger="sakura.agent"):
        agent.send_threadsafe({"type": "voice_command"}, timeline=timeline)
        future.set_result(None)

    assert "id=7" in caplog.text
    assert "speech_end_to_recording_end_ms=1000.0" in caplog.text
    assert "recording_end_to_stt_ready_ms=200.0" in caplog.text
    assert "speech_end_to_sent_ms=11000.0" in caplog.text