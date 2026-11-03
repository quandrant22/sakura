"""tests/test_transport.py — core/transport.py против настоящего сервера
securechannel.server.accept на 127.0.0.1.

Главное: если у устройства есть ключи, а рукопожатие Noise не прошло,
агент НИКОГДА не отправляет старый JSON с token (защита от понижения).
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import websockets
from core import transport

transport._ensure_securechannel_path()
pytest.importorskip("noise")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_secure_store import FakeSecureStore, b64
from noise_test_server import TOKEN, Server, recv_json, run

from securechannel.handshake import generate_keypair
from securechannel.keys import b64url

# ── транспорт ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["off", "prefer", "required"])
def test_session_with_keys_is_noise_without_token(tmp_path, mode):
    async def sc():
        async with Server(tmp_path) as srv:
            store = srv.pair()
            conn = await transport.open_connection(srv.url, mode, token=TOKEN, store=store)
            assert (conn.secure, conn.transport) == (True, "noise")
            await conn.send_json({"type": "register", "device_id": "laptop", "token": TOKEN})
            echo = await recv_json(conn)
            await conn.close()
            return srv, echo
    srv, echo = run(sc)
    assert srv.first_kinds == ["binary"] and srv.texts == []
    assert srv.received == [{"type": "register", "device_id": "laptop"}]   # token вырезан
    assert echo["msg"]["type"] == "register"


def test_prefer_without_keys_uses_token(tmp_path):
    async def sc():
        async with Server(tmp_path) as srv:
            conn = await transport.open_connection(srv.url, "prefer", token=TOKEN,
                                                   store=FakeSecureStore())
            assert (conn.secure, conn.transport) == (False, "ws")
            await conn.send_json({"type": "register", "device_id": "laptop"})
            await recv_json(conn)
            await conn.send_json({"type": "ping", "device_id": "laptop"})
            await recv_json(conn)
            await conn.close()
            return srv
    srv = run(sc)
    assert srv.first_kinds == ["text"]
    assert [m["token"] for m in srv.texts] == [TOKEN, TOKEN]


def test_required_without_keys_does_not_connect(tmp_path):
    async def sc():
        async with Server(tmp_path) as srv:
            with pytest.raises(transport.NotPaired):
                await transport.open_connection(srv.url, "required", token=TOKEN,
                                                store=FakeSecureStore())
            await asyncio.sleep(0.05)
            return srv
    assert run(sc).first_kinds == []


@pytest.mark.parametrize("mode", ["off", "prefer", "required"])
def test_keys_and_broken_ik_never_fall_back_to_token(tmp_path, mode):
    """ГЛАВНЫЙ: ключи есть, сервер рвёт IK (ключ не в реестре → молчание,
    4408) — ошибка SecureHandshakeFailed, ни одного текстового JSON с token."""
    async def sc():
        async with Server(tmp_path) as srv:
            store = srv.stranger()
            with pytest.raises(transport.SecureHandshakeFailed) as ei:
                await transport.open_connection(srv.url, mode, token=TOKEN, store=store)
            await asyncio.sleep(0.05)
            return srv, ei.value, store
    srv, err, store = run(sc)
    assert err.code == transport.CLOSE_HANDSHAKE
    assert srv.first_kinds == ["binary"]        # только кадр Noise
    assert srv.texts == [] and srv.sessions == 0
    assert store.keys is not None and "wipe" not in store.calls


def test_keys_and_server_without_noise_never_fall_back(tmp_path):
    """Сервер не понимает Noise (SECURE_CHANNEL=off: бинарное → 4400)."""
    async def handler(ws):
        seen.append(await ws.recv())
        await ws.close(4400, "secure channel disabled")

    seen = []

    async def sc():
        async with websockets.serve(handler, "127.0.0.1", 0) as s:
            url = f"ws://127.0.0.1:{s.sockets[0].getsockname()[1]}"
            priv, pub = generate_keypair()
            store = FakeSecureStore.paired("laptop", priv, pub, generate_keypair()[1])
            with pytest.raises(transport.SecureHandshakeFailed) as ei:
                await transport.open_connection(url, "prefer", token=TOKEN, store=store)
            return ei.value
    err = run(sc)
    assert err.code == 4400
    assert len(seen) == 1 and isinstance(seen[0], bytes) and seen[0][:2] == b"SK"


def test_rotation_tries_next_server_pub_and_promotes(tmp_path):
    async def sc():
        async with Server(tmp_path) as srv:
            store = srv.pair()                       # server_pub = старый ключ
            new_pub = srv.ctx.keys.rotate(grace_seconds=-1)   # старый уже не принимается
            store.keys.next_server_pub = b64url(new_pub)
            conn = await transport.open_connection(srv.url, "prefer", token=TOKEN, store=store)
            await conn.send_json({"type": "register"})
            await recv_json(conn)
            await conn.close()
            return srv, store, new_pub
    srv, store, new_pub = run(sc)
    assert srv.first_kinds == ["binary", "binary"] and srv.texts == []
    assert "promote_next" in store.calls
    assert store.keys.server_pub == b64(new_pub) and store.keys.next_server_pub is None


def test_secure_server_key_saved_only_from_noise(tmp_path):
    async def sc():
        async with Server(tmp_path) as srv:
            store = srv.pair()
            new_pub = srv.ctx.keys.rotate()          # старый ещё принимается
            conn = await transport.open_connection(srv.url, "prefer", store=store)
            announce = await recv_json(conn)         # сервер сообщает новый ключ
            assert conn.accept_server_key(announce) is True
            await conn.close()
            return store, announce, new_pub
    store, announce, new_pub = run(sc)
    assert announce["type"] == "secure_server_key"
    assert store.keys.next_server_pub == announce["pub"] == b64url(new_pub)
    assert "promote_next" not in store.calls        # используется со следующего раза

    # по открытому ws тот же ключ не принимается
    plain = FakeSecureStore.paired("laptop", b"\x01" * 32, b"\x02" * 32, b"\x03" * 32)
    ws_conn = transport.Conn(SimpleNamespace(), transport="ws", token=TOKEN, store=plain)
    assert ws_conn.accept_server_key(announce) is False
    assert plain.keys.next_server_pub is None


def test_message_300kb_both_ways(tmp_path):
    blob = "сакура" * 50_000                         # ~600 КБ UTF-8, > 64 КиБ кадра

    async def sc():
        async with Server(tmp_path) as srv:
            conn = await transport.open_connection(srv.url, "prefer", store=srv.pair())
            await conn.send_json({"type": "screen_context", "screenshot": blob[:150_000]})
            echo = await recv_json(conn)
            await conn.close()
            return echo
    echo = run(sc)
    assert len(echo["msg"]["screenshot"].encode()) >= 300_000
    assert echo["msg"]["screenshot"] == blob[:150_000]


def test_message_over_2mib_not_sent_connection_alive(tmp_path, caplog):
    async def sc():
        async with Server(tmp_path) as srv:
            conn = await transport.open_connection(srv.url, "prefer", store=srv.pair())
            with pytest.raises(transport.MessageTooLarge):
                await conn.send_json({"type": "screen_context", "screenshot": "x" * 2_200_000})
            await conn.send_json({"type": "ping"})
            echo = await recv_json(conn)
            await conn.close()
            return srv, echo
    srv, echo = run(sc)
    assert echo["msg"] == {"type": "ping"}
    assert [m["type"] for m in srv.received] == ["ping"]
    assert "4413" in caplog.text


def test_close_code_4412_seen_by_conn(tmp_path):
    async def sc():
        async with Server(tmp_path, legacy_close=4412) as srv:
            conn = await transport.open_connection(srv.url, "prefer", token=TOKEN,
                                                   store=FakeSecureStore())
            await conn.send_json({"type": "register"})
            async for _ in conn:
                pass
            return conn.close_code
    assert run(sc) == 4412


def test_log_has_no_keys(tmp_path, caplog):
    async def sc():
        async with Server(tmp_path) as srv:
            store = srv.pair()
            conn = await transport.open_connection(srv.url, "prefer", store=store)
            await conn.close()
            bad = srv.stranger()
            with pytest.raises(transport.SecureHandshakeFailed):
                await transport.open_connection(srv.url, "prefer", store=bad)
            return store, bad
    with caplog.at_level("INFO", logger="sakura.agent"):
        store, bad = run(sc)
    for k in (store.keys, bad.keys):
        for secret in (k.priv, k.pub, k.server_pub):
            assert secret not in caplog.text
    assert store.keys.server_fp in caplog.text
