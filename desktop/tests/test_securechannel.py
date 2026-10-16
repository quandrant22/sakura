"""Клиент securechannel/1: кадры, спаривание, ключи, канал и полный путь против учебного сервера."""
import asyncio
import json
import os
import time

import pytest
import websockets

from desktop.core.securechannel import frames as F
from desktop.core.securechannel import noise as N
from desktop.core.securechannel.channel import IntegrityError, SecureChannel
from desktop.core.securechannel.client import SecureError, ik_handshake, xx_pair
from desktop.core.securechannel.keys import KeyStore, fingerprint
from desktop.core.securechannel.pairing import PairingError, make_qr_uri, normalize_words, parse_qr_uri, words_to_psk
from desktop.tools.securelab.server import LabServer

WORDS = "Лес кот мост ёлка река гора снег луна"


# ── кадры ──
def test_frame_roundtrip_and_errors():
    fr = F.encode_frame(F.FrameType.TRANSPORT, b"abc")
    assert fr[:4] == b"SK\x01\x20" and F.decode_frame(fr) == (F.FrameType.TRANSPORT, b"abc")
    for bad in (b"XX\x01\x20\x00\x00\x00\x00", fr[:-1], b"SK\x02\x20\x00\x00\x00\x00", b"SK\x01\x99\x00\x00\x00\x00"):
        with pytest.raises(F.FrameError):
            F.decode_frame(bad)


def test_fragment_limits():
    msg = os.urandom(F.MAX_MESSAGE)
    chunks = F.fragment(msg)
    assert len(chunks) == 33 and all(c[1] == F.FLAG_MORE for c in chunks[:-1]) and chunks[-1][1] == 0
    r = F.Reassembler()
    out = [r.feed(c[1], c[2:]) for c in chunks]
    assert out[-1] == msg and all(x is None for x in out[:-1])
    with pytest.raises(F.TooLarge):
        F.fragment(b"x" * (F.MAX_MESSAGE + 1))


# ── спаривание ──
def test_words_normalization_and_psk():
    assert normalize_words("  Лес,КОТ-мост  ёлка\nрека гора 7 снег луна") == "лес кот мост елка река гора снег луна"
    assert words_to_psk(WORDS) == words_to_psk("лес кот мост елка река гора снег луна")
    assert len(words_to_psk(WORDS)) == 32
    with pytest.raises(PairingError):
        words_to_psk("лес кот")


def test_qr_roundtrip_and_expiry():
    pub = os.urandom(32)
    uri = make_qr_uri("ws://31.76.80.5:8765", pub, WORDS, time.time() + 600)
    d = parse_qr_uri(uri)
    assert d["server_pub"] == pub and d["url"] == "ws://31.76.80.5:8765" and d["words"].startswith("лес кот")
    with pytest.raises(PairingError, match="истёк"):
        parse_qr_uri(make_qr_uri("ws://h", pub, WORDS, time.time() - 1))
    with pytest.raises(PairingError):
        parse_qr_uri("https://example.com")


# ── ключи ──
def test_keystore_protects_and_resets(tmp_path):
    prot = []
    ks = KeyStore(str(tmp_path), protect=lambda b: prot.append(1) or b[::-1], unprotect=lambda b: b[::-1])
    priv, pub = ks.device_keypair()
    assert prot and (tmp_path / "device_key.dpapi").read_bytes() != priv  # на диске — не в открытом виде
    assert ks.device_keypair()[1] == pub
    spub = os.urandom(32)
    ks.save_server(spub, "pc", "ws://h")
    st = ks.status()
    assert st["paired"] and st["server_fp"] == fingerprint(spub) and st["storage"] == "dpapi"
    assert priv.hex() not in json.dumps(st)
    ks.reset()
    assert ks.status() == {"device_key": False, "device_fp": None, "storage": None, "paired": False,
                           "server_fp": None, "device_id": None}


def test_fingerprint_format():
    fp = fingerprint(b"\x00" * 32)
    assert len(fp) == 19 and fp.count(" ") == 3


# ── канал ──
def pair_channels():
    c_priv, _ = N.generate_keypair()
    s_priv, s_pub = N.generate_keypair()
    i = N.HandshakeState("IK", True, b"p", s_priv=c_priv, rs=s_pub)
    r = N.HandshakeState("IK", False, b"p", s_priv=s_priv)
    r.read(i.write())
    i.read(r.write())
    a, b = i.split(), r.split()
    return SecureChannel(*a, rekey_messages=3), SecureChannel(*b, rekey_messages=3)


def test_channel_replay_reorder_tamper():
    c, s = pair_channels()
    f1, f2 = c.seal("один")[0], c.seal("два")[0]
    with pytest.raises(IntegrityError):  # перестановка
        s.open(f2)
    c, s = pair_channels()
    f1 = c.seal("один")[0]
    assert s.open(f1) == [(F.InnerType.DATA, "один".encode())]
    with pytest.raises(IntegrityError):  # повтор
        s.open(f1)
    c, s = pair_channels()
    f1 = bytearray(c.seal("один")[0])
    f1[-1] ^= 1
    with pytest.raises(IntegrityError):  # подмена
        s.open(bytes(f1))


