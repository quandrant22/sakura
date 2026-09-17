import asyncio
from concurrent.futures import Future
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def load_outbox():
    spec = importlib.util.spec_from_file_location(
        "outbox_under_test", Path(__file__).resolve().parents[1] / "core/outbox.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_limit_ttl_and_order(monkeypatch, caplog):
    module = load_outbox()
    clock = Mock(return_value=10.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=clock))
    queue = module.Outbox()
    for i in range(12):
        queue.put({"type": "voice_command", "text": str(i)})
    ws = SimpleNamespace(send=AsyncMock())
    asyncio.run(queue.flush(ws))
    assert [json.loads(c.args[0])["text"] for c in ws.send.call_args_list] == list(map(str, range(2, 12)))
    assert "queue full" in caplog.text
    queue.put({"type": "expired"})
    clock.return_value = 40.0
    asyncio.run(queue.flush(ws))
    assert ws.send.await_count == 10
    assert "type=expired: older than 30s" in caplog.text


def test_send_failure_retains_original_message_and_future_logs(caplog):
    module = load_outbox()
    queue = module.Outbox()
    message = {"type": "voice_command", "text": "original"}
    queue.put(message)
    message["text"] = "changed"
    ws = SimpleNamespace(send=AsyncMock(side_effect=OSError("disconnect")))
    with pytest.raises(OSError):
        asyncio.run(queue.flush(ws))
    ws.send = AsyncMock()
    asyncio.run(queue.flush(ws))
    assert json.loads(ws.send.call_args.args[0])["text"] == "original"
    future = Future()
    future.set_exception(OSError("disconnect"))
    module.log_send_result(future, "voice_command")
    assert "send failed type=voice_command" in caplog.text
    assert caplog.records[-1].exc_info


def test_concurrent_flush_does_not_duplicate():
    module = load_outbox()

    async def scenario():
        queue = module.Outbox()
        queue.put({"type": "one"})
        queue.put({"type": "two"})
        sent = []

        async def send(wire):
            await asyncio.sleep(0)
            sent.append(json.loads(wire)["type"])

        ws = SimpleNamespace(send=send)
        await asyncio.gather(queue.flush(ws), queue.flush(ws))
        assert sent == ["one", "two"]

    asyncio.run(scenario())
