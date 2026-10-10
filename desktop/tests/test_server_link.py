"""ServerLink: proto 2, корреляция запросов, таймауты, офлайн, сервер v1 — против мок-сервера."""
import asyncio
import json

import pytest
import websockets

from desktop.core.api.server import ApiError
from desktop.core.server_link import ServerLink
from desktop.tools.mock_server import MockServer

TOKEN = "t"


def run(coro):
    return asyncio.run(coro)


class _Conn:
    """Минимальная замена Agent: регистрация + цикл приёма → ServerLink.handle."""

    def __init__(self, link: ServerLink, url: str, device="mostech"):
        self.link, self.url, self.device = link, url, device
        self.pushes: list[dict] = []
        self.other: list[dict] = []

    async def __aenter__(self):
        self.ws = await websockets.connect(self.url)
        await self.ws.send(json.dumps({"type": "register", "device_id": self.device,
                                       "token": TOKEN, "proto": 2}))

        async def send(msg):
            await self.ws.send(json.dumps(msg))
        self.link.on_connected(send)
        self.task = asyncio.ensure_future(self._recv())
        return self

    async def _recv(self):
        try:
            async for raw in self.ws:
                data = json.loads(raw)
                if not self.link.handle(data):
                    self.other.append(data)
        except websockets.ConnectionClosed:
            pass
        self.link.on_disconnected()

    async def __aexit__(self, *exc):
        await self.ws.close()
        await self.task


async def _mock(**kw):
    srv = MockServer(token=TOKEN, step_delay=0, **kw)
    server = await srv.serve("127.0.0.1", 0)
    return srv, server, f"ws://127.0.0.1:{next(iter(server.sockets)).getsockname()[1]}"


def _link(**kw):
    pushes = []
    link = ServerLink(auth=lambda: {"device_id": "mostech", "token": TOKEN},
                      on_push=pushes.append, **kw)
    return link, pushes


def test_registered_sets_proto_and_master():
    async def go():
        srv, server, url = await _mock()
        async with server:
            link, _ = _link()
            async with _Conn(link, url):
                await asyncio.sleep(0.2)
                assert (link.proto, link.master) == (2, True)
    run(go())


def test_request_roundtrip_and_parallel_correlation():
    async def go():
        srv, server, url = await _mock()
        async with server:
            link, _ = _link()
            async with _Conn(link, url):
                await asyncio.sleep(0.1)
                h, d, s = await asyncio.gather(
                    link.request({"type": "history_request", "limit": 2}),
                    link.request({"type": "devices_request"}),
                    link.request({"type": "status_request"}))
                assert h["type"] == "history" and len(h["messages"]) == 2
                assert d["type"] == "devices" and s["type"] == "status"
                sent = [m for m in srv.received if m.get("type") == "devices_request"][0]
                assert sent["token"] == TOKEN and sent["device_id"] == "mostech"
    run(go())


def test_server_error_becomes_api_error():
    async def go():
        srv, server, url = await _mock()
        async with server:
            link, _ = _link()
            async with _Conn(link, url):
                await asyncio.sleep(0.1)
                with pytest.raises(ApiError) as e:
                    await link.request({"type": "scenario_get", "id": "nope"})
                assert e.value.code == "not_found"
    run(go())


def test_timeout_when_server_silent():
    async def go():
        srv, server, url = await _mock(mode="offline")
        async with server:
            link, _ = _link(timeout=0.3)
            async with _Conn(link, url):
                await asyncio.sleep(0.1)
                with pytest.raises(ApiError) as e:
                    await link.request({"type": "devices_request"})
                assert e.value.code == "timeout"
                assert link._pending == {}
    run(go())


def test_offline_without_connection():
    async def go():
        link, _ = _link()
        with pytest.raises(ApiError) as e:
            await link.request({"type": "devices_request"})
        assert e.value.code == "offline"
    run(go())


def test_disconnect_fails_pending_with_offline():
    async def go():
        srv, server, url = await _mock(mode="offline")
        async with server:
            link, _ = _link(timeout=5)
            conn = _Conn(link, url)
            await conn.__aenter__()
            await asyncio.sleep(0.1)
            task = asyncio.ensure_future(link.request({"type": "devices_request"}))
            await asyncio.sleep(0.1)
            await conn.__aexit__()
            with pytest.raises(ApiError) as e:
                await task
            assert e.value.code == "offline"
            assert not link.online
    run(go())


def test_legacy_server_unsupported():
    async def go():
        srv, server, url = await _mock(mode="legacy")
        async with server:
            link, _ = _link()
            async with _Conn(link, url):
                await asyncio.sleep(0.1)
                assert link.proto == 1
                with pytest.raises(ApiError) as e:
                    await link.request({"type": "status_request"})
                assert e.value.code == "unsupported"
    run(go())


def test_v1_server_without_registered_after_grace():
    async def go():
        link, _ = _link(v1_grace=0.05)

        async def send(msg):
            raise AssertionError("v1: запрос не должен уходить на сервер")
        link.on_connected(send)
        await asyncio.sleep(0.1)
        with pytest.raises(ApiError) as e:
            await link.request({"type": "devices_request"})
        assert e.value.code == "unsupported" and link.proto == 1
    run(go())


def test_pushes_forwarded():
    async def go():
        srv, server, url = await _mock()
        async with server:
            link, pushes = _link()
            async with _Conn(link, url) as conn:
                await asyncio.sleep(0.1)
                await conn.ws.send(json.dumps({"type": "voice_command", "text": "привет", "token": TOKEN}))
                await asyncio.sleep(0.3)
                assert [p["type"] for p in pushes] == ["chat_message", "chat_message"]
                assert [o["type"] for o in conn.other] == ["reply"]  # reply остаётся агенту
                run_reply = await link.request({"type": "scenario_run", "id": "focus"})
                assert run_reply["type"] == "scenario_run_started"
                await asyncio.sleep(0.2)
                assert [p["status"] for p in pushes if p["type"] == "scenario_event"] == ["ok", "ok", "done"]
    run(go())


def test_state_events():
    events = []
    link = ServerLink(on_state=events.append)

    async def send(msg):
        pass
    link.on_connected(send)
    link.handle({"type": "registered", "proto": 2, "master": True})
    link.on_disconnected()
    assert [(e["server"], e["proto"]) for e in events] == [("online", None), ("online", 2), ("offline", 2)]
