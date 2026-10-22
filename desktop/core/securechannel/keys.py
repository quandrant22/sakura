"""Ключи устройства (PROTOCOL.md §8): статический ключ X25519 в Windows DPAPI, ключ сервера, отпечатки.

DATA_DIR\\secure\\device_key.dpapi — закрытый ключ, зашифрованный DPAPI (только этот пользователь);
без DPAPI — device_key.bin с правами только текущему пользователю. server.json — открытый ключ сервера,
его отпечаток, device_id из спаривания и адрес. Значения ключей не журналируются.
"""
import hashlib
import json
import logging
import os
import time

from desktop.core.securechannel import noise
from desktop.core.securechannel.pairing import b64u, unb64u

log = logging.getLogger("sakura.secure")


def fingerprint(pub: bytes) -> str:
    """BLAKE2s(pub, 32)[:8] в hex группами по 4: «3f9a 1c02 77de 0b41»."""
    h = hashlib.blake2s(pub, digest_size=32).digest()[:8].hex()
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


def sha256_hex(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()


class KeyStore:
    def __init__(self, folder: str, protect=None, unprotect=None, restrict=None):
        self.folder = folder
        self._protect, self._unprotect, self._restrict = protect, unprotect, restrict
        if protect is None and os.name == "nt":
            from desktop.core.platform import dpapi
            self._protect, self._unprotect = dpapi.protect, dpapi.unprotect

    @property
    def _dpapi_path(self):
        return os.path.join(self.folder, "device_key.dpapi")

    @property
    def _plain_path(self):
        return os.path.join(self.folder, "device_key.bin")

    @property
    def _server_path(self):
        return os.path.join(self.folder, "server.json")

    def _write(self, path: str, data: bytes) -> None:
        os.makedirs(self.folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        if self._restrict:
            try:
                self._restrict(path)
            except Exception as e:  # noqa: BLE001
                log.warning("[secure] не удалось ограничить права на файл ключа: %s", type(e).__name__)

    # ── ключ устройства ──
    def device_private(self) -> bytes | None:
        if os.path.isfile(self._dpapi_path) and self._unprotect:
            return self._unprotect(open(self._dpapi_path, "rb").read())
        if os.path.isfile(self._plain_path):
            return open(self._plain_path, "rb").read()
        return None

    def device_keypair(self, create: bool = True) -> tuple[bytes, bytes] | None:
        priv = self.device_private()
        if priv is None:
            if not create:
                return None
            priv, _ = noise.generate_keypair()
            if self._protect:
                try:
                    self._write(self._dpapi_path, self._protect(priv))
                    log.info("[secure] создан ключ устройства (DPAPI)")
                except OSError:
                    self._write(self._plain_path, priv)
                    log.info("[secure] создан ключ устройства (файл только для пользователя)")
            else:
                self._write(self._plain_path, priv)
        return priv, noise.public_from_private(priv)

    # ── сервер ──
    def server(self) -> dict | None:
        try:
            d = json.load(open(self._server_path, encoding="utf-8"))
            d["pub_bytes"] = unb64u(d["pub"])
            return d
        except (OSError, ValueError, KeyError):
            return None

    def save_server(self, pub: bytes, device_id: str, url: str) -> None:
        data = {"pub": b64u(pub), "fp": fingerprint(pub), "sha256": sha256_hex(pub), "device_id": device_id,
                "url": url, "paired": time.time()}
        self._write(self._server_path, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        log.info("[secure] спарено: устройство %s, сервер %s", device_id, data["fp"])

    def rotate_server_key(self, pub: bytes) -> None:
        """Сервер сообщил новый ключ (secure_server_key) — использовать со следующего соединения."""
        cur = self.server()
        if cur:
            self.save_server(pub, cur.get("device_id", ""), cur.get("url", ""))

    def reset(self) -> None:
        """«Сбросить ключи»: удалить ключ устройства и данные спаривания."""
        for p in (self._dpapi_path, self._plain_path, self._server_path):
            try:
                os.remove(p)
            except OSError:
                pass
        log.info("[secure] ключи устройства сброшены")

    def status(self) -> dict:
        kp = self.device_keypair(create=False)
        srv = self.server()
        return {"device_key": bool(kp), "device_fp": fingerprint(kp[1]) if kp else None,
                "storage": "dpapi" if os.path.isfile(self._dpapi_path) else ("file" if kp else None),
                "paired": bool(srv), "server_fp": srv.get("fp") if srv else None,
                "device_id": srv.get("device_id") if srv else None}
