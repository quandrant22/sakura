"""securechannel: сервер — спаривание, сеанс, отказы неотличимы по ответу и
времени, отзыв, ротация ключа, лимиты, хранение секретов (600).

Настоящий websockets-сервер; таймаут рукопожатия сжат до 0.6 с.
Run: python -m pytest tests/test_securechannel_server.py -q
"""

import asyncio
import json
import os
import stat
import time

import pytest
import websockets

from securechannel.client import connect_session, pair
from securechannel.frames import FrameType, InnerType, MAX_CHUNK, encode_frame
from securechannel.handshake import Handshake, HandshakeError, generate_keypair
from securechannel.keys import ServerKeys, fingerprint
from securechannel.limits import HandshakeLimiter
from securechannel.pairing import (
    PairingManager,
    make_qr_uri,
    normalize_words,
    parse_qr_uri,
    words_to_psk,
)
from securechannel.registry import DeviceRegistry
from securechannel.server import SecureContext, accept

pytest.importorskip("noise")
TIMEOUT = 0.6


@pytest.fixture
def ctx(tmp_path):
    d = str(tmp_path / "secure")
    return SecureContext(ServerKeys.load_or_create(d), DeviceRegistry.open(d), PairingManager(),
                         limiter=HandshakeLimiter(), timeout=TIMEOUT)


def serve(ctx, scenario, echo=True):
    async def handler(ws):
        try:
            first = await ws.recv()
        except Exception:
            return
        conn = await accept(ws, first, ctx)
        if conn is None:
            return
        async for m in conn:
            if echo:
                await conn.send(json.dumps({"echo": json.loads(m), "dev": conn.device_id}))

    async def _go():
        async with websockets.serve(handler, "127.0.0.1", 0, max_size=None) as srv:
            uri = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
            return await asyncio.wait_for(scenario(uri), 20)
    return asyncio.run(_go())


async def do_pair(uri, ctx, words=None, priv=None, **kw):
    words = words or ctx.pairing.create()[0]
    priv = priv or generate_keypair()[0]
    async with websockets.connect(uri, max_size=None) as ws:
        info = await pair(ws, words, priv, **kw)
    return priv, info


async def closed_with(ws, timeout=3.0):
    """Ждать закрытия: (код, сколько ждали, получено ли что-то)."""
    t = time.monotonic()
    got = []
    try:
        while True:
            got.append(await asyncio.wait_for(ws.recv(), timeout))
    except websockets.ConnectionClosed as e:
        return (e.rcvd.code if e.rcvd else None), time.monotonic() - t, got


# ── спаривание ────────────────────────────────────────────────────

def test_pair_with_qr_then_session(ctx):
    async def sc(uri):
        words, exp = ctx.pairing.create()
        qr = parse_qr_uri(make_qr_uri("ws://host:8765", ctx.keys.current[1], words, exp))
        assert qr["words"] == normalize_words(words) and qr["server_pub"] == ctx.keys.current[1]
        priv, info = await do_pair(uri, ctx, words=qr["words"], expected_server_pub=qr["server_pub"],
                                   name="Ноутбук", kind="pc", device_id_hint="mostech")
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id=info["device_id"])
            await c.send(json.dumps({"type": "register", "big": "я" * (MAX_CHUNK + 10)}))
            r = json.loads(await c.recv())
        return info, r, c.session
    info, r, session = serve(ctx, sc)
    assert info["device_id"] == "mostech" and info["server_fp"] == fingerprint(ctx.keys.current[1])
    assert r["dev"] == "mostech" and len(r["echo"]["big"]) == MAX_CHUNK + 10
    assert len(session) == 16
    dev = ctx.registry.get("mostech")
    assert dev["name"] == "Ноутбук" and dev["last_seen"] and not dev["revoked"]
    assert ctx.pairing.active_psk() is None, "код одноразовый"


