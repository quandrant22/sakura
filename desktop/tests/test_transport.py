"""Подключаемый транспорт до сервера: выбор, проверка отпечатка, откат с noise."""
import asyncio
import hashlib
import os
import ssl

import pytest

from desktop.core import transport as T

DER = b"fake-certificate-der"
GOOD = hashlib.sha256(DER).hexdigest()


class FakeConn:
    def __init__(self, der=DER):
        self.closed = False
        ssl_object = type("S", (), {"getpeercert": lambda self, binary_form=False: der})()
        self.transport = type("Tr", (), {"get_extra_info": lambda self, k: ssl_object if k == "ssl_object" else None})()

    async def close(self):
        self.closed = True


def fake_connect(calls, conn=None):
    async def connect(url, **kw):
        calls.append((url, kw))
        return conn or FakeConn()
    return connect


def test_default_by_url_scheme_and_same_ws_options():
    calls = []
    t = T.make_transport("", "ws://1.2.3.4:8765", connect_fn=fake_connect(calls))
    assert t.kind == "ws"
    asyncio.run(t.connect())
    # поведение прежнее: те же параметры, что были у websockets.connect в agent.run
    assert calls == [("ws://1.2.3.4:8765", {"ping_interval": 20, "proxy": None, "max_size": None})]
    assert T.make_transport(None, "wss://h:443").kind == "wss"


def test_wss_uses_verified_tls_context():
    calls = []
    asyncio.run(T.make_transport("wss", "wss://h", connect_fn=fake_connect(calls)).connect())
    ctx = calls[0][1]["ssl"]
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_wss_refuses_plain_ws_url_and_unknown_kind():
    with pytest.raises(T.TransportError):
        T.make_transport("wss", "ws://h:8765")
    with pytest.raises(T.TransportError):
        T.make_transport("quic", "ws://h")
    with pytest.raises(T.TransportError):
        T.make_transport("ws", "ws://h", cert_sha256=GOOD)  # закреплять нечего без TLS


def test_pinned_fingerprint_match_and_mismatch():
    calls = []
    pinned = ":".join(GOOD[i:i + 2].upper() for i in range(0, 64, 2))  # формат с двоеточиями
    conn = asyncio.run(T.make_transport("wss", "wss://h", cert_sha256=pinned, connect_fn=fake_connect(calls)).connect())
    assert conn.closed is False
    bad = FakeConn(der=b"other-cert")
    with pytest.raises(T.TransportError, match="отпечаток"):
        asyncio.run(T.make_transport("wss", "wss://h", cert_sha256=GOOD, connect_fn=fake_connect([], bad)).connect())
    assert bad.closed is True  # соединение с чужим сертификатом закрыто, отката нет


def test_bad_pin_format_rejected():
    with pytest.raises(T.TransportError, match="64"):
        T.verify_fingerprint(DER, "abcd")


def test_session_closes_connection():
    conn = FakeConn()

    async def go():
        t = T.make_transport("ws", "ws://h", connect_fn=fake_connect([], conn))
        async with T.session(t) as c:
            assert c is conn
    asyncio.run(go())
    assert conn.closed is True


# ── защищённый канал (noise) против учебного сервера ──
def _lab(fn, **kw):
    import websockets as W

    from desktop.tools.securelab.server import LabServer

    async def go():
        lab = LabServer(deadline=0.3, **kw)
        server = await lab.serve()
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        try:
            return await fn(lab, url, W.connect)
        finally:
            server.close()
            await server.wait_closed()
    return asyncio.run(go())


def _paired_store(tmp_path, lab, url, device_id="pc"):
    from desktop.core.securechannel.keys import KeyStore
    ks = KeyStore(str(tmp_path), protect=lambda b: b, unprotect=lambda b: b)
    _, pub = ks.device_keypair()
    lab.add_device(pub, device_id)
    ks.save_server(lab.pub, device_id, url)
    return ks


def test_noise_unpaired_falls_back_to_ws_marked_insecure(tmp_path):
    from desktop.core.securechannel.keys import KeyStore

    async def fn(lab, url, connect):
        t = T.make_transport("noise", url, connect_fn=connect, keystore=KeyStore(str(tmp_path)))
        conn = await t.connect()
        await conn.close()
        return t.state
    st = _lab(fn)
    assert st["transport"] == "ws" and st["secure"] is False and "не подключено" in st["reason"]


def test_noise_only_unpaired_refuses(tmp_path):
    from desktop.core.securechannel.keys import KeyStore

    async def fn(lab, url, connect):
        t = T.make_transport("noise-only", url, connect_fn=connect, keystore=KeyStore(str(tmp_path)))
        with pytest.raises(T.TransportError, match="защищённый канал недоступен"):
            await t.connect()
    _lab(fn)


def test_noise_paired_secure_session_and_server_key_rotation(tmp_path):
    import json

    async def fn(lab, url, connect):
        ks = _paired_store(tmp_path, lab, url)
        t = T.make_transport("noise", url, connect_fn=connect, keystore=ks)
        conn = await t.connect()
        await conn.send(json.dumps({"type": "ping", "request_id": "1"}))
        reply = json.loads(await conn.recv())
        new_pub = os.urandom(32)
        conn.on_server_key(new_pub)
        await conn.close()
        return t.state, reply, ks.server()["pub_bytes"] == new_pub
    st, reply, rotated = _lab(fn)
    assert st["transport"] == "noise" and st["secure"] is True and reply["secure"] is True and rotated


def test_noise_pin_mismatch_refuses_without_fallback(tmp_path):
    async def fn(lab, url, connect):
        ks = _paired_store(tmp_path, lab, url)
        t = T.make_transport("noise", url, connect_fn=connect, keystore=ks, pubkey_sha256="00" * 32)
        with pytest.raises(T.TransportError, match="SERVER_PUBKEY_SHA256"):
            await t.connect()
    _lab(fn)


def test_noise_unknown_key_falls_back_or_refuses(tmp_path):
    from desktop.core.securechannel.keys import KeyStore

    async def fn(lab, url, connect):
        ks = KeyStore(str(tmp_path), protect=lambda b: b, unprotect=lambda b: b)
        ks.device_keypair()
        ks.save_server(lab.pub, "pc", url)  # спарено «у себя», но сервер ключа не знает (отозван)
        t = T.make_transport("noise", url, connect_fn=connect, keystore=ks)
        conn = await t.connect()
        await conn.close()
        strict = T.make_transport("noise-only", url, connect_fn=connect, keystore=ks)
        with pytest.raises(T.TransportError):
            await strict.connect()
        return t.state
    st = _lab(fn)
    assert st["transport"] == "ws" and "не узнал" in st["reason"]


def test_kinds_and_default_unchanged():
    assert T.make_transport(None, "ws://h").kind == "ws"
    assert T.make_transport("noise-only", "ws://h").required is True
    with pytest.raises(T.TransportError):
        T.make_transport("tls", "ws://h")
