"""Клиент Сакуры против НАСТОЯЩЕГО серверного пакета securechannel/ (оба движка: lib — noiseprotocol, edu).

Спаривание по 8 словам и по QR → сеанс IK → эхо → сообщение 2 МиБ; неизвестный ключ — отказ 4408 в дедлайн.
Движок lib требует noiseprotocol (нет в venv агента) — тогда проверяется только edu.
"""
import asyncio
import json
import os
import time

import pytest
import websockets

from desktop.core.securechannel import noise as N
from desktop.core.securechannel.client import SecureError, ik_handshake, xx_pair
from desktop.core.securechannel.keys import KeyStore
from desktop.core.securechannel.pairing import make_qr_uri, words_to_psk

server_mod = pytest.importorskip("securechannel.server")
from securechannel.keys import ServerKeys  # noqa: E402
from securechannel.pairing import PairingManager  # noqa: E402
from securechannel.registry import DeviceRegistry  # noqa: E402

try:
    import noise  # noqa: F401
    BACKENDS = ["edu", "lib"]
except ImportError:
    BACKENDS = ["edu"]


async def _serve(tmp_path, backend, timeout=0.5):
    keys = ServerKeys.load_or_create(str(tmp_path / "srv"))
    ctx = server_mod.SecureContext(keys=keys, registry=DeviceRegistry(str(tmp_path / "srv" / "devices.json")),
                                   pairing=PairingManager(), backend=backend, timeout=timeout)

    async def handler(ws):
        first = await ws.recv()
        conn = await server_mod.accept(ws, first, ctx)
        if conn is None:
            return
        try:
            async for text in conn:
                msg = json.loads(text)
                await conn.send(json.dumps({"type": "echo", "request_id": msg.get("request_id"), "size": len(text)}))
        except Exception:  # noqa: BLE001
            pass
    srv = await websockets.serve(handler, "127.0.0.1", 0, max_size=None, compression=None)
    return srv, f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}", ctx


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("via", ["words", "qr"])
def test_pair_and_session_against_real_server(tmp_path, backend, via):
    async def go():
        srv, url, ctx = await _serve(tmp_path, backend)
        try:
            words, expires = ctx.pairing.create()
            server_pub = ctx.keys.current[1]
            ks = KeyStore(str(tmp_path / "cli"), protect=lambda b: b, unprotect=lambda b: b)
            priv, _ = ks.device_keypair()
            expected = None
            if via == "qr":
                from desktop.core.securechannel.pairing import parse_qr_uri
                qr = parse_qr_uri(make_qr_uri(url, server_pub, words, expires))
                words, expected = qr["words"], qr["server_pub"]
            async with websockets.connect(url, max_size=None, compression=None) as ws:
                res = await xx_pair(ws, priv, words_to_psk(words), {"name": "PC", "kind": "pc", "device_id_hint": "pc"},
                                    expected_server_pub=expected)
            assert res["server_pub"] == server_pub
            ks.save_server(res["server_pub"], res["device_id"], url)
            async with websockets.connect(url, max_size=None, compression=None) as ws:
                conn = await ik_handshake(ws, priv, server_pub, res["device_id"])
                await conn.send(json.dumps({"type": "register", "request_id": "1"}))
                assert json.loads(await conn.recv())["type"] == "echo"
                big = json.dumps({"type": "blob", "request_id": "2", "d": "x" * (2 * 1024 * 1024 - 200)})
                await conn.send(big)
                assert json.loads(await conn.recv())["size"] == len(big)
                for i in range(30):  # много сообщений подряд — счётчики nonce в обе стороны
                    await conn.send(json.dumps({"type": "ping", "request_id": str(i)}))
                    assert json.loads(await conn.recv())["request_id"] == str(i)
        finally:
            srv.close()
            await srv.wait_closed()
    asyncio.run(go())


@pytest.mark.parametrize("backend", BACKENDS)
def test_unknown_key_rejected_by_real_server_at_deadline(tmp_path, backend):
    async def go():
        srv, url, ctx = await _serve(tmp_path, backend, timeout=0.4)
        try:
            priv, _ = N.generate_keypair()
            t = time.monotonic()
            async with websockets.connect(url) as ws:
                with pytest.raises(SecureError) as e:
                    await ik_handshake(ws, priv, ctx.keys.current[1], "x", timeout=3)
            return e.value.code, time.monotonic() - t
        finally:
            srv.close()
            await srv.wait_closed()
    code, dt = asyncio.run(go())
    assert code == 4408 and dt >= 0.35


@pytest.mark.parametrize("backend", BACKENDS)
def test_wrong_words_rejected_by_real_server(tmp_path, backend):
    async def go():
        srv, url, ctx = await _serve(tmp_path, backend, timeout=0.4)
        try:
            ctx.pairing.create()
            priv, _ = N.generate_keypair()
            async with websockets.connect(url) as ws:
                with pytest.raises(SecureError):
                    await xx_pair(ws, priv, os.urandom(32), {"name": "x"}, timeout=3)
        finally:
            srv.close()
            await srv.wait_closed()
    asyncio.run(go())
