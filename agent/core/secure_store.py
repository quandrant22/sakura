"""
core/secure_store.py — ключ устройства агента и данные спаривания (ТЗ-4, PROTOCOL §8).

    keys = load()            # DeviceKeys | None; битый файл — исключение
    save(keys)               # атомарно, права только текущему пользователю
    set_next_server_pub(pub) # ротация: новый ключ сервера со следующего входа
    promote_next()           # next_server_pub → server_pub
    wipe()                   # «Сбросить спаривание»

Файл: %APPDATA%\\Sakura\\secure\\device.json (вне Windows —
~/.config/sakura/secure/device.json; каталог можно задать SAKURA_SECURE_DIR).

    {"v":1, "device_id", "pub", "server_url", "server_pub", "server_fp",
     "paired_at", "next_server_pub",
     "priv_dpapi": "<base64 DPAPI>"   — Windows: ключ зашифрован ключом пользователя
     | "priv": "<base64>"}            — без DPAPI: только права на файл

Права: на Windows каталог и файл — ACL только текущему пользователю
(icacls /inheritance:r /grant:r), вне Windows — 700/600. Временный файл
получает права ДО записи ключа и переименовывается в device.json — нет
момента, когда ключ лежит с наследуемыми правами или наполовину записан.

В журнал — только device_id и отпечаток сервера. Никогда — ключи.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass

log = logging.getLogger("sakura.agent")

FILE_NAME = "device.json"
_DPAPI_ENTROPY = b"sakura-securechannel/1 agent device key"


@dataclass
class DeviceKeys:
    """Тот же вид, что у fake_secure_store: ключи — base64 (priv — в памяти)."""

    device_id: str
    priv: str
    pub: str
    server_url: str
    server_pub: str
    server_fp: str
    paired_at: float
    next_server_pub: str | None = None
    v: int = 1


class StoreError(Exception):
    """Файл ключей есть, но не читается (повреждён, чужой DPAPI)."""


def default_dir() -> str:
    env = os.getenv("SAKURA_SECURE_DIR", "").strip()
    if env:
        return env
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Sakura", "secure")
    return os.path.join(os.path.expanduser("~"), ".config", "sakura", "secure")


# ── платформенные защиты ─────────────────────────────────────────────────


def _icacls(path: str, *, folder: bool) -> None:
    user = os.getenv("USERNAME", "").strip()
    if not user:
        raise OSError("USERNAME не задан")
    grant = f"{user}:(OI)(CI)F" if folder else f"{user}:F"
    subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", grant],
                   check=True, capture_output=True, timeout=15,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def restrict(path: str, *, folder: bool = False) -> None:
    """Доступ только текущему пользователю."""
    if os.name == "nt":
        _icacls(path, folder=folder)
    else:
        os.chmod(path, 0o700 if folder else 0o600)


def _dpapi():
    """(protect, unprotect) Windows DPAPI или None."""
    if os.name != "nt":
        return None
    import ctypes
    import ctypes.wintypes as wt

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def take(b) -> bytes:
        try:
            return ctypes.string_at(b.pbData, b.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(b.pbData)

    def call(fn, data: bytes) -> bytes:
        inp, _keep1 = blob(data)
        ent, _keep2 = blob(_DPAPI_ENTROPY)
        out = Blob()
        if not fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0x1,
                  ctypes.byref(out)):
            raise OSError("DPAPI")
        return take(out)

    crypt32 = ctypes.windll.crypt32
    return (lambda d: call(crypt32.CryptProtectData, d),
            lambda d: call(crypt32.CryptUnprotectData, d))


# ── хранилище ────────────────────────────────────────────────────────────


class SecureStore:
    def __init__(self, folder: str | None = None, *, protect=None, unprotect=None,
                 restrict_fn=None, use_dpapi: bool = True):
        self.folder = folder or default_dir()
        self.path = os.path.join(self.folder, FILE_NAME)
        if protect is None and use_dpapi:
            pair = _dpapi()
            if pair:
                protect, unprotect = pair
        self._protect, self._unprotect = protect, unprotect
        self._restrict = restrict_fn or restrict

    # чтение
    def _read_raw(self) -> dict | None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            raise StoreError(f"device.json не читается: {type(e).__name__}") from None
        if not isinstance(data, dict) or data.get("v") != 1:
            raise StoreError("device.json: неизвестный формат")
        return data

    def load(self) -> DeviceKeys | None:
        data = self._read_raw()
        if data is None:
            return None
        try:
            if "priv_dpapi" in data:
                if self._unprotect is None:
                    raise StoreError("ключ зашифрован DPAPI, а DPAPI недоступен")
                priv = base64.b64encode(
                    self._unprotect(base64.b64decode(data["priv_dpapi"]))).decode()
            else:
                priv = data["priv"]
            return DeviceKeys(device_id=str(data["device_id"]), priv=priv,
                              pub=data["pub"], server_url=data.get("server_url", ""),
                              server_pub=data["server_pub"],
                              server_fp=data.get("server_fp", ""),
                              paired_at=float(data.get("paired_at", 0)),
                              next_server_pub=data.get("next_server_pub"))
        except StoreError:
            raise
        except (KeyError, ValueError, TypeError, OSError) as e:
            raise StoreError(f"device.json повреждён: {type(e).__name__}") from None

    # запись
    def _write(self, data: dict) -> None:
        new_dir = not os.path.isdir(self.folder)
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        if new_dir:
            try:
                self._restrict(self.folder, folder=True)
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("[secure_store] права на каталог ключей: %s", type(e).__name__)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=self.folder)
        try:
            # Права — до записи ключа. Не вышло ограничить — не пишем.
            self._restrict(tmp, folder=False)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd = -1
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def save(self, keys: DeviceKeys) -> None:
        data = dataclasses.asdict(keys)
        priv = data.pop("priv")
        if self._protect is not None:
            data["priv_dpapi"] = base64.b64encode(
                self._protect(base64.b64decode(priv))).decode()
        else:
            data["priv"] = priv
        self._write(data)
        log.info("[secure_store] сохранено: устройство %s, сервер %s",
                 keys.device_id, keys.server_fp)

    def _update(self, **fields) -> None:
        data = self._read_raw()
        if data is None:
            raise StoreError("устройство не спарено")
        data.update(fields)
        self._write(data)

    def set_next_server_pub(self, pub: str) -> None:
        self._update(next_server_pub=pub)

    def promote_next(self) -> None:
        data = self._read_raw()
        if data is None or not data.get("next_server_pub"):
            return
        from core.transport import _fp, key_bytes
        raw = key_bytes(data["next_server_pub"])
        self._update(server_pub=base64.b64encode(raw).decode(), server_fp=_fp(raw),
                     next_server_pub=None)

    def wipe(self) -> None:
        try:
            os.remove(self.path)
            log.info("[secure_store] спаривание сброшено")
        except FileNotFoundError:
            pass


# ── API модуля (его ищет core.transport._default_store) ──────────────────

_default: SecureStore | None = None


def _store() -> SecureStore:
    global _default
    if _default is None or _default.folder != default_dir():
        _default = SecureStore()
    return _default


def load() -> DeviceKeys | None:
    return _store().load()


def save(keys: DeviceKeys) -> None:
    _store().save(keys)


def set_next_server_pub(pub: str) -> None:
    _store().set_next_server_pub(pub)


def promote_next() -> None:
    _store().promote_next()


def wipe() -> None:
    _store().wipe()
