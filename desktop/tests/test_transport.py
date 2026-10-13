"""Подключаемый транспорт до сервера: выбор, проверка отпечатка, откат с noise."""
import asyncio
import hashlib
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


def test_noise_falls_back_to_ws_or_wss(caplog):
    assert T.make_transport("noise", "ws://h").kind == "ws"
    assert T.make_transport("noise", "wss://h").kind == "wss"
    assert "noise ещё не реализован" in caplog.text
    with pytest.raises(NotImplementedError):
        asyncio.run(T.NoiseTransport("tcp://h").connect())


def test_session_closes_connection():
    conn = FakeConn()

    async def go():
        t = T.make_transport("ws", "ws://h", connect_fn=fake_connect([], conn))
        async with T.session(t) as c:
            assert c is conn
    asyncio.run(go())
    assert conn.closed is True
