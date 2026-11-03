"""Зашифрованный канал после рукопожатия (PROTOCOL.md §4): seal/open кадров TRANSPORT, rekey, ping, close.

Получатель расшифровывает строго следующим nonce: повтор, пропуск, перестановка или подмена кадра →
IntegrityError (закрытие 4409) без попыток восстановления.
"""
import struct
import time

from desktop.core.securechannel.frames import (
    FrameError,
    FrameType,
    InnerType,
    Reassembler,
    TooLarge,
    decode_frame,
    decode_inner,
    encode_frame,
    encode_inner,
    fragment,
)
from desktop.core.securechannel.noise import CipherState, NoiseError

__all__ = ["SecureChannel", "IntegrityError", "TooLarge"]


class IntegrityError(Exception):
    """Кадр не расшифровался (подмена, повтор, перестановка) → 4409."""


class SecureChannel:
    def __init__(self, send: CipherState, recv: CipherState, rekey_messages: int = 10000,
                 rekey_seconds: float = 3600.0, clock=time.monotonic):
        self._send, self._recv = send, recv
        self.rekey_messages, self.rekey_seconds = rekey_messages, rekey_seconds
        self._clock = clock
        self._sent_since = 0
        self._rekey_at = clock()
        self._asm = Reassembler()
        self.started = clock()
        self.rekeys_out = 0
        self.rekeys_in = 0
        self.frames_out = 0
        self.frames_in = 0

    # ── отправка ──
    def _seal_inner(self, inner_plain: bytes) -> bytes:
        self.frames_out += 1
        return encode_frame(FrameType.TRANSPORT, self._send.encrypt_with_ad(b"", inner_plain))

    def _maybe_rekey(self) -> list[bytes]:
        due = self._sent_since >= self.rekey_messages or self._clock() - self._rekey_at >= self.rekey_seconds
        if not due:
            return []
        frame = self._seal_inner(encode_inner(InnerType.REKEY, 0, b""))  # REKEY — на старом ключе
        self._send.rekey()
        self._sent_since = 0
        self._rekey_at = self._clock()
        self.rekeys_out += 1
        return [frame]

    def seal(self, message: bytes | str) -> list[bytes]:
        """Сообщение приложения → кадры TRANSPORT (с фрагментацией и rekey по лимитам)."""
        data = message.encode("utf-8") if isinstance(message, str) else message
        out: list[bytes] = []
        for chunk in fragment(data):
            out += self._maybe_rekey()
            out.append(self._seal_inner(chunk))
            self._sent_since += 1
        return out

    def ping(self, data: bytes = b"") -> bytes:
        return self._seal_inner(encode_inner(InnerType.PING, 0, data[:32]))

    def close_frame(self, code: int, reason: str = "") -> bytes:
        return self._seal_inner(encode_inner(InnerType.CLOSE, 0, struct.pack(">H", code) + reason.encode()[:120]))

    # ── приём ──
    def open(self, frame: bytes) -> list[tuple[InnerType, bytes]]:
        """Кадр → [(тип, данные)]: DATA — целое сообщение (после сборки), PING отвечается PONG снаружи."""
        try:
            ftype, body = decode_frame(frame)
        except FrameError as e:
            raise IntegrityError(str(e)) from None
        if ftype != FrameType.TRANSPORT:
            raise IntegrityError("после рукопожатия допустимы только кадры TRANSPORT")
        try:
            plain = self._recv.decrypt_with_ad(b"", body)
        except NoiseError:
            raise IntegrityError("кадр не расшифровался (подмена, повтор или перестановка)") from None
        self.frames_in += 1
        inner, flags, data = decode_inner(plain)
        if inner == InnerType.REKEY:
            self._recv.rekey()
            self.rekeys_in += 1
            return []
        if self._asm.in_progress and inner not in (InnerType.DATA, InnerType.PING, InnerType.PONG):
            raise IntegrityError("посторонний кадр посреди сообщения")
        if inner == InnerType.DATA:
            msg = self._asm.feed(flags, data)
            return [] if msg is None else [(InnerType.DATA, msg)]
        return [(inner, data)]

    def stats(self) -> dict:
        return {"age_s": round(self._clock() - self.started, 1), "rekeys": self.rekeys_out + self.rekeys_in,
                "frames_out": self.frames_out, "frames_in": self.frames_in}
