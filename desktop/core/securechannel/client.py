"""Клиент securechannel/1: сеанс IK и спаривание XXpsk3 поверх WebSocket (PROTOCOL.md §3–4).

SecureConnection выглядит для ядра как websocket: send(text), recv(), async for, close(code), плюс
secure, transport, device_id, stats(). Входящие PING отвечаются PONG, REKEY выполняются, CLOSE — закрытие.
"""
import asyncio
import json
import logging
import time

from desktop.core.securechannel.channel import IntegrityError, SecureChannel
from desktop.core.securechannel.frames import FrameError, FrameType, InnerType, decode_frame, encode_frame, encode_inner
from desktop.core.securechannel.keys import fingerprint
from desktop.core.securechannel.noise import HandshakeState, NoiseError

log = logging.getLogger("sakura.secure")

PROLOGUE_SESSION = b"sakura-securechannel/1\x00session"
PROLOGUE_PAIR = b"sakura-securechannel/1\x00pair"
HANDSHAKE_TIMEOUT_S = 8.0  # сервер отвечает сразу или молчит до своего дедлайна 5 с


class SecureError(ConnectionError):
    """Рукопожатие или канал не удались — текст понятен пользователю, без подробностей о ключах."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


CLOSE_TEXT = {
    4400: "сервер не принял защищённый канал (протокол не включён или ошибка формата)",
    4408: "сервер не узнал это устройство — подключите его заново (Настройки → Безопасность)",
    4409: "нарушена целостность канала — соединение разорвано",
    4412: "сервер требует защищённый канал",
    4413: "сообщение слишком большое",
    4429: "слишком много попыток подключения — подождите минуту",
}


class _Closed(Exception):
    pass


async def _recv_frame(ws, timeout: float) -> tuple[FrameType, bytes]:
    try:
        data = await asyncio.wait_for(ws.recv(), timeout)
    except asyncio.TimeoutError:
        raise SecureError("сервер не ответил на рукопожатие", 4408) from None
    except Exception as e:  # ConnectionClosed
        code = getattr(getattr(e, "rcvd", None), "code", None) or getattr(e, "code", None)
        raise SecureError(CLOSE_TEXT.get(code, "соединение закрыто во время рукопожатия"), code) from None
    if isinstance(data, str):
        raise SecureError("сервер ответил текстом — защищённый канал на нём не включён", 4400)
    try:
        return decode_frame(data)
    except FrameError as e:
        raise SecureError(f"неверный кадр рукопожатия: {e}", 4400) from None


class SecureConnection:
    transport = "noise"
    secure = True

    def __init__(self, ws, channel: SecureChannel, device_id: str | None, session: str | None):
        self._ws = ws
        self._ch = channel
        self.device_id = device_id
        self.session = session
        self.remote_address = getattr(ws, "remote_address", None)
        self.transport_obj = getattr(ws, "transport", None)
        self._lock = asyncio.Lock()
        self.on_server_key = None  # ротация ключа сервера (§8.2): сохранить для следующего соединения

    async def send(self, message: str | bytes) -> None:
        async with self._lock:
            for frame in self._ch.seal(message):
                await self._ws.send(frame)

    async def recv(self) -> str:
        while True:
            data = await self._ws.recv()
            if isinstance(data, str):
                await self.close(4400, "текст внутри защищённого соединения")
                raise SecureError("сервер прислал текст внутри защищённого соединения", 4400)
            try:
                items = self._ch.open(data)
            except IntegrityError as e:
                log.warning("[secure] нарушение целостности: %s", e)
                await self._ws.close(4409, "integrity")
                raise SecureError(CLOSE_TEXT[4409], 4409) from None
            for inner, payload in items:
                if inner == InnerType.DATA:
                    text = payload.decode("utf-8")
                    if '"secure_server_key"' in text and self._server_key(text):
                        continue
                    return text
                if inner == InnerType.PING:
                    async with self._lock:
                        await self._ws.send(self._ch._seal_inner(encode_inner(InnerType.PONG, 0, payload)))
                elif inner == InnerType.CLOSE:
                    code = int.from_bytes(payload[:2], "big") if len(payload) >= 2 else 1000
                    await self._ws.close(code, payload[2:].decode("utf-8", "replace"))
                    raise SecureError(CLOSE_TEXT.get(code, "сервер закрыл соединение"), code)

    def _server_key(self, text: str) -> bool:
        try:
            msg = json.loads(text)
        except ValueError:
            return False
        if msg.get("type") != "secure_server_key":
            return False
        from desktop.core.securechannel.pairing import unb64u
        if self.on_server_key and msg.get("pub"):
            self.on_server_key(unb64u(msg["pub"]))
            log.info("[secure] сервер сообщил новый ключ — со следующего соединения")
        return True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return await self.recv()
        except SecureError:
            raise StopAsyncIteration from None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        try:
            async with self._lock:
                await self._ws.send(self._ch.close_frame(code, reason))
        except Exception:  # noqa: BLE001
            pass
        await self._ws.close(code, reason)

    def stats(self) -> dict:
        return {"transport": "noise", "secure": True, "session": self.session, **self._ch.stats()}


async def ik_handshake(ws, device_priv: bytes, server_pub: bytes, device_id: str,
                       timeout: float = HANDSHAKE_TIMEOUT_S, clock=time.time) -> SecureConnection:
    """Сеанс IK: IK_INIT (только идентификация) → IK_RESP (параметры сеанса) → канал."""
    t0 = time.monotonic()
    hs = HandshakeState("IK", True, PROLOGUE_SESSION, s_priv=device_priv, rs=server_pub)
    ident = json.dumps({"v": 1, "device_id": device_id, "ts": clock()}).encode()
    await ws.send(encode_frame(FrameType.IK_INIT, hs.write(ident)))
    ftype, body = await _recv_frame(ws, timeout)
    if ftype != FrameType.IK_RESP:
        raise SecureError("неожиданный ответ сервера на рукопожатие", 4400)
    try:
        params = json.loads(hs.read(body) or b"{}")
    except (NoiseError, ValueError):
        raise SecureError("ответ сервера не прошёл проверку ключа — возможна подмена сервера", 4408) from None
    send, recv = hs.split()
    ch = SecureChannel(send, recv, int(params.get("rekey_messages", 10000)), float(params.get("rekey_seconds", 3600)))
    log.info("[secure] сеанс установлен: transport=noise secure=true сервер %s, %d мс",
             fingerprint(server_pub), int((time.monotonic() - t0) * 1000))
    return SecureConnection(ws, ch, device_id, params.get("session"))


async def xx_pair(ws, device_priv: bytes, psk: bytes, info: dict, expected_server_pub: bytes | None = None,
                  timeout: float = HANDSHAKE_TIMEOUT_S) -> dict:
    """Спаривание XXpsk3. Сервер подлинный только после расшифровки PAIRED (в ключах смешан PSK)."""
    hs = HandshakeState("XXpsk3", True, PROLOGUE_PAIR, s_priv=device_priv, psk=psk)
    await ws.send(encode_frame(FrameType.XX_1, hs.write(b"")))
    ftype, body = await _recv_frame(ws, timeout)
    if ftype != FrameType.XX_2:
        raise SecureError("неожиданный ответ сервера при спаривании", 4400)
    try:
        hs.read(body)
    except NoiseError:
        raise SecureError("ответ сервера при спаривании не прошёл проверку", 4408) from None
    if expected_server_pub is not None and hs.remote_static != expected_server_pub:
        await ws.close(1000, "server key mismatch")
        raise SecureError("ключ сервера не совпал с QR — спаривание остановлено (возможна подмена сервера)")
    await ws.send(encode_frame(FrameType.XX_3, hs.write(json.dumps({"v": 1, **info}).encode())))
    send, recv = hs.split()
    ch = SecureChannel(send, recv)
    try:
        ftype, body = await _recv_frame(ws, timeout)
    except SecureError as e:
        raise SecureError("код спаривания не подошёл или истёк — получите новый в Telegram (/pair)", e.code) from None
    try:
        items = ch.open(encode_frame(ftype, body))
    except IntegrityError:
        raise SecureError("код спаривания не подошёл — ответ сервера не расшифровался") from None
    for inner, data in items:
        if inner == InnerType.PAIRED:
            paired = json.loads(data)
            if paired.get("server_pub") and paired["server_pub"] != _b64u(hs.remote_static):
                raise SecureError("сервер сообщил другой ключ, чем в рукопожатии — спаривание остановлено")
            try:
                await ws.close(1000, "paired")
            except Exception:  # noqa: BLE001
                pass
            return {"device_id": paired.get("device_id"), "server_pub": hs.remote_static,
                    "server_fp": fingerprint(hs.remote_static)}
    raise SecureError("сервер не подтвердил спаривание")


def _b64u(data: bytes) -> str:
    from desktop.core.securechannel.pairing import b64u
    return b64u(data)
