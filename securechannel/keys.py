"""Статический ключ сервера (X25519) и его ротация (PROTOCOL.md §8.2, KEYS.md).

Файл SECURE_DIR/server_keys.json (600): список ключей, первый — текущий.
При ротации новый ключ становится первым, прежний принимается ещё
grace_seconds (retire_after) — клиенты успевают получить новый ключ
сообщением secure_server_key. Приватные ключи в журнал не попадают.
"""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time

from securechannel.handshake import generate_keypair
from securechannel.store import read_json, write_json_600

DEFAULT_GRACE_S = 7 * 24 * 3600


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def fingerprint(pub: bytes) -> str:
    """BLAKE2s(pub)[:8] hex группами по 4 (ФИКС, PROTOCOL.md §8.1)."""
    h = hashlib.blake2s(pub, digest_size=32).hexdigest()[:16]
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


class ServerKeys:
    def __init__(self, path: str, clock=time.time):
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: list[dict] = []

    @classmethod
    def load_or_create(cls, secure_dir: str, clock=time.time) -> ServerKeys:
        ks = cls(os.path.join(secure_dir, "server_keys.json"), clock)
        data = read_json(ks.path, None)
        if data and data.get("keys"):
            ks._keys = data["keys"]
        else:
            ks._keys = [ks._new()]
            ks._save()
        return ks

    def _new(self) -> dict:
        priv, pub = generate_keypair()
        return {"priv": b64(priv), "pub": b64(pub), "created": self._clock(),
                "retire_after": None}

    def _save(self) -> None:
        write_json_600(self.path, {"keys": self._keys})

    @property
    def current(self) -> tuple[bytes, bytes]:
        k = self._keys[0]
        return unb64(k["priv"]), unb64(k["pub"])

    def accepted(self) -> list[tuple[bytes, bytes]]:
        """Ключи, которыми сервер ещё расшифровывает IK_INIT (текущий первым)."""
        now = self._clock()
        out = []
        for k in self._keys:
            if k["retire_after"] is None or k["retire_after"] > now:
                out.append((unb64(k["priv"]), unb64(k["pub"])))
        return out

    def rotate(self, grace_seconds: float = DEFAULT_GRACE_S) -> bytes:
        """Новый текущий ключ; прежние принимаются ещё grace_seconds."""
        with self._lock:
            now = self._clock()
            for k in self._keys:
                if k["retire_after"] is None:
                    k["retire_after"] = now + grace_seconds
            self._keys = [self._new()] + [k for k in self._keys
                                          if k["retire_after"] > now]
            self._save()
            return unb64(self._keys[0]["pub"])

    def retire_after(self, pub: bytes) -> float | None:
        for k in self._keys:
            if unb64(k["pub"]) == pub:
                return k["retire_after"]
        return None
