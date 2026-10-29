"""Фейк core.secure_store (пишет параллельная задача) — тот же API и формат.

    load() -> DeviceKeys | None, save(keys), set_next_server_pub(pub),
    promote_next(), wipe()

Формат device.json: {"v":1,"device_id","priv","pub","server_url","server_pub",
"server_fp","paired_at","next_server_pub"}; ключи — base64.
"""

from __future__ import annotations

import base64
import dataclasses
import time
from dataclasses import dataclass


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@dataclass
class DeviceKeys:
    device_id: str
    priv: str
    pub: str
    server_url: str
    server_pub: str
    server_fp: str
    paired_at: float
    next_server_pub: str | None = None
    v: int = 1


class FakeSecureStore:
    def __init__(self, keys: DeviceKeys | None = None):
        self.keys = keys
        self.calls: list[str] = []

    @classmethod
    def paired(cls, device_id: str, priv: bytes, pub: bytes, server_pub: bytes,
               server_url: str = "ws://127.0.0.1", next_server_pub: str | None = None):
        from securechannel.keys import fingerprint
        return cls(DeviceKeys(device_id=device_id, priv=b64(priv), pub=b64(pub),
                              server_url=server_url, server_pub=b64(server_pub),
                              server_fp=fingerprint(server_pub), paired_at=time.time(),
                              next_server_pub=next_server_pub))

    def load(self) -> DeviceKeys | None:
        self.calls.append("load")
        return None if self.keys is None else dataclasses.replace(self.keys)

    def save(self, keys: DeviceKeys) -> None:
        self.calls.append("save")
        self.keys = dataclasses.replace(keys)

    def set_next_server_pub(self, pub: str) -> None:
        self.calls.append("set_next_server_pub")
        self.keys.next_server_pub = pub

    def promote_next(self) -> None:
        self.calls.append("promote_next")
        from core.transport import key_bytes

        from securechannel.keys import fingerprint

        raw = key_bytes(self.keys.next_server_pub)
        self.keys.server_pub = b64(raw)
        self.keys.server_fp = fingerprint(raw)
        self.keys.next_server_pub = None

    def wipe(self) -> None:
        self.calls.append("wipe")
        self.keys = None
