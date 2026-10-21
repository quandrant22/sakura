"""Серверная сторона securechannel/1: принять соединение Noise.

    conn = await accept(websocket, first_message, ctx)

  * IK_INIT  → сеанс: SecureConnection (для ws_handler — обычный websocket);
  * XX_1     → спаривание: устройство в реестре, кадр PAIRED, закрытие 1000;
               возвращается None;
  * отказ    → ПОЛНОЕ МОЛЧАНИЕ до дедлайна (5 с от первого кадра), затем
               закрытие 4408. Неизвестный, отозванный ключ, битое сообщение,
               неверный PSK неотличимы между собой ни ответом, ни временем.

Журнал без секретов: transport, secure, device_id, отпечаток, исход.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field

from securechannel.channel import REKEY_MESSAGES, REKEY_SECONDS, SecureChannel, parse_close
from securechannel.frames import (
    FrameError,
    FrameType,
    InnerType,
    TooLarge,
    decode_frame,
    encode_frame,
)
from securechannel.handshake import Handshake, HandshakeError, IntegrityError
from securechannel.keys import ServerKeys, b64url, fingerprint
from securechannel.limits import HandshakeLimiter
from securechannel.pairing import PairingManager
from securechannel.registry import DeviceRegistry

log = logging.getLogger("sakura.securechannel")

HANDSHAKE_TIMEOUT_S = 5.0
CLOSE_NORMAL = 1000
CLOSE_PROTOCOL = 4400
CLOSE_HANDSHAKE = 4408
CLOSE_INTEGRITY = 4409
CLOSE_SECURE_REQUIRED = 4412
CLOSE_TOO_LARGE = 4413
CLOSE_RATE_LIMITED = 4429


class SecureChannelClosed(Exception):
    """Соединение закрыто (кодом протокола или собеседником)."""

    def __init__(self, code: int, reason: str = ""):
        super().__init__(f"{code} {reason}")
        self.code = code
        self.reason = reason


@dataclass
class SecureContext:
    keys: ServerKeys
    registry: DeviceRegistry
    pairing: PairingManager
    limiter: HandshakeLimiter = field(default_factory=HandshakeLimiter)
    backend: str = "lib"
    timeout: float = HANDSHAKE_TIMEOUT_S
    rekey_messages: int = REKEY_MESSAGES
    rekey_seconds: float = REKEY_SECONDS
    on_paired: object = None            # async callback(device: dict)
    clock: object = time.monotonic


def _peer_ip(websocket) -> str:
    addr = getattr(websocket, "remote_address", None)
    return str(addr[0]) if isinstance(addr, tuple) and addr else str(addr)


async def _silent_fail(websocket, deadline: float, clock, why: str, ip: str) -> None:
    """Отказ рукопожатия: не отвечать, закрыть ровно в момент дедлайна."""
    log.info(f"[secure] transport=noise secure=false ip={ip} рукопожатие отклонено ({why})")
    delay = deadline - clock()
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await websocket.close(CLOSE_HANDSHAKE, "handshake failed")
    except Exception:
        pass


async def _recv_frame(websocket, deadline: float, clock) -> tuple[FrameType, bytes]:
    remaining = deadline - clock()
    if remaining <= 0:
        raise asyncio.TimeoutError
    raw = await asyncio.wait_for(websocket.recv(), remaining)
    return decode_frame(raw)


async def accept(websocket, first_message: bytes, ctx: SecureContext):
    """Рукопожатие по первому кадру. SecureConnection | None (спаривание/отказ)."""
    clock = ctx.clock
    ip = _peer_ip(websocket)
    deadline = clock() + ctx.timeout
    if not ctx.limiter.try_begin(ip):
        log.warning(f"[secure] transport=noise ip={ip} лимит рукопожатий — 4429")
        try:
            await websocket.close(CLOSE_RATE_LIMITED, "rate limited")
        except Exception:
            pass
        return None
    try:
        try:
            ftype, body = decode_frame(first_message)
        except FrameError:
            await _silent_fail(websocket, deadline, clock, "битый первый кадр", ip)
            return None
        if ftype == FrameType.IK_INIT:
            return await _accept_ik(websocket, body, ctx, deadline, ip)
        if ftype == FrameType.XX_1:
            await _accept_pairing(websocket, body, ctx, deadline, ip)
            return None
        await _silent_fail(websocket, deadline, clock, f"первый кадр {ftype.name}", ip)
        return None
    finally:
        ctx.limiter.end(ip)


async def _accept_ik(websocket, body, ctx: SecureContext, deadline, ip):
    clock = ctx.clock
    hs = payload = None
    used_pub = None
    for priv, pub in ctx.keys.accepted():           # текущий, затем прежние (ротация)
        try:
            cand = Handshake.ik_responder(priv, backend=ctx.backend)
            payload = cand.read(body)
            hs, used_pub = cand, pub
            break
        except HandshakeError:
            continue
    if hs is None:
        await _silent_fail(websocket, deadline, clock, "IK_INIT не расшифровался", ip)
        return None
    device = ctx.registry.by_pub(hs.remote_static)
    if device is None:
        # Неизвестный или отозванный ключ: тот же путь, что битое сообщение.
        await _silent_fail(websocket, deadline, clock,
                           f"ключ {fingerprint(hs.remote_static)} не в реестре", ip)
        return None
    try:
        ident = json.loads(payload or b"{}")
    except ValueError:
        ident = {}
    session = secrets.token_hex(8)
    resp = json.dumps({"v": 1, "session": session, "rekey_messages": ctx.rekey_messages,
                       "rekey_seconds": ctx.rekey_seconds, "server_time": time.time()}).encode()
    try:
        msg2 = hs.write(resp)
        await websocket.send(encode_frame(FrameType.IK_RESP, msg2))
    except Exception as e:
        log.info(f"[secure] ip={ip} ответ IK не отправлен: {type(e).__name__}")
        return None
    send, recv = hs.split()
    channel = SecureChannel(send, recv, rekey_messages=ctx.rekey_messages,
                            rekey_seconds=ctx.rekey_seconds)
    ctx.registry.touch(device["id"])
    claimed = ident.get("device_id") if isinstance(ident, dict) else None
    log.info(f"[secure] transport=noise secure=true ip={ip} device={device['id']} "
             f"fp={device['fp']} session={session}"
             + (f" (заявлен device_id={claimed!r})" if claimed and claimed != device["id"] else ""))
    conn = SecureConnection(websocket, channel, device["id"])
    current_pub = ctx.keys.current[1]
    if used_pub != current_pub:
        # Клиент пришёл со старым ключом сервера — сообщить новый (§8.2).
        await conn.send(json.dumps({
            "type": "secure_server_key", "pub": b64url(current_pub),
            "fp": fingerprint(current_pub), "retire_after": ctx.keys.retire_after(used_pub)}))
    return conn


async def _accept_pairing(websocket, body, ctx: SecureContext, deadline, ip):
    clock = ctx.clock
    psk = ctx.pairing.active_psk()
    if psk is None:
        await _silent_fail(websocket, deadline, clock, "нет активного кода спаривания", ip)
        return
    priv, pub = ctx.keys.current
    hs = Handshake.xx_responder(priv, psk, backend=ctx.backend)
    try:
        hs.read(body)
        await websocket.send(encode_frame(FrameType.XX_2, hs.write(b"")))
        ftype, body3 = await _recv_frame(websocket, deadline, clock)
        if ftype != FrameType.XX_3:
            raise HandshakeError(f"ожидался XX_3, пришёл {ftype.name}")
        info = json.loads(hs.read(body3) or b"{}")
    except (HandshakeError, FrameError, ValueError, asyncio.TimeoutError) as e:
        ctx.pairing.failed(psk)
        await _silent_fail(websocket, deadline, clock, f"спаривание: {type(e).__name__}", ip)
        return
    except Exception as e:
        ctx.pairing.failed(psk)
        log.info(f"[secure] ip={ip} спаривание прервано: {type(e).__name__}")
        return
    if not ctx.pairing.consume(psk):
        await _silent_fail(websocket, deadline, clock, "код уже использован", ip)
        return
    info = info if isinstance(info, dict) else {}
    device = ctx.registry.add(hs.remote_static, name=str(info.get("name") or "устройство"),
                              kind=str(info.get("kind") or "pc"),
                              id_hint=str(info.get("device_id_hint") or ""))
    send, recv = hs.split()
    channel = SecureChannel(send, recv)
    paired = json.dumps({"device_id": device["id"], "server_pub": b64url(pub),
                         "server_fp": fingerprint(pub)}).encode()
    for frame in channel.control(InnerType.PAIRED, paired):
        await websocket.send(frame)
    log.info(f"[secure] transport=noise ip={ip} спарено устройство {device['id']} fp={device['fp']}")
    try:
        await websocket.close(CLOSE_NORMAL, "paired")
    except Exception:
        pass
    if ctx.on_paired is not None:
        try:
            await ctx.on_paired(device)
        except Exception as e:
            log.debug(f"[secure] on_paired: {type(e).__name__}")


class SecureConnection:
    """websocket для ws_handler поверх SecureChannel: recv/send текстом JSON."""

    transport = "noise"
    secure = True

    def __init__(self, websocket, channel: SecureChannel, device_id: str):
        self._ws = websocket
        self._ch = channel
        self.device_id = device_id
        self._send_lock = asyncio.Lock()
        self.close_code: int | None = None
        self.close_reason: str | None = None

    @property
    def remote_address(self):
        return getattr(self._ws, "remote_address", None)

    async def _send_frames(self, make) -> None:
        # Шифрование и отправка под одним замком: порядок счётчиков nonce
        # обязан совпадать с порядком кадров в сокете.
        async with self._send_lock:
            for frame in make():
                await self._ws.send(frame)

    async def send(self, message) -> None:
        if isinstance(message, (bytes, bytearray)):
            message = bytes(message).decode("utf-8")
        data = message.encode("utf-8")
        try:
            await self._send_frames(lambda: self._ch.seal(data))
        except TooLarge:
            raise SecureChannelClosed(CLOSE_TOO_LARGE, "message too large") from None

    async def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        if self.close_code is None:
            self.close_code, self.close_reason = code, reason
            try:
                await self._send_frames(lambda: [self._ch.close_frame(code, reason)])
            except Exception:
                pass
        try:
            await self._ws.close(code, reason)
        except Exception:
            pass

    async def _fail(self, code: int, reason: str):
        log.warning(f"[secure] transport=noise device={self.device_id} закрытие {code}: {reason}")
        self.close_code, self.close_reason = code, reason
        try:
            await self._ws.close(code, reason)
        except Exception:
            pass
        raise SecureChannelClosed(code, reason)

    async def recv(self) -> str:
        while True:
            raw = await self._ws.recv()
            if isinstance(raw, str):
                await self._fail(CLOSE_PROTOCOL, "text frame on secure channel")
            try:
                events = self._ch.open(raw)
            except IntegrityError:
                await self._fail(CLOSE_INTEGRITY, "integrity")
            except TooLarge:
                await self._fail(CLOSE_TOO_LARGE, "too large")
            except FrameError:
                await self._fail(CLOSE_PROTOCOL, "bad frame")
            for inner, data in events:
                if inner == InnerType.DATA:
                    try:
                        return data.decode("utf-8")
                    except UnicodeDecodeError:
                        await self._fail(CLOSE_PROTOCOL, "not utf-8")
                if inner == InnerType.PING:
                    await self._send_frames(lambda: self._ch.control(InnerType.PONG, data[:32]))
                elif inner == InnerType.CLOSE:
                    code, reason = parse_close(data)
                    self.close_code, self.close_reason = code, reason
                    try:
                        await self._ws.close(CLOSE_NORMAL, "bye")
                    except Exception:
                        pass
                    raise SecureChannelClosed(code, reason)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return await self.recv()
        except SecureChannelClosed:
            raise StopAsyncIteration from None
        except Exception as e:
            if type(e).__name__.startswith("ConnectionClosed"):
                raise StopAsyncIteration from None
            raise
