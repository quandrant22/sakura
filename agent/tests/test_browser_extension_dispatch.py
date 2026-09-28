import asyncio
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import browser


def test_youtube_player_command_uses_agent_loop(monkeypatch):
    agent_loop = object()
    calls = {}
    response = {"ok": True, "result": "played"}

    async def send_command(action):
        calls["action"] = action
        return response

    class CompletedFuture:
        def __init__(self, result):
            self._result = result

        def result(self, timeout=None):
            calls["timeout"] = timeout
            return self._result

        def cancel(self):
            calls["cancelled"] = True

    def run_coroutine_threadsafe(coroutine, loop):
        calls["loop"] = loop
        return CompletedFuture(asyncio.run(coroutine))

    extension_server = SimpleNamespace(
        is_connected=lambda: True,
        _agent_loop=agent_loop,
        send_command=send_command,
    )
    monkeypatch.setitem(sys.modules, "core.extension_server", extension_server)
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", run_coroutine_threadsafe)

    result = browser.youtube_player_cmd("youtube_volume_up")

    assert result == "youtube: youtube_volume_up"
    assert calls["action"] == "youtube_volume_up"
    assert calls["loop"] is agent_loop