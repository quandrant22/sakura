"""Реестр устройств (PROTOCOL.md §8.3): кто может открыть сеанс IK.

Файл SECURE_DIR/devices.json (600). Запись: id, name, kind, pub, fp,
created, last_seen, revoked. Отозванный ключ для рукопожатия — то же, что
неизвестный (ответа нет, закрытие по дедлайну).
"""

from __future__ import annotations

import os
import re
import threading
import time

from securechannel.keys import b64, fingerprint, unb64
from securechannel.store import read_json, write_json_600

_ID_SAFE = re.compile(r"[^a-z0-9_-]+")
LAST_SEEN_EVERY_S = 60.0       # не писать файл на каждое соединение


class DeviceRegistry:
    def __init__(self, path: str, clock=time.time):
        self.path = path
        self._clock = clock
        self._lock = threading.RLock()
        data = read_json(path, {"devices": []})
        self._devices: list[dict] = list(data.get("devices") or [])

    @classmethod
    def open(cls, secure_dir: str, clock=time.time) -> DeviceRegistry:
        return cls(os.path.join(secure_dir, "devices.json"), clock)

    def _save(self) -> None:
        write_json_600(self.path, {"devices": self._devices})

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(d) for d in self._devices]

    def get(self, device_id: str) -> dict | None:
        with self._lock:
            return next((dict(d) for d in self._devices if d["id"] == device_id), None)

    def by_pub(self, pub: bytes) -> dict | None:
        """Активное (не отозванное) устройство с этим ключом."""
        key = b64(pub)
        with self._lock:
            for d in self._devices:
                if d["pub"] == key and not d.get("revoked"):
                    return dict(d)
        return None

    def _free_id(self, hint: str) -> str:
        base = _ID_SAFE.sub("", (hint or "").lower())[:32] or "device"
        taken = {d["id"] for d in self._devices}
        if base not in taken:
            return base
        i = 2
        while f"{base}{i}" in taken:
            i += 1
        return f"{base}{i}"

    def add(self, pub: bytes, *, name: str, kind: str = "pc", id_hint: str = "") -> dict:
        """Новое устройство (после спаривания). Повтор того же ключа —
        прежняя запись (снимается отзыв не делается: отозванный ключ не
        возвращается спариванием — нужна новая пара ключей)."""
        with self._lock:
            key = b64(pub)
            for d in self._devices:
                if d["pub"] == key:
                    return dict(d)
            dev = {"id": self._free_id(id_hint or name), "name": (name or "устройство")[:40],
                   "kind": kind if kind in ("pc", "phone", "tablet", "headphones", "other") else "other",
                   "pub": key, "fp": fingerprint(pub), "created": self._clock(),
                   "last_seen": None, "revoked": None}
            self._devices.append(dev)
            self._save()
            return dict(dev)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            for d in self._devices:
                if d["id"] == device_id and not d.get("revoked"):
                    d["revoked"] = self._clock()
                    self._save()
                    return True
        return False

    def touch(self, device_id: str) -> None:
        with self._lock:
            for d in self._devices:
                if d["id"] == device_id:
                    now = self._clock()
                    if d.get("last_seen") is None or now - d["last_seen"] >= LAST_SEEN_EVERY_S:
                        d["last_seen"] = now
                        self._save()
                    return

    @staticmethod
    def pub_of(device: dict) -> bytes:
        return unb64(device["pub"])
