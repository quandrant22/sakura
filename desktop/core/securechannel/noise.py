"""Noise Protocol Framework (rev 34) для клиента: Noise_IK и Noise_XXpsk3 на 25519, ChaChaPoly, BLAKE2s.

Только примитивы из проверенных библиотек: X25519 и ChaCha20-Poly1305 — PyCA cryptography, BLAKE2s и
HMAC — hashlib/hmac. Здесь — лишь машина состояний Noise (CipherState, SymmetricState, HandshakeState)
по спецификации; совместимость проверяется против noiseprotocol (MIT, им пользуется сервер) — тест
desktop/tests/test_securechannel_interop.py.
"""
import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

DHLEN = 32
HASHLEN = 32
MAX_NONCE = 2**64 - 1
MAX_MESSAGE = 65535


class NoiseError(Exception):
    """Ошибка рукопожатия или расшифровки (без подробностей о ключах)."""


# ── примитивы ──
def generate_keypair() -> tuple[bytes, bytes]:
    priv = X25519PrivateKey.generate()
    return (priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
            priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def public_from_private(priv: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def dh(priv: bytes, pub: bytes) -> bytes:
    try:
        return X25519PrivateKey.from_private_bytes(priv).exchange(X25519PublicKey.from_public_bytes(pub))
    except ValueError as e:  # нулевой общий секрет (малая подгруппа) и т.п.
        raise NoiseError("недопустимый открытый ключ") from e


def _nonce(n: int) -> bytes:
    return b"\x00" * 4 + n.to_bytes(8, "little")


def _hash(data: bytes) -> bytes:
    return hashlib.blake2s(data).digest()


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.blake2s).digest()


def hkdf(ck: bytes, ikm: bytes, n: int) -> list[bytes]:
    temp = _hmac(ck, ikm)
    out, prev = [], b""
    for i in range(1, n + 1):
        prev = _hmac(temp, prev + bytes([i]))
        out.append(prev)
    return out


# ── CipherState ──
class CipherState:
    def __init__(self, key: bytes | None = None):
        self.k = key
        self.n = 0

    def has_key(self) -> bool:
        return self.k is not None

    def encrypt_with_ad(self, ad: bytes, plaintext: bytes) -> bytes:
        if self.k is None:
            return plaintext
        if self.n >= MAX_NONCE:
            raise NoiseError("исчерпан счётчик nonce")
        out = ChaCha20Poly1305(self.k).encrypt(_nonce(self.n), plaintext, ad)
        self.n += 1
        return out

    def decrypt_with_ad(self, ad: bytes, ciphertext: bytes) -> bytes:
        if self.k is None:
            return ciphertext
        if self.n >= MAX_NONCE:
            raise NoiseError("исчерпан счётчик nonce")
        try:
            out = ChaCha20Poly1305(self.k).decrypt(_nonce(self.n), ciphertext, ad)
        except Exception as e:  # InvalidTag
            raise NoiseError("ошибка целостности") from e
        self.n += 1
        return out

    def rekey(self) -> None:
        """REKEY(): k = ENCRYPT(k, 2^64−1, ε, 0^32)[:32]; n не сбрасывается."""
        self.k = ChaCha20Poly1305(self.k).encrypt(_nonce(MAX_NONCE), b"\x00" * 32, b"")[:32]


# ── SymmetricState ──
class SymmetricState:
    def __init__(self, protocol_name: bytes):
        self.h = protocol_name.ljust(HASHLEN, b"\x00") if len(protocol_name) <= HASHLEN else _hash(protocol_name)
        self.ck = self.h
        self.cipher = CipherState()

    def mix_key(self, ikm: bytes) -> None:
        self.ck, temp_k = hkdf(self.ck, ikm, 2)
        self.cipher = CipherState(temp_k[:32])

    def mix_hash(self, data: bytes) -> None:
        self.h = _hash(self.h + data)

    def mix_key_and_hash(self, ikm: bytes) -> None:
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
        k1, k2 = hkdf(self.ck, b"", 2)
        return CipherState(k1[:32]), CipherState(k2[:32])


# ── шаблоны рукопожатий ──
PATTERNS = {
    # (предварительные сообщения ответчика, сообщения)
    "IK": (["s"], [["e", "es", "s", "ss"], ["e", "ee", "se"]]),
    "XXpsk3": ([], [["e"], ["e", "ee", "s", "es"], ["s", "se", "psk"]]),
}


class HandshakeState:
    """Рукопожатие Noise. initiator=True — клиент. Методы write/read поочерёдно, затем split()."""

    def __init__(self, pattern: str, initiator: bool, prologue: bytes, s_priv: bytes | None = None,
                 rs: bytes | None = None, psk: bytes | None = None, e_priv: bytes | None = None):
        if pattern not in PATTERNS:
            raise ValueError(f"неизвестный шаблон {pattern}")
        self.pattern = pattern
        self.initiator = initiator
        self.psk = psk
        self.psk_mode = "psk" in pattern
        if self.psk_mode and (psk is None or len(psk) != 32):
            raise ValueError("нужен psk 32 байта")
        self.s = (s_priv, public_from_private(s_priv)) if s_priv else None
        self._fixed_e = e_priv  # только для тестовых векторов
        self.e: tuple[bytes, bytes] | None = None
        self.rs = rs
        self.re: bytes | None = None
        name = f"Noise_{pattern}_25519_ChaChaPoly_BLAKE2s".encode()
        self.ss = SymmetricState(name)
        self.ss.mix_hash(prologue)
        pre, self.messages = PATTERNS[pattern]
        for tok in pre:  # пред-сообщение ответчика: его статический ключ известен заранее
            if tok == "s":
                key = self.s[1] if not initiator else rs
                if key is None:
                    raise ValueError("IK: инициатору нужен открытый ключ ответчика")
                self.ss.mix_hash(key)
        self.step = 0

    @property
    def complete(self) -> bool:
        return self.step >= len(self.messages)

    @property
    def handshake_hash(self) -> bytes:
        return self.ss.h

    @property
    def remote_static(self) -> bytes | None:
        return self.rs

    def _my_turn(self) -> bool:
        return (self.step % 2 == 0) == self.initiator

    def _dh_for(self, tok: str) -> bytes:
        i = self.initiator
        if tok == "ee":
            return dh(self.e[0], self.re)
        if tok == "ss":
            return dh(self.s[0], self.rs)
        if tok == "es":
            return dh(self.e[0], self.rs) if i else dh(self.s[0], self.re)
        if tok == "se":
            return dh(self.s[0], self.re) if i else dh(self.e[0], self.rs)
        raise ValueError(tok)

    def write(self, payload: bytes = b"") -> bytes:
        if self.complete or not self._my_turn():
            raise NoiseError("не наша очередь писать")
        buf = b""
        for tok in self.messages[self.step]:
            if tok == "e":
                if self._fixed_e:
                    self.e = (self._fixed_e, public_from_private(self._fixed_e))
                else:
                    self.e = generate_keypair()
                buf += self.e[1]
                self.ss.mix_hash(self.e[1])
                if self.psk_mode:
                    self.ss.mix_key(self.e[1])
            elif tok == "s":
                buf += self.ss.encrypt_and_hash(self.s[1])
            elif tok == "psk":
                self.ss.mix_key_and_hash(self.psk)
            else:
                self.ss.mix_key(self._dh_for(tok))
        buf += self.ss.encrypt_and_hash(payload)
        if len(buf) > MAX_MESSAGE:
            raise NoiseError("сообщение рукопожатия слишком велико")
        self.step += 1
        return buf

    def read(self, message: bytes) -> bytes:
        if self.complete or self._my_turn():
            raise NoiseError("не наша очередь читать")
        buf = memoryview(message)
        pos = 0
        for tok in self.messages[self.step]:
            if tok == "e":
                if len(buf) - pos < DHLEN:
                    raise NoiseError("короткое сообщение")
                self.re = bytes(buf[pos:pos + DHLEN])
                pos += DHLEN
                self.ss.mix_hash(self.re)
                if self.psk_mode:
                    self.ss.mix_key(self.re)
            elif tok == "s":
                n = DHLEN + (16 if self.ss.cipher.has_key() else 0)
                if len(buf) - pos < n:
                    raise NoiseError("короткое сообщение")
                self.rs = self.ss.decrypt_and_hash(bytes(buf[pos:pos + n]))
                pos += n
            elif tok == "psk":
                self.ss.mix_key_and_hash(self.psk)
            else:
                self.ss.mix_key(self._dh_for(tok))
        payload = self.ss.decrypt_and_hash(bytes(buf[pos:]))
        self.step += 1
        return payload

    def split(self) -> tuple[CipherState, CipherState]:
        """(send, recv) для своей стороны."""
        if not self.complete:
            raise NoiseError("рукопожатие не завершено")
        c1, c2 = self.ss.split()
        return (c1, c2) if self.initiator else (c2, c1)
