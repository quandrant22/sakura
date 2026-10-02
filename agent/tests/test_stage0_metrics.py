import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

from core import agent as agent_module
from ui import overlay as overlay_module


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


def test_hud_paint_cpu_is_aggregated_and_logged(monkeypatch, caplog):
    monkeypatch.setattr(overlay_module, "_paint_cpu_window_start", 0.0)
    monkeypatch.setattr(overlay_module, "_paint_cpu_seconds", 0.0)
    monkeypatch.setattr(overlay_module, "_paint_cpu_events", 0)
    monkeypatch.setattr(overlay_module, "_paint_cpu_max", 0.0)
    monkeypatch.setattr(overlay_module.time, "monotonic", lambda: 60.0)

    with caplog.at_level("INFO", logger="sakura.overlay"):
        overlay_module._record_hud_paint_cpu(0.03)

    assert "[overlay-cpu]" in caplog.text
    assert "hud_paint_cpu_s=0.030" in caplog.text
    assert "paints=1" in caplog.text