"""Кадры securechannel/1 (PROTOCOL.md §2, §4.1–4.2): внешний кадр «SK», внутренний заголовок, фрагментация."""
import enum
import struct

MAGIC = b"SK"
VERSION = 0x01
MAX_BODY = 65535
MAX_CHUNK = 65535 - 16 - 2  # тег AEAD 16 + внутренний заголовок 2
MAX_MESSAGE = 2 * 1024 * 1024
MAX_FRAGMENTS = 64
FLAG_MORE = 0x01
_HDR = struct.Struct(">2sBBI")


class FrameType(enum.IntEnum):
    IK_INIT = 0x01
    IK_RESP = 0x02
    XX_1 = 0x11
    XX_2 = 0x12
    XX_3 = 0x13
    TRANSPORT = 0x20


class InnerType(enum.IntEnum):
    DATA = 0x01
    REKEY = 0x02
    CLOSE = 0x03
    PING = 0x04
    PONG = 0x05
    PAIRED = 0x06


class FrameError(ValueError):
    """Нарушение формата кадра (→ 4400)."""


class TooLarge(FrameError):
    """Сообщение больше 2 МиБ или больше 64 кусков (→ 4413)."""


def encode_frame(ftype: int, body: bytes) -> bytes:
    if len(body) > MAX_BODY:
        raise FrameError("тело кадра больше 65535 байт")
    return _HDR.pack(MAGIC, VERSION, int(ftype), len(body)) + body


def decode_frame(data: bytes) -> tuple[FrameType, bytes]:
    if len(data) < _HDR.size:
        raise FrameError("короткий кадр")
    magic, ver, ftype, length = _HDR.unpack_from(data)
    if magic != MAGIC or ver != VERSION:
        raise FrameError("не кадр securechannel/1")
    body = data[_HDR.size:]
    if length != len(body) or length > MAX_BODY:
        raise FrameError("длина кадра не совпадает")
    try:
        return FrameType(ftype), bytes(body)
    except ValueError:
        raise FrameError("неизвестный тип кадра") from None


def encode_inner(inner: int, flags: int, data: bytes) -> bytes:
    return bytes([int(inner), flags & 0xFF]) + data


def decode_inner(plain: bytes) -> tuple[InnerType, int, bytes]:
    if len(plain) < 2:
        raise FrameError("короткий внутренний заголовок")
    try:
        inner = InnerType(plain[0])
    except ValueError:
        raise FrameError("неизвестный внутренний тип") from None
    if plain[1] & ~FLAG_MORE:
        raise FrameError("неизвестные флаги")
    return inner, plain[1], plain[2:]


def fragment(message: bytes) -> list[bytes]:
    """Куски DATA (без шифрования): каждый ≤ MAX_CHUNK; у всех, кроме последнего, флаг MORE."""
    if len(message) > MAX_MESSAGE:
        raise TooLarge("сообщение больше 2 МиБ")
    chunks = [message[i:i + MAX_CHUNK] for i in range(0, len(message), MAX_CHUNK)] or [b""]
    if len(chunks) > MAX_FRAGMENTS:
        raise TooLarge("больше 64 кусков")
    return [encode_inner(InnerType.DATA, FLAG_MORE if i < len(chunks) - 1 else 0, c) for i, c in enumerate(chunks)]


class Reassembler:
    """Сборка DATA-кусков в сообщение; лимиты 2 МиБ и 64 куска."""

    def __init__(self):
        self._parts: list[bytes] = []
        self._size = 0

    def feed(self, flags: int, data: bytes) -> bytes | None:
        self._parts.append(data)
        self._size += len(data)
        if self._size > MAX_MESSAGE or len(self._parts) > MAX_FRAGMENTS:
            self._parts, self._size = [], 0
            raise TooLarge("сообщение больше лимита")
        if flags & FLAG_MORE:
            return None
        out = b"".join(self._parts)
        self._parts, self._size = [], 0
        return out

    @property
    def in_progress(self) -> bool:
        return bool(self._parts)