def test_pair_words_typed_with_noise(ctx):
    async def sc(uri):
        words, _ = ctx.pairing.create()
        typed = "  " + ", ".join(w.upper().replace("Е", "Ё") for w in words.split()) + "!"
        return await do_pair(uri, ctx, words=typed)
    _, info = serve(ctx, sc)
    assert info["device_id"]


def test_pair_qr_key_mismatch_aborts_before_message3(ctx):
    async def sc(uri):
        words, _ = ctx.pairing.create()
        with pytest.raises(HandshakeError):
            await do_pair(uri, ctx, words=words, expected_server_pub=generate_keypair()[1])
        return ctx.registry.list()
    assert serve(ctx, sc) == []


def test_pair_wrong_words_burns_attempts(ctx):
    async def sc(uri):
        ctx.pairing.create()
        results = []
        for _ in range(5):
            async with websockets.connect(uri, max_size=None) as ws:
                hs = Handshake.xx_initiator(generate_keypair()[0], words_to_psk("неверные слова"))
                await ws.send(encode_frame(FrameType.XX_1, hs.write(b"")))
                from securechannel.frames import decode_frame
                _, b = decode_frame(await ws.recv())
                hs.read(b)
                await ws.send(encode_frame(FrameType.XX_3, hs.write(b"{}")))
                results.append(await closed_with(ws))
        return results
    results = serve(ctx, sc)
    assert all(code == 4408 and not got for code, _, got in results)
    assert ctx.pairing.active_psk() is None, "5 неудач — код сгорел"
    assert ctx.registry.list() == []


def test_pair_without_code_or_expired(ctx):
    t = [1000.0]
    ctx.pairing = PairingManager(clock=lambda: t[0])

    async def sc(uri):
        out = []
        for setup in ("none", "expired"):
            if setup == "expired":
                words, _ = ctx.pairing.create()
                t[0] += 601
            async with websockets.connect(uri, max_size=None) as ws:
                hs = Handshake.xx_initiator(generate_keypair()[0], b"\x00" * 32)
                await ws.send(encode_frame(FrameType.XX_1, hs.write(b"")))
                out.append(await closed_with(ws))
        return out
    assert [(c, got) for c, _, got in serve(ctx, sc)] == [(4408, []), (4408, [])]


# ── отказы неотличимы ─────────────────────────────────────────────

def test_failures_are_silent_and_take_same_time(ctx):
    """Неизвестный ключ, отозванный ключ, битый IK_INIT, чужой ключ сервера:
    ни одного байта в ответ, закрытие 4408 в момент дедлайна."""
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        ctx.registry.revoke(info["device_id"])
        server_pub = ctx.keys.current[1]
        cases = {
            "unknown": Handshake.ik_initiator(generate_keypair()[0], server_pub).write(b"{}"),
            "revoked": Handshake.ik_initiator(priv, server_pub).write(b"{}"),
            "garbage": os.urandom(96),
            "wrong_server_key": Handshake.ik_initiator(priv, generate_keypair()[1]).write(b"{}"),
        }
        out = {}
        for name, m1 in cases.items():
            async with websockets.connect(uri, max_size=None) as ws:
                await ws.send(encode_frame(FrameType.IK_INIT, m1))
                out[name] = await closed_with(ws)
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(b"SK\x01")                      # битый первый кадр
            out["bad_frame"] = await closed_with(ws)
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(encode_frame(FrameType.IK_RESP, b"x"))   # не тот тип
            out["wrong_type"] = await closed_with(ws)
        return out
    out = serve(ctx, sc)
    times = []
    for name, (code, waited, got) in out.items():
        assert code == 4408 and got == [], name
        times.append(waited)
    assert min(times) >= TIMEOUT - 0.08 and max(times) - min(times) < 0.15, times


