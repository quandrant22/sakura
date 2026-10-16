"""Кадры securechannel/1 (docs/security/PROTOCOL.md §2, §4).

Внешний кадр — одно бинарное WebSocket-сообщение:
    "SK" | ver u8 | type u8 | length u32 BE | body
Внутренний заголовок — первые 2 байта расшифрованного TRANSPORT:
    inner u8 | flags u8 | data
Сообщение приложения длиннее одного куска режется на куски с флагом MORE.

Парсер строгий: любое отклонение — FrameError (сервер закрывает 4400/4413).
"""

from __future__ import annotations

import struct
from enum import IntEnum

MAGIC = b"SK"
VERSION = 1
HEADER = struct.Struct(">2sBBI")      # magic, ver, type, length
HEADER_LEN = HEADER.size              # 8
MAX_BODY = 65535                      # максимум сообщения Noise
TAG_LEN = 16                          # Poly1305
INNER_LEN = 2
MAX_CHUNK = MAX_BODY - TAG_LEN - INNER_LEN    # 65517
MAX_MESSAGE = 2 * 1024 * 1024                 # 2 МиБ
MAX_FRAGMENTS = 64
FLAG_MORE = 0x01


class FrameType(IntEnum):
    IK_INIT = 0x01
    IK_RESP = 0x02
    XX_1 = 0x11
    XX_2 = 0x12
    XX_3 = 0x13
    TRANSPORT = 0x20


class InnerType(IntEnum):
    DATA = 0x01
    REKEY = 0x02
    CLOSE = 0x03
    PING = 0x04
    PONG = 0x05
    PAIRED = 0x06


class FrameError(ValueError):
    """Нарушение формата кадра."""


class TooLarge(FrameError):
    """Сообщение длиннее 2 МиБ или больше 64 кусков (закрытие 4413)."""


def is_secure_frame(data) -> bool:
    """Первое WebSocket-сообщение — кадр Noise (а не JSON старого протокола)?"""
    return isinstance(data, (bytes, bytearray, memoryview)) and bytes(data[:2]) == MAGIC


def encode_frame(ftype: FrameType | int, body: bytes) -> bytes:
    ftype = FrameType(ftype)
    if len(body) > MAX_BODY:
        raise FrameError(f"тело кадра {len(body)} > {MAX_BODY}")
    return HEADER.pack(MAGIC, VERSION, int(ftype), len(body)) + bytes(body)


def decode_frame(data: bytes) -> tuple[FrameType, bytes]:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise FrameError("кадр должен быть бинарным")
    data = bytes(data)
    if len(data) < HEADER_LEN:
        raise FrameError("короче заголовка")
    magic, ver, ftype, length = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise FrameError("неверная магия")
    if ver != VERSION:
        raise FrameError(f"версия {ver} не поддерживается")
    try:
        ftype = FrameType(ftype)
    except ValueError:
        raise FrameError(f"неизвестный тип {ftype:#x}") from None
    if length > MAX_BODY:
        raise FrameError("длина больше максимума")
    if length != len(data) - HEADER_LEN:
        raise FrameError("длина не совпадает с телом")
    return ftype, data[HEADER_LEN:]


def encode_inner(inner: InnerType | int, flags: int, data: bytes = b"") -> bytes:
    inner = InnerType(inner)
    if flags & ~FLAG_MORE:
        raise FrameError("неизвестные флаги")
    if flags and inner != InnerType.DATA:
        raise FrameError("MORE только у DATA")
    if len(data) > MAX_CHUNK:
        raise FrameError("кусок больше MAX_CHUNK")
    return bytes((int(inner), flags)) + bytes(data)


def decode_inner(plain: bytes) -> tuple[InnerType, int, bytes]:
    if len(plain) < INNER_LEN:
        raise FrameError("короче внутреннего заголовка")
    try:
        inner = InnerType(plain[0])
    except ValueError:
        raise FrameError(f"неизвестный внутренний тип {plain[0]:#x}") from None
    flags = plain[1]
    if flags & ~FLAG_MORE or (flags and inner != InnerType.DATA):
        raise FrameError("недопустимые флаги")
    return inner, flags, plain[INNER_LEN:]


def fragment(message: bytes) -> list[tuple[int, bytes]]:
    """Сообщение → [(flags, кусок)]; у всех, кроме последнего, FLAG_MORE."""
    if len(message) > MAX_MESSAGE:
        raise TooLarge(f"сообщение {len(message)} > {MAX_MESSAGE}")
    chunks = [message[i:i + MAX_CHUNK] for i in range(0, len(message), MAX_CHUNK)] or [b""]
    if len(chunks) > MAX_FRAGMENTS:
        raise TooLarge("больше 64 кусков")
    return [(FLAG_MORE if i < len(chunks) - 1 else 0, c) for i, c in enumerate(chunks)]


class Reassembler:
    """Сборка кусков DATA в сообщение; лимиты проверяются на каждом куске."""

    def __init__(self, max_message: int = MAX_MESSAGE, max_fragments: int = MAX_FRAGMENTS):
        self.max_message = max_message
        self.max_fragments = max_fragments
        self._parts: list[bytes] = []
        self._size = 0

    @property
    def pending(self) -> bool:
        return bool(self._parts)

    def feed(self, flags: int, data: bytes) -> bytes | None:
        self._parts.append(bytes(data))
        self._size += len(data)
        if self._size > self.max_message:
            raise TooLarge("сообщение больше 2 МиБ")
        if len(self._parts) > self.max_fragments:
            raise TooLarge("больше 64 кусков")
        if flags & FLAG_MORE:
            return None
        msg = b"".join(self._parts)
        self._parts, self._size = [], 0
        return msg
