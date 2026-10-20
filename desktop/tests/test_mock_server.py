"""Мок-сервер протокола v2: регистрация, все запросы, ошибки, режимы legacy/offline."""
import asyncio
import json

import pytest
import websockets

from desktop.tools.mock_server import CLOSE_UNAUTHORIZED, V2_REQUESTS, MockServer

TOKEN = "t"


def run(coro):
    return asyncio.run(coro)


async def _start(**kw):
    srv = MockServer(token=TOKEN, step_delay=0, **kw)
    server = await srv.serve("127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    return srv, server, f"ws://127.0.0.1:{port}"


async def _client(url, device="mostech", token=TOKEN):
    ws = await websockets.connect(url)
    await ws.send(json.dumps({"type": "register", "device_id": device, "token": token, "proto": 2}))
    return ws


async def _recv(ws, timeout=2.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _request(ws, obj):
    obj.setdefault("request_id", "r1")
    await ws.send(json.dumps(obj))
    while True:
        msg = await _recv(ws)
        if msg.get("request_id") == obj["request_id"] and msg["type"] != "scenario_run_started":
            return msg


def test_register_ok_and_master_flag():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            reg = await _recv(ws)
            assert reg == {"type": "registered", "device_id": "mostech", "proto": 2, "master": True}
            await ws.close()
    run(go())


def test_bad_token_closed_4401():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url, token="wrong")
            with pytest.raises(websockets.ConnectionClosed) as e:
                await _recv(ws)
            assert e.value.rcvd.code == CLOSE_UNAUTHORIZED
    run(go())


def test_all_v2_requests_answered():
    payloads = {
        "scenario_get": {"id": "focus"}, "scenario_delete": {"id": "sleep"},
        "scenario_run": {"id": "focus"}, "scenario_from_text": {"text": "Создай сценарий сна"},
        "scenario_save": {"scenario": {"name": "Новый", "conditions": [], "actions": []}},
        "memory_search": {"q": "лоу"}, "memory_update": {"id": "k1", "text": "x"},
        "memory_delete": {"id": "k2"}, "chat_search": {"q": "а"}, "chat_delete": {"id": "m1"},
        "chat_read": {"last_read_id": "m5"}, "chat_clear": {"confirm": True}, "chat_send": {"text": "привет"},
    }
    expected = {
        "history_request": "history", "chat_search": "chat_search", "chat_delete": "chat_delete",
        "chat_read": "chat_read", "chat_clear": "chat_clear", "chat_send": "chat_ack",
        "devices_request": "devices", "status_request": "status", "secure_devices": "secure_devices",
        "scenarios_list": "scenarios", "scenario_get": "scenario", "scenario_save": "scenario",
        "scenario_delete": "scenarios", "scenario_from_text": "scenario_preview",
        "memory_list": "memory_items", "memory_search": "memory_items",
        "memory_update": "memory_items", "memory_delete": "memory_items",
        "profile_get": "profile", "profile_set": "profile",
    }

    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            # chat_clear — последним: он очищает историю, нужную chat_search/chat_delete.
            kinds = sorted(V2_REQUESTS - {"scenario_run", "chat_clear"}) + ["chat_clear"]
            for i, kind in enumerate(kinds):
                reply = await _request(ws, {"type": kind, "request_id": f"q{i}", **payloads.get(kind, {})})
                assert reply["type"] == expected[kind], (kind, reply)
            await ws.close()
    run(go())


def test_scenario_run_streams_events():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            await ws.send(json.dumps({"type": "scenario_run", "request_id": "x", "id": "sleep"}))
            started = await _recv(ws)
            assert started["type"] == "scenario_run_started"
            events = [await _recv(ws) for _ in range(4)]
            assert [e["status"] for e in events] == ["ok", "ok", "ok", "done"]
            assert all(e["run_id"] == started["run_id"] for e in events)
            await ws.close()
    run(go())


def test_history_limit_and_before():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            h = await _request(ws, {"type": "history_request", "limit": 2})
            assert [m["id"] for m in h["messages"]] == ["m4", "m5"]
            h = await _request(ws, {"type": "history_request", "limit": 10, "before_ts": 1760090100.0,
                                    "request_id": "r2"})
            assert [m["id"] for m in h["messages"]] == ["m1", "m2"]
            await ws.close()
    run(go())


def test_voice_command_pushes_chat_messages():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            await ws.send(json.dumps({"type": "voice_command", "text": "привет", "token": TOKEN}))
            kinds = [(await _recv(ws))["type"] for _ in range(3)]
            assert kinds == ["chat_message", "reply", "chat_message"]
            await ws.close()
    run(go())


def test_errors_not_found_and_bad_request():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            e = await _request(ws, {"type": "scenario_get", "id": "nope"})
            assert (e["type"], e["code"]) == ("error", "not_found")
            e = await _request(ws, {"type": "memory_search", "request_id": "r2"})
            assert (e["type"], e["code"]) == ("error", "bad_request")
            await ws.close()
    run(go())


def test_not_master_device_rejected():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url, device="phone")
            reg = await _recv(ws)
            assert reg["master"] is False
            e = await _request(ws, {"type": "devices_request"})
            assert e["code"] == "not_master"
            await ws.close()
    run(go())


