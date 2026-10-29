"""
core/transport.py — соединение агента с сервером: Noise или старый ws+token.

    conn = await open_connection(config.VPS_WS_URL, config.AGENT_SECURE)
    await conn.send_json({"type": "register", ...})
    async for raw in conn: ...

Выбор транспорта (docs/security/PROTOCOL.md, docs/DECISIONS.md «Агент: транспорт»):
  * ключей нет, режим off/prefer  → старый протокол, token в каждом JSON;
  * ключей нет, режим required    → NotPaired, не подключаемся;
  * ключи есть (любой режим)      → ТОЛЬКО Noise IK. Неудача рукопожатия —
    SecureHandshakeFailed, вызывающий ждёт и пробует снова. Отката на token
    нет: иначе атакующий на пути понизил бы канал до открытого текста,
    просто обрывая рукопожатие.

Ключ сервера: сначала текущий, при неудаче — next_server_pub (ротация,
PROTOCOL §8.2); успех на нём → promote_next(). Новый ключ сервер сообщает
сообщением secure_server_key — его принимаем только внутри Noise.

В журнал — только transport, secure, device_id, отпечаток ключа сервера
и код результата. Никогда: ключи, payload рукопожатия, тексты.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys

import websockets

log = logging.getLogger("sakura.agent")

MODES = ("off", "prefer", "required")
HANDSHAKE_TIMEOUT_S = 10.0
KEYS_POLL_S = 5.0

CLOSE_HANDSHAKE = 4408
CLOSE_INTEGRITY = 4409
CLOSE_SECURE_REQUIRED = 4412
CLOSE_TOO_LARGE = 4413

# Параметры websockets.connect — как были у агента до Noise.
_WS_KWARGS = {"ping_interval": 20, "proxy": None, "max_size": None}


def _ensure_securechannel_path() -> None:
    """securechannel/ лежит в корне репозитория, рядом с agent/.

    В собранном .exe пакет уже внутри (build.bat, --paths ..). Из исходников
    корень добавляется В КОНЕЦ sys.path: иначе config.py сервера заслонил бы
    config.py агента.
    """
    try:
        import securechannel  # noqa: F401
        return
    except ImportError:
        pass
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.isdir(os.path.join(root, "securechannel")) and root not in sys.path:
        sys.path.append(root)


class NotPaired(Exception):
    """Режим required, а ключей устройства нет — подключаться нельзя."""


class SecureHandshakeFailed(Exception):
    """Рукопожатие Noise не прошло (таймаут, 4408, 4429, обрыв, подмена)."""

    def __init__(self, reason: str, code: int | None = None):
        super().__init__(f"{reason}" + (f" (код {code})" if code else ""))
        self.reason = reason
        self.code = code


class MessageTooLarge(Exception):
    """Сообщение больше 2 МиБ — по Noise не отправить (PROTOCOL §4.2, 4413)."""


def normalize_mode(mode: str | None) -> str:
    m = (mode or "prefer").strip().lower()
    return m if m in MODES else "prefer"


def _default_store():
    """core.secure_store (хранилище ключа устройства) или None, если его нет."""
    try:
        from core import secure_store
        return secure_store
    except ImportError:
        return None


def load_keys(store=None):
    store = _default_store() if store is None else store
    if store is None:
        return None
    try:
        return store.load()
    except Exception as e:
        # Битый файл ключа — это не «ключей нет»: молча уходить на token нельзя.
        log.error("[transport] ключи устройства не читаются: %s", type(e).__name__)
        raise SecureHandshakeFailed("ключи устройства не читаются") from e


def _field(keys, name: str):
    if isinstance(keys, dict):
        return keys.get(name)
    return getattr(keys, name, None)


def key_bytes(value) -> bytes:
    """Ключ X25519 из хранилища: bytes или base64/base64url → 32 байта."""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, str) and value:
        text = value.strip().replace("-", "+").replace("_", "/")
        raw = base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
    else:
        raise ValueError("ключ не задан")
    if len(raw) != 32:
        raise ValueError("ключ не 32 байта")
    return raw


def _fp(pub: bytes) -> str:
    _ensure_securechannel_path()
    from securechannel.keys import fingerprint
    return fingerprint(pub)


def _close_code_of(exc) -> int | None:
    for attr in ("rcvd", "sent"):
        frame = getattr(exc, attr, None)
        if frame is not None and getattr(frame, "code", None):
            return frame.code
    return getattr(exc, "code", None)


async def _quiet_close(io, *args) -> None:
    try:
        await io.close(*args)
    except (OSError, RuntimeError, websockets.ConnectionClosed) as e:
        log.debug("[transport] закрытие: %s", type(e).__name__)


def _is_closed(exc) -> bool:
    return (isinstance(exc, websockets.ConnectionClosed)
            or type(exc).__name__ == "SecureChannelClosed")


class Conn:
    """Соединение с сервером; для агента одинаково на ws и на Noise.

    send_json — единственный путь исходящих JSON: token добавляется только
    на старом транспорте и вырезается на Noise.
    """

    def __init__(self, ws, *, transport: str, channel=None, token: str = "",
                 store=None, server_fp: str = "", device_id: str = ""):
        self._ws = ws
        self._io = channel if channel is not None else ws
        self.transport = transport
        self.secure = transport == "noise"
        self._token = token
        self._store = store
        self.server_fp = server_fp
        self.device_id = device_id
        self._close_code: int | None = None

    # ── отправка ──────────────────────────────────────────────────────

    async def send(self, text) -> None:
        try:
            await self._io.send(text)
        except Exception as e:
            if self.secure and type(e).__name__ == "SecureChannelClosed" \
                    and getattr(e, "code", None) == CLOSE_TOO_LARGE:
                size = len(text.encode("utf-8") if isinstance(text, str) else text)
                log.error("[transport] transport=noise сообщение %d байт > 2 МиБ — "
                          "не отправлено (4413)", size)
                raise MessageTooLarge(size) from None
            raise

    async def send_json(self, obj: dict) -> None:
        msg = dict(obj)
        if self.secure:
            msg.pop("token", None)
        else:
            msg["token"] = self._token
        await self.send(json.dumps(msg))

    # ── приём ─────────────────────────────────────────────────────────

    async def recv(self):
        try:
            return await self._io.recv()
        except Exception as e:
            if _is_closed(e):
                self._close_code = self._close_code or _close_code_of(e)
            raise

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except Exception as e:
            if _is_closed(e):
                raise StopAsyncIteration from None
            raise

    @property
    def close_code(self) -> int | None:
        """Код закрытия: из CLOSE внутри Noise или из WebSocket close."""
        return (self._close_code
                or getattr(self._io, "close_code", None)
                or getattr(self._ws, "close_code", None))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await _quiet_close(self._io, code, reason)

    # ── ротация ключа сервера ─────────────────────────────────────────

    def accept_server_key(self, msg: dict) -> bool:
        """secure_server_key (PROTOCOL §5): запомнить следующий ключ сервера.

        Только из Noise: по открытому ws его подсунул бы кто угодно.
        """
        if not self.secure:
            log.warning("[transport] transport=ws: secure_server_key вне Noise — отброшен")
            return False
        pub = msg.get("pub") if isinstance(msg, dict) else None
        try:
            raw = key_bytes(pub)
        except (ValueError, TypeError):
            log.warning("[transport] secure_server_key: неверный ключ — отброшен")
            return False
        store = self._store if self._store is not None else _default_store()
        if store is None:
            return False
        store.set_next_server_pub(pub)
        log.info("[transport] новый ключ сервера fp=%s сохранён, будет со следующего "
                 "подключения", _fp(raw))
        return True


async def wait_for_keys(store=None, poll: float = KEYS_POLL_S):
    """Ждать, пока появятся ключи устройства (после спаривания)."""
    while True:
        try:
            keys = load_keys(store)
        except SecureHandshakeFailed:
            keys = None
        if keys is not None:
            return keys
        await asyncio.sleep(poll)


async def _noise_session(url, priv, server_pub, device_id, timeout, connect):
    _ensure_securechannel_path()
    from securechannel.client import connect_session

    ws = await connect(url, **_WS_KWARGS)
    try:
        session = await asyncio.wait_for(
            connect_session(ws, priv, server_pub, device_id=device_id, timeout=timeout),
            timeout)
    except asyncio.CancelledError:
        await _quiet_close(ws)
        raise
    except Exception as e:
        # Любая неудача рукопожатия — одна ошибка; отката на token нет.
        code = _close_code_of(e) or getattr(ws, "close_code", None)
        await _quiet_close(ws)
        reason = "таймаут" if isinstance(e, asyncio.TimeoutError) else type(e).__name__
        raise SecureHandshakeFailed(reason, code) from e
    return ws, session


async def open_connection(url: str, mode: str | None, *, token: str | None = None,
                          store=None, timeout: float = HANDSHAKE_TIMEOUT_S,
                          connect=None) -> Conn:
    """Открыть соединение по правилам режима (см. docstring модуля)."""
    mode = normalize_mode(mode)
    connect = connect or websockets.connect
    store = _default_store() if store is None else store
    keys = load_keys(store)

    if keys is None:
        if mode == "required":
            raise NotPaired("AGENT_SECURE=required, а устройство не спарено")
        if token is None:
            import config
            token = str(getattr(config, "WS_TOKEN", "") or "")
        ws = await connect(url, **_WS_KWARGS)
        log.info("[transport] transport=ws secure=false (устройство не спарено)")
        return Conn(ws, transport="ws", token=token.strip(), store=store)

    device_id = str(_field(keys, "device_id") or "")
    try:
        priv = key_bytes(_field(keys, "priv"))
        current = key_bytes(_field(keys, "server_pub"))
    except (ValueError, TypeError):
        log.error("[transport] ключи устройства повреждены — нужно спарить заново")
        raise SecureHandshakeFailed("ключи устройства повреждены") from None
    candidates = [(current, False)]
    nxt = _field(keys, "next_server_pub")
    if nxt:
        try:
            nxt_raw = key_bytes(nxt)
            if nxt_raw != current:
                candidates.append((nxt_raw, True))
        except (ValueError, TypeError):
            log.warning("[transport] next_server_pub повреждён — пропущен")

    last: SecureHandshakeFailed | None = None
    for server_pub, is_next in candidates:
        fp = _fp(server_pub)
        try:
            ws, session = await _noise_session(url, priv, server_pub, device_id,
                                               timeout, connect)
        except SecureHandshakeFailed as e:
            log.warning("[transport] transport=noise secure=false device=%s fp=%s "
                        "рукопожатие не прошло: %s", device_id, fp, e)
            last = e
            continue
        if is_next:
            store.promote_next()
            log.info("[transport] ключ сервера сменён на fp=%s (ротация)", fp)
        log.info("[transport] transport=noise secure=true device=%s fp=%s",
                 device_id, fp)
        return Conn(ws, transport="noise", channel=session, store=store,
                    server_fp=fp, device_id=device_id)
    raise last or SecureHandshakeFailed("нет ключа сервера")
