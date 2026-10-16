"""Учебная реализация Noise Protocol Framework (rev. 34) для двух паттернов:
Noise_IK_25519_ChaChaPoly_BLAKE2s и Noise_XXpsk3_25519_ChaChaPoly_BLAKE2s.

Назначение — понятность для курса «Криптографические методы защиты
информации», а не скорость. Собственных криптопримитивов нет:

  * DH       — X25519            (PyCA cryptography)
  * AEAD     — ChaCha20-Poly1305 (PyCA cryptography)
  * HASH     — BLAKE2s, HMAC     (hashlib, hmac стандартной библиотеки)

Структура повторяет спецификацию (https://noiseprotocol.org/noise.html):
CipherState (§5.1) → SymmetricState (§5.2) → HandshakeState (§5.3).
Сверка: официальные тестовые векторы (securechannel/vectors) и
дифференциальные тесты против noiseprotocol (MIT) — tests/test_securechannel_*.
В рабочем коде рукопожатие выполняет библиотека (securechannel.handshake,
backend="lib"); эта реализация — backend="edu".
"""

from __future__ import annotations

import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

DHLEN = 32        # длина открытого ключа X25519
HASHLEN = 32      # BLAKE2s
MAX_NONCE = 2**64 - 1   # зарезервировано для REKEY (§11.3)
EMPTY = b""


class NoiseError(Exception):
    """Ошибка рукопожатия или транспорта (неверный тег, порядок, длина)."""


# ── криптопримитивы (обёртки над библиотеками) ─────────────────────────

class KeyPair:
    """Пара ключей X25519. priv/pub — 32 байта."""

    def __init__(self, priv: bytes):
        self._sk = X25519PrivateKey.from_private_bytes(priv)
        self.priv = priv
        self.pub = self._sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    @classmethod
    def generate(cls) -> KeyPair:
        sk = X25519PrivateKey.generate()
        return cls(sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))

    def dh(self, public: bytes) -> bytes:
        """DH(self, public) — общий секрет 32 байта (§4.1)."""
        try:
            return self._sk.exchange(X25519PublicKey.from_public_bytes(public))
        except ValueError as e:      # нулевой результат (малый порядок) — отказ
            raise NoiseError(f"DH: {e}") from None


def _nonce(n: int) -> bytes:
    """Nonce ChaChaPoly в Noise: 4 нулевых байта ‖ n (64 бита little-endian) (§12.3)."""
    return b"\x00" * 4 + struct.pack("<Q", n)


def aead_encrypt(k: bytes, n: int, ad: bytes, plaintext: bytes) -> bytes:
    return ChaCha20Poly1305(k).encrypt(_nonce(n), plaintext, ad)


def aead_decrypt(k: bytes, n: int, ad: bytes, ciphertext: bytes) -> bytes:
    try:
        return ChaCha20Poly1305(k).decrypt(_nonce(n), ciphertext, ad)
    except Exception:        # InvalidTag: подмена, не тот ключ, не тот nonce
        raise NoiseError("AEAD: неверный тег") from None


def hash_(data: bytes) -> bytes:
    return hashlib.blake2s(data).digest()


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.blake2s).digest()


def hkdf(chaining_key: bytes, input_key_material: bytes, num_outputs: int):
    """HKDF Noise (§4.3): HMAC-BLAKE2s, 2 или 3 выхода по 32 байта."""
    temp_key = _hmac(chaining_key, input_key_material)
    out1 = _hmac(temp_key, b"\x01")
    out2 = _hmac(temp_key, out1 + b"\x02")
    if num_outputs == 2:
        return out1, out2
    out3 = _hmac(temp_key, out2 + b"\x03")
    return out1, out2, out3


# ── §5.1 CipherState ───────────────────────────────────────────────────

