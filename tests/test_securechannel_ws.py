"""securechannel в adapters/ws.ws_handler: режимы SECURE_CHANNEL, Noise без
токена, device_id из реестра, приватные классы только на secure.

Run: python -m pytest tests/test_securechannel_ws.py -q
"""

import asyncio
import json

import pytest
import websockets

import adapters.ws as wh
import config
import modules.state as st
import sakura_core.ws_protocol as proto
from modules import device_manager, presence_sync, rituals
from modules.ws_auth import _WS_SECRET, MAX_WS_MESSAGE_SIZE
from sakura_core import secure_policy
from securechannel.client import connect_session, pair
from securechannel.handshake import generate_keypair

pytest.importorskip("noise")


@pytest.fixture
def env(monkeypatch):
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(st, "device_proto", {})
    monkeypatch.setattr(device_manager, "set_device_offline", lambda d: None)
    monkeypatch.setattr(presence_sync, "set_offline", lambda d: None)
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    monkeypatch.setattr(config, "SECURE_CHANNEL", "optional")
    monkeypatch.setattr(config, "PROTO_V2", True)
    yield monkeypatch
    st.connected_devices.clear()
    st.connected_devices.update(saved)


def run(scenario):
    async def _go():
        async with websockets.serve(wh.ws_handler, "127.0.0.1", 0, max_size=MAX_WS_MESSAGE_SIZE,
                                    ping_interval=None) as srv:
            uri = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
            return await asyncio.wait_for(scenario(uri), 20)
    return asyncio.run(_go())


async def paired_device(uri, hint="laptop"):
    ctx = secure_policy.context()
    words, _ = ctx.pairing.create()
    priv = generate_keypair()[0]
    async with websockets.connect(uri, max_size=None) as ws:
        info = await pair(ws, words, priv, expected_server_pub=ctx.keys.current[1],
                          device_id_hint=hint)
    return priv, info


async def until(conn, pred, timeout=3.0):
    while True:
        m = json.loads(await asyncio.wait_for(conn.recv(), timeout))
        if pred(m):
            return m


async def closed_code(ws):
    try:
        while True:
            await asyncio.wait_for(ws.recv(), 3)
    except websockets.ConnectionClosed as e:
        return e.rcvd.code if e.rcvd else None


def test_noise_session_without_token_and_device_id_from_registry(env):
    async def sc(uri):
        priv, info = await paired_device(uri, hint="laptop")
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id="laptop")
            # без token и с чужим device_id — сервер берёт id из реестра
            await c.send(json.dumps({"type": "register", "device_id": "pc", "proto": 2}))
            reg = await until(c, lambda m: m.get("type") == "registered")
            await c.send(json.dumps({"type": "status_request", "request_id": "s1"}))
            st_ = await until(c, lambda m: m.get("request_id") == "s1")
            online = sorted(st.connected_devices)
        return reg, st_, online
    reg, st_, online = run(sc)
    assert reg["device_id"] == "laptop" and reg["master"] is True
    assert st_["type"] == "status"
    assert online == ["laptop"]


def test_legacy_token_still_works_in_optional(env):
    async def sc(uri):
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "register", "device_id": "laptop",
                                      "token": _WS_SECRET, "proto": 2}))
            return json.loads(await asyncio.wait_for(ws.recv(), 3))
    assert run(sc)["type"] == "registered"


def test_required_rejects_legacy_with_4412(env):
    env.setattr(config, "SECURE_CHANNEL", "required")

    async def sc(uri):
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "register", "device_id": "laptop",
                                      "token": _WS_SECRET}))
            return await closed_code(ws)
    assert run(sc) == 4412


def test_required_accepts_noise(env):
    env.setattr(config, "SECURE_CHANNEL", "required")

    async def sc(uri):
        priv, info = await paired_device(uri)
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id="laptop")
            await c.send(json.dumps({"type": "register", "proto": 2}))
            return await until(c, lambda m: m.get("type") == "registered")
    assert run(sc)["proto"] == 2


def test_off_rejects_noise_with_4400(env):
    env.setattr(config, "SECURE_CHANNEL", "off")

    async def sc(uri):
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(b"SK\x01\x01\x00\x00\x00\x00")
            return await closed_code(ws)
    assert run(sc) == 4400


def test_wrong_token_on_legacy_still_4401(env):
    async def sc(uri):
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "register", "device_id": "laptop", "token": "нет"}))
            return await closed_code(ws)
    assert run(sc) == 4401


def test_private_classes_need_secure(env):
    """Не-secure (не Noise и не локальный источник): приватное — ошибка,
    обычное — работает. На Noise то же приватное проходит до обработчика."""
    env.setattr(secure_policy, "is_local_peer", lambda ip: False)

    async def sc(uri):
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "register", "device_id": "laptop",
                                      "token": _WS_SECRET, "proto": 2}))
            await ws.recv()
            out = {}
            for t in ("history_request", "memory_list", "profile_get", "vision_request",
                      "computer_step", "chat_send"):
                await ws.send(json.dumps({"type": t, "request_id": t, "device_id": "laptop",
                                          "token": _WS_SECRET}))
                out[t] = await until(ws, lambda m, t=t: m.get("request_id") == t)
            await ws.send(json.dumps({"type": "status_request", "request_id": "s",
                                      "device_id": "laptop", "token": _WS_SECRET}))
            out["status"] = await until(ws, lambda m: m.get("request_id") == "s")
        priv, info = await paired_device(uri)
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id="laptop")
            await c.send(json.dumps({"type": "register", "proto": 2}))
            await until(c, lambda m: m.get("type") == "registered")
            await c.send(json.dumps({"type": "history_request", "request_id": "h"}))
            out["noise_history"] = await until(c, lambda m: m.get("request_id") == "h")
        return out
    out = run(sc)
    for t in ("history_request", "memory_list", "profile_get", "vision_request",
              "computer_step", "chat_send"):
        assert out[t]["code"] == "secure_channel_required" and out[t]["hint"], t
        assert out[t]["request_id"] == t
    assert out["status"]["type"] == "status"
    assert out["noise_history"].get("code") != "secure_channel_required"


def test_loopback_counts_as_secure(env):
    async def sc(uri):
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "register", "device_id": "laptop",
                                      "token": _WS_SECRET, "proto": 2}))
            await ws.recv()
            await ws.send(json.dumps({"type": "history_request", "request_id": "h",
                                      "device_id": "laptop", "token": _WS_SECRET}))
            return await until(ws, lambda m: m.get("request_id") == "h")
    r = run(sc)
    assert r.get("code") != "secure_channel_required"


def test_policy_helpers(env):
    assert secure_policy.is_private("chat_send") and secure_policy.is_private("vision_request")
    assert not secure_policy.is_private("status_request") and not secure_policy.is_private(None)
    assert secure_policy.is_local_peer("127.0.0.1") and secure_policy.is_local_peer("::1")
    assert secure_policy.is_local_peer("::ffff:127.0.0.1")
    assert not secure_policy.is_local_peer("8.8.8.8") and not secure_policy.is_local_peer("мусор")
    assert not secure_policy.is_local_peer(None)
    env.setattr(config, "SECURE_CHANNEL", "что-то")
    assert secure_policy.mode() == "off"
    class W:
        remote_address = ("10.0.0.5", 1)
    assert secure_policy.peer_ip(W()) == "10.0.0.5" and secure_policy.peer_ip(object()) is None
