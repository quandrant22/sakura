"""Рукопожатия securechannel/1: IK (сеанс) и XXpsk3 (спаривание).

Единый интерфейс над двумя движками:

  backend="lib" — noiseprotocol (MIT, https://pypi.org/project/noiseprotocol/):
                  проверенная библиотека, используется в работе;
  backend="edu" — учебная реализация securechannel.noise (сверена с
                  официальными векторами и с библиотекой).

    hs = Handshake.ik_initiator(client_priv, server_pub)
    m1 = hs.write(payload)        # → кадр IK_INIT
    p2 = hs.read(m2)              # ← IK_RESP
    send, recv = hs.split()       # Cipher для транспорта

Ключ собеседника (remote_static) доступен сразу после чтения сообщения
с токеном «s» — ответчик IK узнаёт устройство до того, как ответить.
"""

from __future__ import annotations

from securechannel.noise.core import (
    CipherState,
    HandshakeState,
    KeyPair,
    NoiseError,
    protocol_name,
)

PROLOGUE_BASE = b"sakura-securechannel/1\x00"
PROLOGUE_SESSION = PROLOGUE_BASE + b"session"
PROLOGUE_PAIR = PROLOGUE_BASE + b"pair"
DEFAULT_BACKEND = "lib"


class HandshakeError(Exception):
    """Рукопожатие не удалось (подмена, не тот ключ, не тот PSK, порядок)."""


class IntegrityError(Exception):
    """Транспортное сообщение не расшифровалось (подмена, повтор, перестановка)."""


class Cipher:
    """Одно направление транспорта: encrypt/decrypt со счётчиком и rekey."""

    def __init__(self, encrypt, decrypt, rekey):
        self._encrypt, self._decrypt, self._rekey = encrypt, decrypt, rekey

    def encrypt(self, plaintext: bytes) -> bytes:
        return bytes(self._encrypt(plaintext))

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return bytes(self._decrypt(ciphertext))
        except Exception as e:
            raise IntegrityError(type(e).__name__) from None

    def rekey(self) -> None:
        self._rekey()


def _edu_cipher(cs: CipherState) -> Cipher:
    return Cipher(lambda p: cs.encrypt_with_ad(b"", p),
                  lambda c: cs.decrypt_with_ad(b"", c),
                  cs.rekey)