class CipherState:
    """Ключ k и счётчик n одного направления.

    Счётчик строго растёт: получатель расшифровывает только следующим n,
    поэтому повтор, пропуск и перестановка сообщения дают ошибку тега."""

    def __init__(self, k: bytes | None = None):
        self.k = k
        self.n = 0

    def has_key(self) -> bool:
        return self.k is not None

    def encrypt_with_ad(self, ad: bytes, plaintext: bytes) -> bytes:
        if self.k is None:
            return plaintext
        if self.n >= MAX_NONCE:
            raise NoiseError("исчерпан счётчик nonce")
        c = aead_encrypt(self.k, self.n, ad, plaintext)
        self.n += 1
        return c

    def decrypt_with_ad(self, ad: bytes, ciphertext: bytes) -> bytes:
        if self.k is None:
            return ciphertext
        if self.n >= MAX_NONCE:
            raise NoiseError("исчерпан счётчик nonce")
        p = aead_decrypt(self.k, self.n, ad, ciphertext)
        self.n += 1          # только после успешной расшифровки
        return p

    def rekey(self) -> None:
        """REKEY (§11.3): k = ENCRYPT(k, 2^64−1, ε, 0^32)[:32]; n не сбрасывается."""
        if self.k is None:
            raise NoiseError("rekey без ключа")
        self.k = aead_encrypt(self.k, MAX_NONCE, EMPTY, b"\x00" * 32)[:32]


# ── §5.2 SymmetricState ────────────────────────────────────────────────

class SymmetricState:
    """Цепной ключ ck и хеш рукопожатия h (транскрипт)."""

    def __init__(self, protocol_name: bytes):
        if len(protocol_name) <= HASHLEN:
            self.h = protocol_name.ljust(HASHLEN, b"\x00")
        else:
            self.h = hash_(protocol_name)
        self.ck = self.h
        self.cipher = CipherState()

    def mix_key(self, ikm: bytes) -> None:
        self.ck, temp_k = hkdf(self.ck, ikm, 2)
        self.cipher = CipherState(temp_k[:32])

    def mix_hash(self, data: bytes) -> None:
        self.h = hash_(self.h + data)

    def mix_key_and_hash(self, ikm: bytes) -> None:
        """Для токена psk (§9)."""
        self.ck, temp_h, temp_k = hkdf(self.ck, ikm, 3)
        self.mix_hash(temp_h)
        self.cipher = CipherState(temp_k[:32])

    def encrypt_and_hash(self, plaintext: bytes) -> bytes:
        c = self.cipher.encrypt_with_ad(self.h, plaintext)
        self.mix_hash(c)
        return c

    def decrypt_and_hash(self, ciphertext: bytes) -> bytes:
        p = self.cipher.decrypt_with_ad(self.h, ciphertext)
        self.mix_hash(ciphertext)
        return p

    def split(self) -> tuple[CipherState, CipherState]:
        k1, k2 = hkdf(self.ck, EMPTY, 2)
        return CipherState(k1[:32]), CipherState(k2[:32])


# ── §5.3 HandshakeState, паттерны §7 ───────────────────────────────────

# Паттерны: пред-сообщения и сообщения как списки токенов.
PATTERNS = {
    "IK": {
        "pre_responder": ["s"],          # <- s : ключ сервера известен заранее
        "messages": [["e", "es", "s", "ss"], ["e", "ee", "se"]],
    },
    "XXpsk3": {
        "pre_responder": [],
        "messages": [["e"], ["e", "ee", "s", "es"], ["s", "se", "psk"]],
    },
}


def protocol_name(pattern: str) -> bytes:
    return f"Noise_{pattern}_25519_ChaChaPoly_BLAKE2s".encode()