def test_legacy_mode_unsupported():
    async def go():
        srv, server, url = await _start(mode="legacy")
        async with server:
            ws = await _client(url)
            assert (await _recv(ws))["proto"] == 1
            e = await _request(ws, {"type": "status_request"})
            assert e["code"] == "unsupported"
            await ws.close()
    run(go())


def test_offline_mode_silent():
    async def go():
        srv, server, url = await _start(mode="offline")
        async with server:
            ws = await _client(url)
            await _recv(ws)
            await ws.send(json.dumps({"type": "devices_request", "request_id": "z"}))
            with pytest.raises(asyncio.TimeoutError):
                await _recv(ws, timeout=0.3)
            await ws.close()
    run(go())


def test_state_is_isolated_between_instances():
    a, b = MockServer(token=TOKEN), MockServer(token=TOKEN)
    a.state["scenarios"]["scenarios"].clear()
    assert b.state["scenarios"]["scenarios"]


def test_unknown_request_type_answered_unknown_type():
    """Запрос с request_id вне V2_REQUESTS сервера — error/unknown_type; ping и прочее без request_id — тишина."""
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            e = await _request(ws, {"type": "history_search", "q": "а"})
            assert (e["type"], e["code"]) == ("error", "unknown_type")
            await ws.send(json.dumps({"type": "ping", "device_id": "mostech"}))
            with pytest.raises(asyncio.TimeoutError):
                await _recv(ws, timeout=0.3)
            await ws.close()
    run(go())


def test_dangerous_scenario_needs_confirm():
    async def go():
        srv, server, url = await _start()
        srv.state["scenarios"]["scenarios"].append(
            {"id": "off", "name": "Выключить", "enabled": True, "conditions": [],
             "actions": [{"type": "system.shutdown", "value": ""}]})
        async with server:
            ws = await _client(url)
            await _recv(ws)
            e = await _request(ws, {"type": "scenario_run", "id": "off"})
            assert (e["type"], e["code"]) == ("error", "confirm_required")
            assert "system.shutdown" in e["message"]
            await ws.send(json.dumps({"type": "scenario_run", "request_id": "r2", "id": "off", "confirm": True}))
            assert (await _recv(ws))["type"] == "scenario_run_started"
            await ws.close()
    run(go())


def test_secure_devices_bye_and_presence():
    async def go():
        srv, server, url = await _start()
        async with server:
            ws = await _client(url)
            await _recv(ws)
            pc = await _client(url, device="pc")
            await _recv(pc)
            r = await _request(ws, {"type": "secure_devices"})
            cur = {d["device_id"]: d["current"] for d in r["devices"]}
            assert cur["mostech"] is True and cur["pc"] is False
            assert all("pub" not in d and len(d["fingerprint"]) == 16 for d in r["devices"])
            await pc.send(json.dumps({"type": "bye", "device_id": "pc", "reason": "sleep"}))
            await asyncio.sleep(0.05)
            assert srv.bye == {"pc": "sleep"}
            await srv.presence("pc", "mostech")
            assert await _recv(ws) == {"type": "presence", "event": "arrival", "from": "pc", "to": "mostech"}
            assert (await _recv(pc))["event"] == "departure"
            await pc.close()
            await ws.close()
    run(go())
