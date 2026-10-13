"""desktop.core.transport — транспорт до сервера за интерфейсом: connect / send / recv / close.

SERVER_TRANSPORT выбирает реализацию (по умолчанию — по схеме VPS_WS_URL, поведение не меняется):
  ws    — WebSocket; для wss:// TLS с проверкой сертификата по системному хранилищу;
  wss   — только wss:// (ws:// отклоняется: соединение было бы без шифрования);
          SERVER_CERT_SHA256 — закрепление отпечатка сертификата сервера (SHA-256 DER, hex,
          двоеточия и регистр не важны); несовпадение — отказ, отката нет;
  noise — Noise-протокол поверх TCP: пока заглушка (интерфейс и TODO), при выборе — откат
          на ws/wss по схеме URL с предупреждением в журнале.
Соединение, которое отдаёт connect(), умеет send(), recv(), close() и async for — как websockets.
"""
import contextlib
import hashlib
import logging
import ssl
from typing import Protocol

import websockets

log = logging.getLogger("sakura.transport")

KINDS = ("ws", "wss", "noise")


class TransportError(ConnectionError):
    """Отказ транспорта (неверная настройка, несовпадение отпечатка)."""


class Connection(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...
    def __aiter__(self): ...


class Transport(Protocol):
    kind: str

    async def connect(self) -> Connection: ...


def normalize_fp(fp: str) -> str:
    return "".join(c for c in (fp or "").lower() if c in "0123456789abcdef")


def verify_fingerprint(der: bytes | None, expected: str) -> None:
    """Сертификат сервера (DER) должен совпасть с закреплённым SHA-256; иначе TransportError."""
    want = normalize_fp(expected)
    if len(want) != 64:
        raise TransportError("SERVER_CERT_SHA256 должен быть SHA-256 (64 шестнадцатеричных знака)")
    got = hashlib.sha256(der).hexdigest() if der else ""
    if got != want:
        raise TransportError("отпечаток сертификата сервера не совпал с SERVER_CERT_SHA256 — соединение отклонено")


class WsTransport:
    """WebSocket (ws:// или wss://). connect_fn подменяется в тестах."""

    def __init__(self, url: str, kind: str = "ws", cert_sha256: str = "", connect_fn=None,
                 ssl_context: ssl.SSLContext | None = None):
        self.url = url
        self.kind = kind
        self.cert_sha256 = cert_sha256
        self._connect = connect_fn or websockets.connect
        self._ssl = ssl_context
        secure = url.startswith("wss://")
        if kind == "wss" and not secure:
            raise TransportError("SERVER_TRANSPORT=wss требует адрес wss:// в VPS_WS_URL")
        if cert_sha256 and not secure:
            raise TransportError("SERVER_CERT_SHA256 задан, но адрес не wss:// — закреплять нечего")

    async def connect(self) -> Connection:
        kw = {"ping_interval": 20, "proxy": None, "max_size": None}
        if self.url.startswith("wss://"):
            kw["ssl"] = self._ssl or ssl.create_default_context()  # проверка цепочки и имени хоста
        conn = await self._connect(self.url, **kw)
        if self.cert_sha256:
            sslobj = getattr(conn, "transport", None)
            sslobj = sslobj.get_extra_info("ssl_object") if sslobj is not None else None
            der = sslobj.getpeercert(binary_form=True) if sslobj is not None else None
            try:
                verify_fingerprint(der, self.cert_sha256)
            except TransportError:
                await conn.close()
                raise
        return conn


class NoiseTransport:
    """Noise (XX/IK поверх TCP) — заглушка.

    TODO: выбрать библиотеку (dissononce / noiseprotocol), рукопожатие по статическому ключу
    сервера (SERVER_NOISE_PUBKEY), кадрирование сообщений длиной, тот же интерфейс Connection.
    """
    kind = "noise"

    def __init__(self, url: str):
        self.url = url

    async def connect(self) -> Connection:
        raise NotImplementedError("транспорт noise ещё не реализован")


def make_transport(kind: str | None, url: str, cert_sha256: str = "", connect_fn=None) -> Transport:
    """Транспорт по настройке; noise пока откатывается на ws/wss по схеме URL."""
    kind = (kind or "").strip().lower() or ("wss" if url.startswith("wss://") else "ws")
    if kind not in KINDS:
        raise TransportError(f"SERVER_TRANSPORT: неизвестный транспорт «{kind}» (ws, wss, noise)")
    if kind == "noise":
        log.warning("[transport] noise ещё не реализован — использую %s", "wss" if url.startswith("wss://") else "ws")
        kind = "wss" if url.startswith("wss://") else "ws"
    return WsTransport(url, kind=kind, cert_sha256=cert_sha256, connect_fn=connect_fn)


@contextlib.asynccontextmanager
async def session(transport: Transport):
    """async with session(t) as conn: … — соединение закрывается при выходе."""
    conn = await transport.connect()
    try:
        yield conn
    finally:
        with contextlib.suppress(Exception):
            await conn.close()