class Handshake:
    """Рукопожатие одной стороны (см. модуль)."""

    def __init__(self, pattern: str, initiator: bool, s_priv: bytes, *,
                 rs_pub: bytes | None = None, psk: bytes | None = None,
                 prologue: bytes, backend: str = DEFAULT_BACKEND,
                 e_priv: bytes | None = None):
        if backend not in ("lib", "edu"):
            raise ValueError(f"backend: {backend}")
        self.pattern, self.initiator, self.backend = pattern, initiator, backend
        self.remote_static: bytes | None = rs_pub if initiator else None
        self._hash: bytes | None = None
        if backend == "edu":
            self._hs = HandshakeState(
                pattern, initiator, prologue, s=KeyPair(s_priv),
                e=KeyPair(e_priv) if e_priv else None, rs=rs_pub, psk=psk)
            return
        from noise.connection import Keypair, NoiseConnection
        conn = NoiseConnection.from_name(protocol_name(pattern))
        conn.set_as_initiator() if initiator else conn.set_as_responder()
        conn.set_keypair_from_private_bytes(Keypair.STATIC, s_priv)
        if rs_pub is not None:
            conn.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC, rs_pub)
        if e_priv is not None:
            conn.set_keypair_from_private_bytes(Keypair.EPHEMERAL, e_priv)
        if psk is not None:
            conn.set_psks(psk)
        conn.set_prologue(prologue)
        conn.start_handshake()
        self._conn = conn
        # На последнем сообщении библиотека сразу стирает handshake_state —
        # ключ собеседника (XX: приходит именно последним) и хеш забираем
        # в момент завершения, до очистки.
        proto = conn.noise_protocol
        done = proto.handshake_done

        def _done_with_capture(*a, **k):
            self._capture()
            return done(*a, **k)
        proto.handshake_done = _done_with_capture

    # ── фабрики ───────────────────────────────────────────────────────

    @classmethod
    def ik_initiator(cls, s_priv: bytes, rs_pub: bytes, **kw) -> Handshake:
        return cls("IK", True, s_priv, rs_pub=rs_pub, prologue=PROLOGUE_SESSION, **kw)

    @classmethod
    def ik_responder(cls, s_priv: bytes, **kw) -> Handshake:
        return cls("IK", False, s_priv, prologue=PROLOGUE_SESSION, **kw)

    @classmethod
    def xx_initiator(cls, s_priv: bytes, psk: bytes, **kw) -> Handshake:
        return cls("XXpsk3", True, s_priv, psk=psk, prologue=PROLOGUE_PAIR, **kw)

    @classmethod
    def xx_responder(cls, s_priv: bytes, psk: bytes, **kw) -> Handshake:
        return cls("XXpsk3", False, s_priv, psk=psk, prologue=PROLOGUE_PAIR, **kw)

    # ── сообщения ─────────────────────────────────────────────────────

    @property
    def complete(self) -> bool:
        if self.backend == "edu":
            return self._hs.complete
        return bool(self._conn.handshake_finished)

    def _capture(self) -> None:
        """Запомнить ключ собеседника и хеш, пока библиотека их не стёрла."""
        if self.backend == "edu":
            if self._hs.rs is not None:
                self.remote_static = self._hs.rs
            self._hash = self._hs.handshake_hash()
            return
        hs = getattr(self._conn.noise_protocol, "handshake_state", None)
        if hs is not None:
            rs = getattr(hs, "rs", None)
            pub = getattr(rs, "public_bytes", None)    # пока ключа нет — заглушка Empty
            if pub:
                self.remote_static = bytes(pub)
            self._hash = bytes(hs.symmetric_state.h)

    def write(self, payload: bytes = b"") -> bytes:
        try:
            out = (self._hs.write_message(payload) if self.backend == "edu"
                   else bytes(self._conn.write_message(payload)))
        except Exception as e:
            raise HandshakeError(f"write: {type(e).__name__}") from None
        self._capture()
        if self.backend == "lib" and self.complete:
            self._hash = bytes(self._conn.get_handshake_hash())
        return out

    def read(self, message: bytes) -> bytes:
        try:
            if self.backend == "edu":
                payload = self._hs.read_message(bytes(message))
            else:
                payload = bytes(self._conn.read_message(bytes(message)))
        except Exception as e:
            raise HandshakeError(f"read: {type(e).__name__}") from None
        self._capture()
        if self.backend == "lib" and self.complete:
            self._hash = bytes(self._conn.get_handshake_hash())
        return payload

    @property
    def handshake_hash(self) -> bytes | None:
        return self._hash

    def split(self) -> tuple[Cipher, Cipher]:
        """(исходящий, входящий) шифр транспорта этой стороны."""
        if not self.complete:
            raise HandshakeError("рукопожатие не завершено")
        if self.backend == "edu":
            out, inc = self._hs.split()
            return _edu_cipher(out), _edu_cipher(inc)
        c = self._conn
        return (Cipher(c.encrypt, lambda x: (_ for _ in ()).throw(RuntimeError("send-only")),
                       c.rekey_outbound_cipher),
                Cipher(lambda x: (_ for _ in ()).throw(RuntimeError("recv-only")), c.decrypt,
                       c.rekey_inbound_cipher))


def generate_keypair() -> tuple[bytes, bytes]:
    """(priv, pub) X25519 — через PyCA cryptography."""
    kp = KeyPair.generate()
    return kp.priv, kp.pub


def public_key(priv: bytes) -> bytes:
    return KeyPair(priv).pub


__all__ = ["Handshake", "HandshakeError", "IntegrityError", "Cipher", "NoiseError",
           "PROLOGUE_SESSION", "PROLOGUE_PAIR", "generate_keypair", "public_key"]
