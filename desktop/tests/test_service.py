"""CoreService: события шины → API, команды интерфейса → агент/hands/сервер."""
import asyncio
import json
from types import SimpleNamespace

import pytest
import websockets

from desktop.core.api.server import LocalApiServer
from desktop.core.service import CoreService


class FakeSettings:
    def __init__(self):
        self.data = {}

    def items(self):
        return dict(self.data)

    def set(self, k, v):
        self.data[k] = v


class FakeAgent:
    def __init__(self, bus, server_link=None):
        self.bus, self.server_link = bus, server_link
        self.hearing = SimpleNamespace(mic_enabled=True)
        self.player = SimpleNamespace(interrupted=0)
        self.player.interrupt = lambda: setattr(self.player, "interrupted", self.player.interrupted + 1)
        self.sent, self.states = [], []

    def submit_user_text(self, text, channel=None):
        self.sent.append((text, channel))

    def set_state(self, s):
        self.states.append(s)


def _hands():
    return SimpleNamespace(_app_cache={"Telegram": "x", "Steam": "y"}, scan_apps=lambda: {},
                           take_screenshot=lambda: "QUJD", open_app=lambda n: f"открываю {n}")


def make_service():
    api = LocalApiServer(token="tok")
    return CoreService(agent_factory=FakeAgent, api=api, settings=FakeSettings(), hands=_hands())


def run(coro):
    return asyncio.run(coro)


async def _client(svc):
    ws = await websockets.connect(f"ws://127.0.0.1:{svc.api.port}", additional_headers={"Origin": "file://"})
    await ws.send(json.dumps({"type": "hello", "token": "tok", "client": "ui"}))
    snap = [json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(3)]
    return ws, snap


async def _call(ws, msg):
    await ws.send(json.dumps(msg))
    while True:
        r = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if r.get("type") == "reply" and r.get("request_id") == msg["request_id"]:
            return r


def test_snapshot_on_connect():
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, snap = await _client(svc)
        assert [e["type"] for e in snap] == ["connection", "state", "settings"]
        assert snap[0]["server"] == "offline"
        assert snap[2]["settings"]["quick_prompts"][0] == "Что у меня сегодня?"
        await ws.close()
        await svc.api.stop()
    run(go())


def test_commands():
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, _ = await _client(svc)
        r = await _call(ws, {"type": "send_text", "request_id": "1", "text": " Погода "})
        assert r["ok"] and svc.agent.sent == [("Погода", "text")]
        r = await _call(ws, {"type": "send_text", "request_id": "2", "text": "  "})
        assert r["error"]["code"] == "bad_request"
        r = await _call(ws, {"type": "mic_toggle", "request_id": "3"})
        assert r["result"] == {"mic": False}
        r = await _call(ws, {"type": "stop_speaking", "request_id": "4"})
        assert r["ok"] and svc.agent.player.interrupted == 1 and svc.agent.states == ["idle"]
        r = await _call(ws, {"type": "list_apps", "request_id": "5"})
        assert r["result"]["apps"] == [{"name": "Steam"}, {"name": "Telegram"}]
        r = await _call(ws, {"type": "quick_action", "request_id": "6", "id": "screenshot"})
        assert r["result"] == {"image": "QUJD"}
        r = await _call(ws, {"type": "quick_action", "request_id": "7", "id": "open_app", "arg": "Telegram"})
        assert r["result"] == {"text": "открываю Telegram"}
        r = await _call(ws, {"type": "quick_action", "request_id": "8", "id": "focus_mode"})
        assert r["error"]["code"] == "offline"
        r = await _call(ws, {"type": "settings_set", "request_id": "9",
                             "key": "theme", "value": "sakura-day"})
        assert r["result"]["settings"]["theme"] == "sakura-day"
        r = await _call(ws, {"type": "settings_set", "request_id": "10", "key": "WS_TOKEN", "value": "x"})
        assert r["error"]["code"] == "bad_request"
        r = await _call(ws, {"type": "server", "request_id": "11", "message": {"type": "devices_request"}})
        assert r["error"]["code"] == "offline"
        await ws.close()
        await svc.api.stop()
    run(go())


def test_bus_events_mapped():
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, _ = await _client(svc)
        svc.bus.emit("state", value="listening")
        svc.bus.emit("user_text", text="привет")
        svc.bus.emit("sakura_text", text="и тебе")
        svc.bus.emit("agent_alert", text="внимание")
        got = [json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(5)]
        assert [g["type"] for g in got] == ["state", "transcript", "chat_message", "chat_message", "notify"]
        assert got[2]["message"]["role"] == "user" and got[3]["message"]["role"] == "assistant"
        await ws.close()
        await svc.api.stop()
    run(go())


def test_no_local_chat_when_server_proto2():
    svc = make_service()
    sent = []
    svc._emit = sent.append
    svc.link.proto = 2
    svc.bus.emit("sakura_text", text="x")
    assert sent == []


@pytest.mark.parametrize("bad", [{"message": None}, {"message": {}}])
def test_server_command_validation(bad):
    async def go():
        svc = make_service()
        from desktop.core.api.server import ApiError
        with pytest.raises(ApiError):
            await svc.cmd_server(bad)
    run(go())


def test_deferred_agent_reports_starting():
    async def go():
        svc = CoreService(agent_factory=None, api=LocalApiServer(token="tok"),
                          settings=FakeSettings(), hands=_hands())
        assert svc.settings_snapshot()["core_ready"] is False
        from desktop.core.api.server import ApiError
        with pytest.raises(ApiError) as e:
            await svc.cmd_send_text({"text": "x"})
        assert e.value.code == "starting"
    run(go())
