"""desktop.core.transport — транспорт до сервера за интерфейсом: connect / send / recv / close.

SERVER_TRANSPORT выбирает реализацию (по умолчанию — по схеме VPS_WS_URL, поведение не меняется):
  ws    — WebSocket; для wss:// TLS с проверкой сертификата по системному хранилищу;
  wss   — только wss:// (ws:// отклоняется: соединение было бы без шифрования);
          SERVER_CERT_SHA256 — закрепление отпечатка сертификата сервера (SHA-256 DER, hex,
          двоеточия и регистр не важны); несовпадение — отказ, отката нет;
  noise — защищённый канал securechannel/1 (Noise IK поверх WebSocket, docs/security/PROTOCOL.md);
          устройство не подключено или сервер не принял канал — откат на ws с токеном и пометкой
          «не защищено» (state); несовпадение SERVER_PUBKEY_SHA256 — отказ без отката (подмена);
  noise-only — то же без отката (сервер в режиме required или нужна гарантия шифрования).
Соединение, которое отдаёт connect(), умеет send(), recv(), close() и async for — как websockets.
"""
import contextlib
import hashlib
import logging
import ssl
from typing import Protocol

import websockets

log = logging.getLogger("sakura.transport")

KINDS = ("ws", "wss", "noise", "noise-only")


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
    """securechannel/1: сеанс IK по ключу устройства; required=False — откат на ws с токеном."""

    def __init__(self, url: str, required: bool = False, keystore=None, pubkey_sha256: str = "",
                 connect_fn=None, fallback: Transport | None = None):
        self.url = url
        self.required = required
        self.kind = "noise-only" if required else "noise"
        self._keystore = keystore
        self.pubkey_sha256 = normalize_fp(pubkey_sha256)
        self._connect = connect_fn or websockets.connect
        self._fallback = fallback
        self.state: dict = {"transport": None, "secure": False, "reason": None}

    @property
    def keystore(self):
        if self._keystore is None:
            import os

            from desktop.core import config
            from desktop.core.securechannel.keys import KeyStore
            restrict = None
            if os.name == "nt":
                from desktop.core.platform import get_platform
                restrict = get_platform().restrict_to_current_user
            self._keystore = KeyStore(os.path.join(config.DATA_DIR, "secure"), restrict=restrict)
        return self._keystore

    async def _fallback_or_raise(self, reason: str) -> Connection:
        if self.required or self._fallback is None:
            self.state = {"transport": None, "secure": False, "reason": reason}
            raise TransportError(f"защищённый канал недоступен: {reason}")
        log.warning("[transport] защищённый канал недоступен (%s) — подключаюсь без защиты (ws)", reason)
        conn = await self._fallback.connect()
        self.state = {"transport": "ws", "secure": False, "reason": reason}
        return conn

    async def connect(self) -> Connection:
        from desktop.core.securechannel.client import SecureError, ik_handshake
        from desktop.core.securechannel.keys import sha256_hex
        ks = self.keystore
        srv, kp = ks.server(), ks.device_keypair(create=False)
        if not srv or not kp:
            return await self._fallback_or_raise("устройство не подключено (Настройки → Безопасность)")
        if self.pubkey_sha256 and sha256_hex(srv["pub_bytes"]) != self.pubkey_sha256:
            self.state = {"transport": None, "secure": False, "reason": "ключ сервера не совпал с SERVER_PUBKEY_SHA256"}
            raise TransportError("ключ сервера не совпал с SERVER_PUBKEY_SHA256 — подключение отклонено")
        ws = await self._connect(self.url, ping_interval=20, proxy=None, max_size=None)
        try:
            conn = await ik_handshake(ws, kp[0], srv["pub_bytes"], srv.get("device_id") or "")
        except SecureError as e:
            with contextlib.suppress(Exception):
                await ws.close()
            if e.code == 4408:  # ключ не узнан или отозван — откат на ws не спасёт доверие, но сохраняет связь
                log.warning("[transport] сервер не узнал ключ устройства")
            return await self._fallback_or_raise(str(e))
        conn.on_server_key = ks.rotate_server_key
        self.state = {"transport": "noise", "secure": True, "reason": None, "server_fp": srv.get("fp")}
        return conn


def make_transport(kind: str | None, url: str, cert_sha256: str = "", connect_fn=None,
                   pubkey_sha256: str = "", keystore=None) -> Transport:
    """Транспорт по настройке SERVER_TRANSPORT; по умолчанию — по схеме URL (ws или wss)."""
    kind = (kind or "").strip().lower() or ("wss" if url.startswith("wss://") else "ws")
    if kind not in KINDS:
        raise TransportError(f"SERVER_TRANSPORT: неизвестный транспорт «{kind}» (ws, wss, noise, noise-only)")
    if kind in ("noise", "noise-only"):
        ws_url = url.replace("wss://", "ws://", 1) if url.startswith("wss://") else url
        fallback = None if kind == "noise-only" else WsTransport(url, kind="wss" if url.startswith("wss://") else "ws",
                                                                    cert_sha256=cert_sha256, connect_fn=connect_fn)
        return NoiseTransport(ws_url if not url.startswith("wss://") else url, required=kind == "noise-only",
                              keystore=keystore, pubkey_sha256=pubkey_sha256, connect_fn=connect_fn, fallback=fallback)
    t = WsTransport(url, kind=kind, cert_sha256=cert_sha256, connect_fn=connect_fn)
    t.state = {"transport": kind, "secure": url.startswith("wss://"), "reason": None}
    return t


@contextlib.asynccontextmanager
async def session(transport: Transport):
    """async with session(t) as conn: … — соединение закрывается при выходе."""
    conn = await transport.connect()
    try:
        yield conn
    finally:
        with contextlib.suppress(Exception):
            await conn.close()
