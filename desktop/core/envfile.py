"""desktop.core.envfile — раздел «Секреты»: задан ли ключ в .env и запись нового значения.

Значения никогда не возвращаются, не пишутся в журнал и не попадают в состояние интерфейса:
status() отдаёт только «задан / не задан». set_secret() меняет одну строку KEY=…, сохраняя
остальные строки, комментарии и порядок; перед записью — копия .env.bak с правами только
текущего пользователя; запись — UTF-8 без BOM, атомарно (временный файл + замена).
"""
import logging
import os
import re
import shutil
import tempfile

log = logging.getLogger("sakura.secrets")

# Ключи, которые раздел «Секреты» показывает и даёт записать.
SECRET_KEYS = ("WS_TOKEN", "YANDEX_MUSIC_TOKEN")
# Не секреты (мастер «Подключение»): значения можно показывать.
CONFIG_KEYS = ("DEVICE_ID", "VPS_WS_URL", "SERVER_TRANSPORT")
# Настройки → «Расширение браузера» (не секреты; пустое значение — снять закрепление / выключить загрузку).
EXTENSION_KEYS = ("SAKURA_EXTENSION_ID", "BROWSER_UPLOAD_DIR")
MAX_LEN = 4096


class SecretError(ValueError):
    """Ошибка без значения секрета в тексте."""


def env_path() -> str | None:
    """Путь к .env, который читает ядро (SAKURA_ENV_FILE → desktop/.env → agent/.env)."""
    from desktop.core import config
    return os.getenv("SAKURA_ENV_FILE") or config.ENV_FILE


def _read_lines(path: str) -> list[str]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:  # -sig: BOM, если был, не мешает
        return f.read().splitlines(keepends=True)


def _key_re(key: str):
    return re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=(.*)$")


def status(path: str | None, keys=SECRET_KEYS) -> dict[str, bool]:
    """{KEY: задан ли непустой} — значения не возвращаются."""
    lines = _read_lines(path) if path else []
    out = {}
    for k in keys:
        rx = _key_re(k)
        val = None
        for line in lines:
            m = rx.match(line.rstrip("\r\n"))
            if m:
                val = m.group(1).strip().strip('"').strip("'")
        out[k] = bool(val)
    return out


def _check(key: str, value: str) -> str:
    if key not in SECRET_KEYS + CONFIG_KEYS + EXTENSION_KEYS:
        raise SecretError("этот ключ нельзя менять из Настроек")
    if not isinstance(value, str):
        raise SecretError("значение должно быть строкой")
    value = value.strip()
    if key == "VPS_WS_URL" and not value.startswith(("ws://", "wss://")):
        raise SecretError("адрес сервера должен начинаться с ws:// или wss://")
    if key == "SERVER_TRANSPORT" and value not in ("ws", "wss", "noise", "noise-only"):
        raise SecretError("режим канала: ws, wss, noise или noise-only")
    if key == "DEVICE_ID" and not re.fullmatch(r"[A-Za-z0-9_.-]{2,40}", value):
        raise SecretError("имя устройства: латиница, цифры, «-», «_», «.» (2–40 знаков)")
    # ID расширения Chromium — 32 буквы a–p.
    if key == "SAKURA_EXTENSION_ID" and value and not re.fullmatch(r"[a-p]{32}", value):
        raise SecretError("ID расширения — 32 латинские буквы a–p (как на странице «Расширения»)")
    if key == "BROWSER_UPLOAD_DIR" and value and not (os.path.isabs(value) and os.path.isdir(value)):
        raise SecretError("папка для загрузок — полный путь к существующей папке")
    if not value and key not in EXTENSION_KEYS:
        raise SecretError("пустое значение")
    if len(value) > MAX_LEN or any(c in value for c in "\r\n\0"):
        raise SecretError("значение слишком длинное или содержит перевод строки")
    return value


def config_values(path: str | None) -> dict[str, str]:
    """Значения не секретных ключей (CONFIG_KEYS) — для мастера «Подключение»."""
    out = {k: "" for k in CONFIG_KEYS}
    for line in _read_lines(path) if path else []:
        for k in CONFIG_KEYS:
            m = _key_re(k).match(line.rstrip("\r\n"))
            if m:
                out[k] = m.group(1).strip().strip('"').strip("'")
    return out


def set_secret(path: str, key: str, value: str, restrict=None) -> None:
    """Записать KEY=value в .env, сохранив остальное; копия .env.bak — только текущему пользователю."""
    value = _check(key, value)
    lines = _read_lines(path)
    nl = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    rx = _key_re(key)
    new_line = f"{key}={value}{nl}"
    replaced = False
    out = []
    for line in lines:
        if rx.match(line.rstrip("\r\n")):
            if not replaced:
                out.append(new_line)
                replaced = True
            continue  # повторы ключа убираются: остаётся одно значение
        out.append(line)
    if not replaced:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += nl
        out.append(new_line)

    folder = os.path.dirname(os.path.abspath(path))
    if os.path.isfile(path):
        bak = path + ".bak"
        shutil.copyfile(path, bak)
        if restrict:
            try:
                restrict(bak)
            except Exception as e:  # noqa: BLE001
                log.warning("[secrets] не удалось ограничить права на .env.bak: %s", type(e).__name__)
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:  # UTF-8 без BOM
            f.write("".join(out))
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    if restrict:
        try:
            restrict(path)
        except Exception as e:  # noqa: BLE001
            log.warning("[secrets] не удалось ограничить права на .env: %s", type(e).__name__)
    log.info("[secrets] %s обновлён в .env%s", key,
             "" if key in CONFIG_KEYS + EXTENSION_KEYS else " (значение не журналируется)")
