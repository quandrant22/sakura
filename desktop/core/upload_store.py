"""desktop.core.upload_store — файлы для page.upload по одноразовому токену.

Агент браузера получает от сервера имя файла (или путь), ядро выдаёт токен, расширение
забирает по токену содержимое (extension_server: upload_fetch → upload_data).
Токен выдаётся только для обычного файла внутри папки BROWSER_UPLOAD_DIR (настройка):
путь вне папки (в том числе через «..» или ссылку), папка не задана, файл .env* — отказ.
Токен одноразовый и живёт TOKEN_TTL секунд. Имя и содержимое файла не журналируются.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import secrets
import threading
import time

TOKEN_TTL = 300.0
MAX_BYTES = 25 * 1024 * 1024


class UploadError(ValueError):
    """Отказ без пути и содержимого в тексте."""


class UploadStore:
    def __init__(self, root: str | None, ttl: float = TOKEN_TTL, max_bytes: int = MAX_BYTES,
                 clock=time.monotonic):
        self.set_root(root)
        self.ttl = ttl
        self.max_bytes = max_bytes
        self._clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def set_root(self, root: str | None) -> None:
        """Сменить папку (Настройки → Расширение браузера); выданные токены проверяются заново при take."""
        self.root = os.path.realpath(root) if root else None

    def _check(self, path: str) -> str:
        if not self.root or not os.path.isdir(self.root):
            raise UploadError("папка для загрузок (BROWSER_UPLOAD_DIR) не задана")
        if not isinstance(path, str) or not path.strip() or "\0" in path:
            raise UploadError("не указан файл")
        p = path.strip()
        full = os.path.realpath(p if os.path.isabs(p) else os.path.join(self.root, p))
        try:
            inside = os.path.commonpath([self.root, full]) == self.root
        except ValueError:  # разные диски Windows
            inside = False
        if not inside or full == self.root:
            raise UploadError("файл вне папки для загрузок — отказ")
        if os.path.basename(full).lower().startswith(".env"):
            raise UploadError("секреты не загружаются")
        if not os.path.isfile(full):
            raise UploadError("файл не найден в папке для загрузок")
        if os.path.getsize(full) > self.max_bytes:
            raise UploadError(f"файл больше {self.max_bytes // (1024 * 1024)} МБ")
        return full

    def issue(self, path: str) -> str:
        """Токен на файл внутри папки; иначе UploadError."""
        full = self._check(path)
        token = secrets.token_urlsafe(18)
        now = self._clock()
        with self._lock:
            self._tokens = {t: v for t, v in self._tokens.items() if v[1] > now}
            self._tokens[token] = (full, now + self.ttl)
        return token

    def take(self, token: str) -> dict:
        """Одноразово: {name, mime, size, data_b64}. Путь проверяется ещё раз (файл могли подменить)."""
        with self._lock:
            item = self._tokens.pop(token, None)
        if item is None or item[1] < self._clock():
            raise UploadError("токен файла недействителен")
        full = self._check(item[0])
        with open(full, "rb") as f:
            data = f.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise UploadError("файл изменился и стал слишком большим")
        name = os.path.basename(full)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return {"name": name, "mime": mime, "size": len(data), "data_b64": base64.b64encode(data).decode("ascii")}
