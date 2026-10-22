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
        self.hearing = SimpleNamespace(mic_enabled=True, followups=0)
        self.hearing.open_followup = lambda: setattr(self.hearing, "followups", self.hearing.followups + 1)
        self.player = SimpleNamespace(interrupted=0)
        self.player.interrupt = lambda: setattr(self.player, "interrupted", self.player.interrupted + 1)
        self.sent, self.states, self.sources = [], [], []

    def submit_user_text(self, text, channel=None, source="mic"):
        self.sent.append((text, channel))
        self.sources.append(source)

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
    snap = [json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(4)]
    return ws, snap


async def _call(ws, msg):
    await ws.send(json.dumps(msg))
    while True:
        r = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if r.get("type") == "reply" and r.get("request_id") == msg["request_id"]:
            return r


def test_listen_now():
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, _ = await _client(svc)
        r = await _call(ws, {"type": "listen_now", "request_id": "1"})
        assert r["ok"] and svc.agent.hearing.followups == 1
        assert svc.agent.player.interrupted == 1 and svc.agent.states == ["listening"]
        svc.agent.hearing.mic_enabled = False
        r = await _call(ws, {"type": "listen_now", "request_id": "2"})
        assert r["error"]["code"] == "mic_off" and svc.agent.hearing.followups == 1
        await ws.close()
        await svc.api.stop()
    run(go())


def test_snapshot_on_connect():
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, snap = await _client(svc)
        assert [e["type"] for e in snap] == ["connection", "state", "settings", "media_settings"]
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
        r = await _call(ws, {"type": "game_mode", "request_id": "12", "on": True})
        assert r["result"] == {"on": True}
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
        raw = [json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(6)]
        # listening приглушает встроенные плееры — audio_duck проверяется в test_media_*.
        assert [g["type"] for g in raw].count("audio_duck") == 1
        got = [g for g in raw if g["type"] != "audio_duck"]
        assert [g["type"] for g in got] == ["state", "transcript", "chat_message", "chat_message", "notify"]
        assert got[2]["message"]["role"] == "user" and got[3]["message"]["role"] == "assistant"
        await ws.close()
        await svc.api.stop()
    run(go())


def test_message_source_marked():
    # Источник сообщения виден в чате: голос — mic, окно — ui, проверка — e2e, прочее — api.
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, _ = await _client(svc)
        for i, src in enumerate(["ui", "e2e", None, "hacker"]):
            msg = {"type": "send_text", "request_id": f"s{i}", "text": "привет"}
            if src:
                msg["source"] = src
            assert (await _call(ws, msg))["ok"]
        await ws.close()
        await svc.api.stop()
        return svc.agent.sources
    assert run(go()) == ["ui", "e2e", "api", "api"]

    svc = make_service()
    sent = []
    svc._emit = sent.append
    svc.bus.emit("user_text", text="Сакура, как дела?")          # голос — без source
    svc.bus.emit("user_text", text="Погода", source="ui")
    svc.bus.emit("sakura_text", text="Хорошо")
    chat = [e["message"] for e in sent if e["type"] == "chat_message"]
    assert [(m["role"], m["source"], m["channel"]) for m in chat] == [
        ("user", "mic", "voice"), ("user", "ui", "text"), ("assistant", "server", "text")]


def test_chat_turns_from_bus_and_v2_no_duplicates():
    # п. 1: реплики Сакуры, строки команд и ходы; при сервере v2 его реплики не дублируются.
    svc = make_service()
    sent = []
    svc._emit = sent.append
    svc.bus.emit("user_text", text="сделай потише на двадцать")
    svc.bus.emit("sakura_text", text="Сделано.", kind="ack")
    svc.bus.emit("command_result", detail="громкость 50%", status="done")
    chat = [e["message"] for e in sent if e["type"] == "chat_message"]
    assert [(m["role"], m.get("kind"), m["turn_id"]) for m in chat] == [
        ("user", None, "t1"), ("assistant", "ack", "t1"), ("system", "command", "t1")]

    sent.clear()
    svc.link.proto = 2
    svc.bus.emit("user_text", text="привет")
    svc.bus.emit("sakura_text", text="Привет!")
    svc.bus.emit("command_result", detail="Нет активного плеера", status="noop")
    chat = [e["message"] for e in sent if e["type"] == "chat_message"]
    assert [(m["role"], m["kind"], m["text"]) for m in chat] == [
        ("system", "error", "Не получилось: Нет активного плеера")]


def test_window_ask_only_with_frame_and_server_v2():
    async def go():
        svc = make_service()
        await svc.api.start()
        ws, _ = await _client(svc)
        r1 = await _call(ws, {"type": "window_ask", "request_id": "1"})
        r2 = await _call(ws, {"type": "window_ask", "request_id": "2", "image": "QUJD"})
        r3 = await _call(ws, {"type": "window_ask", "request_id": "3", "image": "x" * 2_000_001})
        await ws.close()
        await svc.api.stop()
        return r1, r2, r3
    r1, r2, r3 = run(go())
    assert r1["error"]["code"] == "bad_request"          # без кадра
    assert r2["error"]["code"] in ("unsupported", "offline")  # сервер v1 / нет связи — честно
    assert r3["error"]["code"] == "bad_request"          # слишком большой кадр


def test_power_pending_warning_and_cancel(monkeypatch):
    # Выключение: тост с отсчётом и предупреждение в чате; «Отмена» — shutdown /a (подставной исполнитель).
    from desktop.core import platform as plat
    calls = []
    monkeypatch.setattr(plat, "get_platform", lambda: type("P", (), {"power": staticmethod(calls.append)})())
    svc = make_service()
    sent = []
    svc._emit = sent.append
    svc.bus.emit("power_pending", action="shutdown", seconds=30)
    assert {"type": "power_pending", "action": "shutdown", "seconds": 30} in sent
    chat = [e["message"] for e in sent if e["type"] == "chat_message"]
    assert "через 30 секунд" in chat[-1]["text"] and "отмени" in chat[-1]["text"]
    r = run(svc.cmd_power_cancel({}))
    assert r == {"ok": True} and calls == ["shutdown_cancel"]
    assert {"type": "power_cancelled"} in sent


def test_repeated_state_not_resent():
    # Агент повторяет speaking на каждый аудио-чанк — в интерфейс уходит только смена состояния.
    svc = make_service()
    sent = []
    svc._emit = sent.append
    for v in ["thinking", "speaking", "speaking", "speaking", "idle", "idle"]:
        svc.bus.emit("state", value=v)
    assert [e["value"] for e in sent if e["type"] == "state"] == ["thinking", "speaking", "idle"]


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