def test_revoked_device_cannot_reconnect_others_can(ctx):
    async def sc(uri):
        p1, i1 = await do_pair(uri, ctx, device_id_hint="mostech")
        p2, i2 = await do_pair(uri, ctx, device_id_hint="pc")
        ctx.registry.revoke("mostech")
        async with websockets.connect(uri, max_size=None) as ws:
            with pytest.raises(Exception):
                await connect_session(ws, p1, i1["server_pub_bytes"], device_id="mostech", timeout=2)
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, p2, i2["server_pub_bytes"], device_id="pc")
            await c.send('{"type":"ping"}')
            return json.loads(await c.recv())
    assert serve(ctx, sc)["dev"] == "pc"


def test_handshake_timeout_without_message3(ctx):
    async def sc(uri):
        ctx.pairing.create()
        async with websockets.connect(uri, max_size=None) as ws:
            hs = Handshake.xx_initiator(generate_keypair()[0], b"\x00" * 32)
            await ws.send(encode_frame(FrameType.XX_1, hs.write(b"")))
            await ws.recv()                                # XX_2 и молчим
            return await closed_with(ws)
    code, _, _ = serve(ctx, sc)
    assert code == 4408


# ── ротация ключа сервера ─────────────────────────────────────────

def test_rotation_accepts_old_key_and_announces_new(ctx):
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        old_pub = info["server_pub_bytes"]
        new_pub = ctx.keys.rotate(grace_seconds=3600)
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, old_pub, device_id=info["device_id"])
            announce = json.loads(await c.recv())
        async with websockets.connect(uri, max_size=None) as ws:
            c2 = await connect_session(ws, priv, new_pub, device_id=info["device_id"])
            await c2.send('{"type":"ping"}')
            r = json.loads(await c2.recv())
        return announce, new_pub, r
    announce, new_pub, r = serve(ctx, sc)
    assert announce["type"] == "secure_server_key" and announce["fp"] == fingerprint(new_pub)
    assert r["dev"]


def test_retired_key_rejected(tmp_path):
    t = [1000.0]
    ks = ServerKeys.load_or_create(str(tmp_path), clock=lambda: t[0])
    old = ks.current[1]
    ks.rotate(grace_seconds=10)
    assert [p for _, p in ks.accepted()] == [ks.current[1], old]
    t[0] += 11
    assert [p for _, p in ks.accepted()] == [ks.current[1]]


# ── лимиты ────────────────────────────────────────────────────────

def test_rate_limit_per_ip(ctx):
    ctx.limiter = HandshakeLimiter(per_ip_per_minute=3)

    async def sc(uri):
        codes = []
        for _ in range(4):
            async with websockets.connect(uri, max_size=None) as ws:
                await ws.send(encode_frame(FrameType.IK_INIT, os.urandom(96)))
                codes.append((await closed_with(ws))[0])
        return codes
    assert serve(ctx, sc) == [4408, 4408, 4408, 4429]


def test_limiter_parallel_and_window():
    t = [0.0]
    lim = HandshakeLimiter(per_ip_parallel=2, total_parallel=3, per_ip_per_minute=10,
                           clock=lambda: t[0])
    assert lim.try_begin("a") and lim.try_begin("a")
    assert not lim.try_begin("a"), "параллельно с IP"
    assert lim.try_begin("b") and not lim.try_begin("c"), "всего"
    lim.end("a")
    assert lim.try_begin("c")
    lim.end("zzz")                                     # чужой IP — без ошибки
    lim2 = HandshakeLimiter(per_ip_per_minute=2, clock=lambda: t[0])
    assert lim2.try_begin("x") and (lim2.end("x") or True) and lim2.try_begin("x")
    lim2.end("x")
    assert not lim2.try_begin("x")
    t[0] = 61.0
    assert lim2.try_begin("x")


# ── транспорт: целостность на сервере ─────────────────────────────

def test_tampered_transport_closes_4409(ctx):
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id=info["device_id"])
            frame = bytearray(c._ch.seal(b'{"type":"ping"}')[0])
            frame[-1] ^= 1
            await ws.send(bytes(frame))
            return await closed_with(ws)
    assert serve(ctx, sc)[0] == 4409