def test_channel_rekey_by_messages():
    c, s = pair_channels()
    got = []
    for i in range(10):
        for fr in c.seal(f"m{i}"):
            got += s.open(fr)
    assert [d.decode() for _, d in got] == [f"m{i}" for i in range(10)]
    assert c.rekeys_out == 3 and s.rekeys_in == 3


# ── полный путь против учебного сервера ──
async def _with_server(fn, **kw):
    lab = LabServer(**kw)
    server = await lab.serve()
    port = server.sockets[0].getsockname()[1]
    try:
        return await fn(lab, f"ws://127.0.0.1:{port}")
    finally:
        server.close()
        await server.wait_closed()


def test_pair_then_session_echo_and_2mb(tmp_path):
    async def go(lab, url):
        lab.start_pairing(WORDS)
        ks = KeyStore(str(tmp_path), protect=lambda b: b, unprotect=lambda b: b)
        priv, pub = ks.device_keypair()
        async with websockets.connect(url, max_size=None) as ws:
            res = await xx_pair(ws, priv, words_to_psk(WORDS), {"name": "PC", "kind": "pc", "device_id_hint": "pc"},
                                expected_server_pub=lab.pub)
        assert res["server_pub"] == lab.pub and res["device_id"] == "pc"
        ks.save_server(res["server_pub"], res["device_id"], url)
        async with websockets.connect(url, max_size=None) as ws:
            conn = await ik_handshake(ws, priv, ks.server()["pub_bytes"], "pc")
            reg = json.dumps({"type": "register", "request_id": "r1"})
            await conn.send(reg)
            assert json.loads(await conn.recv()) == {"type": "echo", "request_id": "r1", "device_id": "pc",
                                                     "secure": True, "size": len(reg)}
            big = json.dumps({"type": "screenshot", "request_id": "r2", "data": "x" * (2 * 1024 * 1024 - 100)})
            await conn.send(big)
            assert json.loads(await conn.recv())["size"] == len(big)
            return conn.stats()
    st = asyncio.run(_with_server(go))
    assert st["transport"] == "noise" and st["frames_out"] >= 34


def test_unknown_or_revoked_device_rejected_at_deadline(tmp_path):
    async def go(lab, url):
        priv, _ = N.generate_keypair()
        t = time.monotonic()
        async with websockets.connect(url) as ws:
            with pytest.raises(SecureError) as e:
                await ik_handshake(ws, priv, lab.pub, "x", timeout=3)
        return e.value.code, time.monotonic() - t
    code, dt = asyncio.run(_with_server(go, deadline=0.4))
    assert code == 4408 and dt >= 0.35  # молчание до дедлайна, а не мгновенный отказ


def test_wrong_pairing_words_fail(tmp_path):
    async def go(lab, url):
        lab.start_pairing(WORDS)
        priv, _ = N.generate_keypair()
        async with websockets.connect(url) as ws:
            with pytest.raises(SecureError, match="не подошёл"):
                await xx_pair(ws, priv, words_to_psk("один два три четыре пять шесть семь восемь"), {"name": "x"},
                              timeout=2)
    asyncio.run(_with_server(go, deadline=0.3))


def test_required_mode_refuses_plain_text():
    async def go(lab, url):
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"type": "register", "token": "lab-token"}))
            with pytest.raises(websockets.ConnectionClosed) as e:
                await ws.recv()
        return e.value.rcvd.code
    assert asyncio.run(_with_server(go, mode="required")) == 4412


# ── Настройки → «Безопасность» (команды ядра) ──
def _svc(tmp_path, monkeypatch):
    from desktop.core import config
    from desktop.core.service import CoreService
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    svc = CoreService.__new__(CoreService)
    svc._restrict = lambda p: None
    svc.link = type("L", (), {"state_event": lambda self: {"server": "online", "proto": 2}})()
    return svc


def test_secure_pair_by_words_and_qr_status_reset(tmp_path, monkeypatch):
    from desktop.core.api.server import ApiError

    async def go(lab, url):
        svc = _svc(tmp_path, monkeypatch)
        monkeypatch.setattr(svc, "_keystore", lambda: KeyStore(str(tmp_path / "secure"), protect=lambda b: b,
                                                                unprotect=lambda b: b))
        lab.start_pairing(WORDS)
        out = await svc.cmd_secure_pair({"words": WORDS, "url": url, "name": "Ноутбук"})
        assert out["server_fp"] == fingerprint(lab.pub)
        st = await svc.cmd_secure_status({})
        assert st["keys"]["paired"] and st["keys"]["server_fp"] == out["server_fp"]
        # QR с подменённым ключом сервера — спаривание остановлено до отправки XX_3
        lab.start_pairing(WORDS)
        bad = make_qr_uri(url, os.urandom(32), WORDS, time.time() + 600)
        with pytest.raises(ApiError, match="подмена"):
            await svc.cmd_secure_pair({"uri": bad})
        good = make_qr_uri(url, lab.pub, WORDS, time.time() + 600)
        lab.start_pairing(WORDS)
        assert (await svc.cmd_secure_pair({"uri": good}))["server_fp"] == fingerprint(lab.pub)
        assert (await svc.cmd_secure_reset({}))["keys"]["paired"] is False
    asyncio.run(_with_server(go))
