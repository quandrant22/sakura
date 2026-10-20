"""Транспорт securechannel/1 после рукопожатия (PROTOCOL.md §4).

SecureChannel держит два шифра Noise (исходящий и входящий) и:
  * режет сообщение приложения на куски ≤ 65517 байт с флагом MORE;
  * шифрует каждый кусок вместе с внутренним заголовком (тип и флаги
    защищены AEAD — менять их на пути нельзя);
  * собирает куски на приёме, проверяя лимиты 2 МиБ и 64 куска;
  * делает rekey своего направления по счётчику и по времени: сначала
    отправляет REKEY на старом ключе, затем меняет ключ (получатель меняет
    свой, расшифровав REKEY);
  * любая ошибка расшифровки — IntegrityError: повтор, пропуск,
    перестановка или подмена кадра (счётчик nonce строго последовательный).
"""

from __future__ import annotations

import struct
import time
from typing import Callable

from securechannel.frames import (
    FrameError,
    FrameType,
    InnerType,
    Reassembler,
    decode_frame,
    decode_inner,
    encode_frame,
    encode_inner,
    fragment,
)
from securechannel.handshake import Cipher, IntegrityError

REKEY_MESSAGES = 10_000
REKEY_SECONDS = 3600.0


class SecureChannel:
    def __init__(self, send: Cipher, recv: Cipher, *,
                 rekey_messages: int = REKEY_MESSAGES,
                 rekey_seconds: float = REKEY_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self._send, self._recv = send, recv
        self.rekey_messages = max(1, int(rekey_messages))
        self.rekey_seconds = float(rekey_seconds)
        self._clock = clock
        self._sent_since_rekey = 0
        self._rekeyed_at = clock()
        self._reassembler = Reassembler()
        self.sent_frames = 0
        self.received_frames = 0
        self.rekeys_sent = 0
        self.rekeys_received = 0

    # ── отправка ──────────────────────────────────────────────────────

    def _frame(self, inner: InnerType, flags: int, data: bytes) -> bytes:
        ct = self._send.encrypt(encode_inner(inner, flags, data))
        self.sent_frames += 1
        self._sent_since_rekey += 1
        return encode_frame(FrameType.TRANSPORT, ct)

    def _maybe_rekey(self) -> list[bytes]:
        due = (self._sent_since_rekey >= self.rekey_messages
               or self._clock() - self._rekeyed_at >= self.rekey_seconds)
        if not due:
            return []
        frame = self._frame(InnerType.REKEY, 0, b"")     # на старом ключе
        self._send.rekey()
        self.rekeys_sent += 1
        self._sent_since_rekey = 0
        self._rekeyed_at = self._clock()
        return [frame]

    def seal(self, message: bytes) -> list[bytes]:
        """Сообщение приложения (UTF-8 JSON) → кадры TRANSPORT."""
        out: list[bytes] = []
        for flags, chunk in fragment(bytes(message)):
            out += self._maybe_rekey()
            out.append(self._frame(InnerType.DATA, flags, chunk))
        return out

    def control(self, inner: InnerType, data: bytes = b"") -> list[bytes]:
        """Служебный кадр: PING, PONG, PAIRED."""
        return self._maybe_rekey() + [self._frame(inner, 0, data)]

    def close_frame(self, code: int, reason: str = "") -> bytes:
        return self._frame(InnerType.CLOSE, 0,
                           struct.pack(">H", code) + reason.encode("utf-8")[:120])

    # ── приём ─────────────────────────────────────────────────────────

    def open(self, frame: bytes) -> list[tuple[InnerType, bytes]]:
        """Кадр → события [(тип, данные)]: DATA — целое сообщение;
        REKEY обрабатывается внутри и событий не даёт."""
        ftype, body = decode_frame(frame)
        if ftype != FrameType.TRANSPORT:
            raise FrameError(f"после рукопожатия ожидался TRANSPORT, пришёл {ftype.name}")
        plain = self._recv.decrypt(body)          # IntegrityError при любой подмене
        self.received_frames += 1
        inner, flags, data = decode_inner(plain)
        if inner == InnerType.DATA:
            msg = self._reassembler.feed(flags, data)
            return [] if msg is None else [(InnerType.DATA, msg)]
        if self._reassembler.pending and inner not in (InnerType.PING, InnerType.PONG,
                                                      InnerType.REKEY):
            raise FrameError("служебный кадр посреди сообщения")
        if inner == InnerType.REKEY:
            self._recv.rekey()
            self.rekeys_received += 1
            return []
        return [(inner, data)]


def parse_close(data: bytes) -> tuple[int, str]:
    if len(data) < 2:
        raise FrameError("CLOSE без кода")
    return struct.unpack(">H", data[:2])[0], data[2:].decode("utf-8", "replace")


__all__ = ["SecureChannel", "IntegrityError", "parse_close", "REKEY_MESSAGES", "REKEY_SECONDS"]