def test_text_frame_on_secure_channel_closes_4400(ctx):
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        async with websockets.connect(uri, max_size=None) as ws:
            await connect_session(ws, priv, info["server_pub_bytes"], device_id=info["device_id"])
            await ws.send('{"type":"ping","token":"x"}')
            return await closed_with(ws)
    assert serve(ctx, sc)[0] == 4400


def test_ping_pong_and_graceful_close(ctx):
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        async with websockets.connect(uri, max_size=None) as ws:
            c = await connect_session(ws, priv, info["server_pub_bytes"], device_id=info["device_id"])
            for f in c._ch.control(InnerType.PING, b"hi"):
                await ws.send(f)
            pong = c._ch.open(await ws.recv())
            await c.close(1000, "bye")
            return pong, c.close_code
    pong, code = serve(ctx, sc)
    assert pong == [(InnerType.PONG, b"hi")] and code == 1000


# ── хранение секретов ─────────────────────────────────────────────

def test_secret_files_are_600_and_dir_700(tmp_path):
    d = tmp_path / "secure"
    ks = ServerKeys.load_or_create(str(d))
    reg = DeviceRegistry.open(str(d))
    reg.add(generate_keypair()[1], name="x")
    for f in ("server_keys.json", "devices.json"):
        assert stat.S_IMODE(os.stat(d / f).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    again = ServerKeys.load_or_create(str(d))
    assert again.current == ks.current, "ключ переживает перезапуск"
    assert not [p for p in os.listdir(d) if p.startswith(".tmp-")]


def test_registry_ids_and_revoke(tmp_path):
    reg = DeviceRegistry.open(str(tmp_path))
    pub = generate_keypair()[1]
    a = reg.add(pub, name="Ноутбук", id_hint="Mostech!")
    assert a["id"] == "mostech" and reg.add(pub, name="dup")["id"] == "mostech"
    b = reg.add(generate_keypair()[1], name="x", id_hint="mostech", kind="weird")
    assert b["id"] == "mostech2" and b["kind"] == "other"
    assert reg.revoke("mostech") and not reg.revoke("mostech") and not reg.revoke("nope")
    assert reg.by_pub(pub) is None and reg.get("mostech")["revoked"]
    assert reg.add(generate_keypair()[1], name="", id_hint="")["id"] == "device"


def test_pairing_manager_rules():
    t = [0.0]
    pm = PairingManager(clock=lambda: t[0])
    assert pm.active_psk() is None and pm.status() is None
    w1, _ = pm.create()
    psk1 = words_to_psk(w1)
    assert pm.active_psk() == psk1 and len(w1.split()) == 8
    w2, _ = pm.create()                       # новый /pair отменяет прежний
    assert pm.active_psk() == words_to_psk(w2)
    pm.failed(psk1)                           # чужой psk не считается
    assert pm.status()["attempts"] == 0
    assert not pm.consume(psk1) and pm.consume(words_to_psk(w2))
    assert pm.active_psk() is None
    pm.cancel()
    assert pm.status() is None


def test_qr_uri_validation():
    pub = generate_keypair()[1]
    uri = make_qr_uri("ws://31.76.80.5:8765", pub, "лес кот мост чай лось гриб луна дом", 1791900000)
    assert uri.startswith("sakura-pair://1?u=ws%3A%2F%2F31.76.80.5%3A8765&k=")
    q = parse_qr_uri(uri)
    assert q["url"] == "ws://31.76.80.5:8765" and q["expires"] == 1791900000
    for bad in ("http://x", "sakura-pair://2?u=a&k=b&w=c&e=1",
                make_qr_uri("ws://h", pub, "лес кот мост чай лось гриб луна", 1),   # 7 слов
                uri.replace("k=", "k=AA")):
        with pytest.raises((ValueError, KeyError)):
            parse_qr_uri(bad)
