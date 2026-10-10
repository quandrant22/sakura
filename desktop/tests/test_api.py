"""Локальный API: токен, Origin, hello, команды, события, файл токена."""
import asyncio
import json

import pytest
import websockets

from desktop.core.api.server import (
    CLOSE_FORBIDDEN_ORIGIN,
    CLOSE_UNAUTHORIZED,
    ApiError,
    LocalApiServer,
)


def run(coro):
    return asyncio.run(coro)


async def _connect(api, token=None, origin="file://", client="ui"):
    headers = {"Origin": origin} if origin else {}
    ws = await websockets.connect(f"ws://127.0.0.1:{api.port}", additional_headers=headers)
    if token is not False:
        await ws.send(json.dumps({"type": "hello", "token": token or api.token, "client": client}))
    return ws


async def _recv(ws, timeout=2.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


def test_wrong_token_closed_4401():
    async def go():
        api = LocalApiServer(token="good")
        await api.start()
        ws = await _connect(api, token="bad")
        with pytest.raises(websockets.ConnectionClosed) as e:
            await _recv(ws)
        assert e.value.rcvd.code == CLOSE_UNAUTHORIZED
        await api.stop()
    run(go())


def test_no_hello_closed_after_timeout(monkeypatch):
    from desktop.core.api import server as srv
    monkeypatch.setattr(srv, "HELLO_TIMEOUT", 0.2)

    async def go():
        api = LocalApiServer(token="good")
        await api.start()
        ws = await _connect(api, token=False)
        with pytest.raises(websockets.ConnectionClosed) as e:
            await _recv(ws)
        assert e.value.rcvd.code == CLOSE_UNAUTHORIZED
        await api.stop()
    run(go())


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost:3000"])
def test_foreign_origin_closed_4403(origin):
    async def go():
        api = LocalApiServer(token="good")
        await api.start()
        ws = await _connect(api, token=False, origin=origin)  # закрывают ещё до hello
        with pytest.raises(websockets.ConnectionClosed) as e:
            await _recv(ws)
        assert e.value.rcvd.code == CLOSE_FORBIDDEN_ORIGIN
        await api.stop()
    run(go())


@pytest.mark.parametrize("origin", ["file://", "http://localhost:5173", None])
def test_allowed_origins_get_snapshot(origin):
    async def go():
        api = LocalApiServer(token="good", snapshot=lambda: [{"type": "state", "value": "idle"}])
        await api.start()
        ws = await _connect(api, origin=origin)
        assert await _recv(ws) == {"type": "state", "value": "idle"}
        await ws.close()
        await api.stop()
    run(go())


def test_listens_on_loopback_only():
    async def go():
        api = LocalApiServer(token="good")
        server = await api.start()
        hosts = {s.getsockname()[0] for s in server.sockets}
        assert hosts == {"127.0.0.1"}
        await api.stop()
    run(go())


def test_command_reply_ok_error_unknown():
    async def go():
        api = LocalApiServer(token="good")

        async def echo(msg):
            return {"echo": msg["text"]}

        async def fail(msg):
            raise ApiError("offline", "нет связи")

        api.command("echo", echo)
        api.command("fail", fail)
        await api.start()
        ws = await _connect(api)
        await ws.send(json.dumps({"type": "echo", "request_id": "a", "text": "hi"}))
        assert await _recv(ws) == {"type": "reply", "request_id": "a", "ok": True, "result": {"echo": "hi"}}
        await ws.send(json.dumps({"type": "fail", "request_id": "b"}))
        r = await _recv(ws)
        assert (r["ok"], r["error"]["code"]) == (False, "offline")
        await ws.send(json.dumps({"type": "nope", "request_id": "c"}))
        r = await _recv(ws)
        assert (r["ok"], r["error"]["code"]) == (False, "unknown_command")
        await ws.close()
        await api.stop()
    run(go())


def test_broadcast_reaches_all_authorized_clients():
    async def go():
        api = LocalApiServer(token="good")
        await api.start()
        a, b = await _connect(api), await _connect(api, client="overlay", origin=None)
        await asyncio.sleep(0.1)
        api.emit_threadsafe({"type": "state", "value": "listening"})
        assert (await _recv(a))["value"] == "listening"
        assert (await _recv(b))["value"] == "listening"
        await a.close()
        await b.close()
        await api.stop()
    run(go())


def test_token_file_written_and_restricted(tmp_path):
    restricted = []

    async def go():
        path = tmp_path / "Sakura" / "ui.token"
        api = LocalApiServer(token="tok", token_path=str(path), restrict=restricted.append)
        await api.start()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"port": api.port, "token": "tok"}
        assert restricted == [str(path)]
        await api.stop()
    run(go())


def test_random_token_by_default():
    assert LocalApiServer().token != LocalApiServer().token
    assert len(LocalApiServer().token) >= 32
