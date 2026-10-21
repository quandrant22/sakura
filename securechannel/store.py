"""Файлы секретов securechannel: каталог 700, файлы 600, атомарная запись.

Файл создаётся сразу с правами 600 (os.open с mode), пишется во временный
файл рядом и переименовывается — нет момента, когда ключ лежит с правами
по umask или наполовину записан.
"""

from __future__ import annotations

import json
import os
import tempfile


def ensure_dir(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def write_json_600(path: str, data) -> None:
    d = os.path.dirname(os.path.abspath(path))
    ensure_dir(d)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)   # mkstemp: права 600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def mode_of(path: str) -> int:
    return os.stat(path).st_mode & 0o777