class HandshakeState:
    """Рукопожатие одной стороны.

    s, e — свои пары ключей; rs, re — открытые ключи собеседника;
    psk — 32 байта для XXpsk3. Сообщения пишутся и читаются по очереди;
    после последнего — split() даёт два CipherState транспорта."""

    def __init__(self, pattern: str, initiator: bool, prologue: bytes = b"", *,
                 s: KeyPair | None = None, e: KeyPair | None = None,
                 rs: bytes | None = None, psk: bytes | None = None):
        if pattern not in PATTERNS:
            raise NoiseError(f"паттерн не поддержан: {pattern}")
        self.pattern = pattern
        self.initiator = initiator
        self.s, self.e, self.rs, self.re = s, e, rs, None
        self.psk = psk
        self.psk_mode = "psk" in pattern
        if self.psk_mode and (psk is None or len(psk) != 32):
            raise NoiseError("нужен psk 32 байта")
        self.symmetric = SymmetricState(protocol_name(pattern))
        self.symmetric.mix_hash(prologue)
        p = PATTERNS[pattern]
        # Пред-сообщение «<- s»: обе стороны смешивают ключ ответчика.
        for token in p["pre_responder"]:
            assert token == "s"
            key = self.s.pub if not initiator else self.rs
            if key is None:
                raise NoiseError("IK: инициатору нужен ключ ответчика (rs)")
            self.symmetric.mix_hash(key)
        self._messages = [list(m) for m in p["messages"]]
        self._index = 0

    @property
    def complete(self) -> bool:
        return self._index >= len(self._messages)

    def _my_turn(self) -> bool:
        return (self._index % 2 == 0) == self.initiator

    def _dh(self, token: str) -> bytes:
        # es: DH(e инициатора, s ответчика) — с любой стороны вычисляется
        # своей приватной половиной и открытой половиной собеседника.
        a, b = token[0], token[1]
        mine, theirs = (a, b) if self.initiator else (b, a)
        local = self.e if mine == "e" else self.s
        remote = self.re if theirs == "e" else self.rs
        if local is None or remote is None:
            raise NoiseError(f"нет ключей для {token}")
        return local.dh(remote)

    def write_message(self, payload: bytes = b"") -> bytes:
        if self.complete or not self._my_turn():
            raise NoiseError("не наша очередь писать")
        out = bytearray()
        for token in self._messages[self._index]:
            if token == "e":
                if self.e is None:
                    self.e = KeyPair.generate()
                out += self.e.pub
                self.symmetric.mix_hash(self.e.pub)
                if self.psk_mode:
                    self.symmetric.mix_key(self.e.pub)
            elif token == "s":
                out += self.symmetric.encrypt_and_hash(self.s.pub)
            elif token == "psk":
                self.symmetric.mix_key_and_hash(self.psk)
            else:
                self.symmetric.mix_key(self._dh(token))
        out += self.symmetric.encrypt_and_hash(payload)
        self._index += 1
        return bytes(out)

    def read_message(self, message: bytes) -> bytes:
        if self.complete or self._my_turn():
            raise NoiseError("не наша очередь читать")
        buf = memoryview(message)
        for token in self._messages[self._index]:
            if token == "e":
                if len(buf) < DHLEN:
                    raise NoiseError("короткое сообщение (e)")
                self.re = bytes(buf[:DHLEN])
                buf = buf[DHLEN:]
                self.symmetric.mix_hash(self.re)
                if self.psk_mode:
                    self.symmetric.mix_key(self.re)
            elif token == "s":
                n = DHLEN + (16 if self.symmetric.cipher.has_key() else 0)
                if len(buf) < n:
                    raise NoiseError("короткое сообщение (s)")
                self.rs = self.symmetric.decrypt_and_hash(bytes(buf[:n]))
                buf = buf[n:]
            elif token == "psk":
                self.symmetric.mix_key_and_hash(self.psk)
            else:
                self.symmetric.mix_key(self._dh(token))
        payload = self.symmetric.decrypt_and_hash(bytes(buf))
        self._index += 1
        return payload

    def handshake_hash(self) -> bytes:
        return self.symmetric.h

    def split(self) -> tuple[CipherState, CipherState]:
        """(исходящий, входящий) для этой стороны."""
        if not self.complete:
            raise NoiseError("рукопожатие не завершено")
        c1, c2 = self.symmetric.split()
        return (c1, c2) if self.initiator else (c2, c1)
