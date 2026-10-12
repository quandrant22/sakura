"""Журнал чата: все сообщения Мастера и ответы Сакуры по каналам.

Файл config.CHAT_DB_PATH (memory/chat.db): SQLite в режиме WAL, права
600, вне git. Таблицы:

  chat_messages  id, ts, role (user|assistant|system),
                 channel (voice|text|telegram|proactive|system), device,
                 text, client_msg_id, reply_to, meta (JSON, без секретов);
                 уникальность (device, client_msg_id) — повтор отправки
                 из окна не дублирует сообщение
  chat_fts       FTS5 по text (поиск)
  chat_read      device → last_read_id (прочитано на устройстве)
  chat_settings  key → value (пауза записи)

Функции синхронные (вызывать через asyncio.to_thread); ошибки записи
ловит вызывающий слой (sakura_core.chat_hooks) — ответ Мастеру журнал
не ломает. Наружу сообщения уходят в форме протокола v2 (to_wire).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time

import config

log = logging.getLogger(__name__)

ROLES = ("user", "assistant", "system")
CHANNELS = ("voice", "text", "telegram", "proactive", "system")
HISTORY_MAX = 100
SEARCH_MAX = 100
# meta — только эти ключи (без текстов, токенов и прочего).
META_KEYS = ("turn_id", "interrupted", "media", "source")
# Чистка по сроку хранения — не чаще раза в час.
_PURGE_EVERY_S = 3600.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    channel       TEXT    NOT NULL CHECK (channel IN ('voice', 'text', 'telegram', 'proactive', 'system')),
    device        TEXT,
    text          TEXT    NOT NULL,
    client_msg_id TEXT,
    reply_to      INTEGER,
    meta          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_device_client
    ON chat_messages (device, client_msg_id);
CREATE INDEX IF NOT EXISTS ix_chat_ts ON chat_messages (ts);
CREATE VIRTUAL TABLE IF NOT EXISTS chat_fts USING fts5 (
    text, content='chat_messages', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chat_ai AFTER INSERT ON chat_messages BEGIN
    INSERT INTO chat_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chat_ad AFTER DELETE ON chat_messages BEGIN
    INSERT INTO chat_fts (chat_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS chat_read (
    device       TEXT PRIMARY KEY,
    last_read_id INTEGER NOT NULL,
    ts           REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None
_last_purge = 0.0


def _path() -> str:
    return config.CHAT_DB_PATH


def _secure(path: str) -> None:
    """Права 600 на базу и её WAL/SHM."""
    for p in (path, path + "-wal", path + "-shm"):
        try:
            if os.path.exists(p):
                os.chmod(p, 0o600)
        except OSError as e:
            log.debug(f"[chat_log] chmod {p}: {e}")


def _db() -> sqlite3.Connection:
    global _conn, _conn_path
    path = _path()
    if _conn is not None and _conn_path == path:
        return _conn
    if _conn is not None:
        _conn.close()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(path):
        # Файл создаётся сразу с правами 600 — без окна, когда он 644.
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # WAL после checkpoint усекается до 1 МиБ, а не держит ~4 МиБ.
    conn.execute("PRAGMA journal_size_limit=1048576")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _secure(path)
    _conn, _conn_path = conn, path
    return conn


def close() -> None:
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, _conn_path = None, None


# ── форма сообщения ────────────────────────────────────────────────

def _clean_meta(meta: dict | None) -> str | None:
    if not meta:
        return None
    m = {k: meta[k] for k in META_KEYS if meta.get(k) is not None}
    return json.dumps(m, ensure_ascii=False) if m else None


def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "ts": r["ts"], "role": r["role"],
        "channel": r["channel"], "device": r["device"], "text": r["text"],
        "client_msg_id": r["client_msg_id"], "reply_to": r["reply_to"],
        "meta": json.loads(r["meta"]) if r["meta"] else {},
    }


def to_wire(msg: dict) -> dict:
    """Message протокола v2: id — строка, ts — Unix-секунды (float)."""
    out = {
        "id": str(msg["id"]), "ts": float(msg["ts"]), "role": msg["role"],
        "text": msg["text"], "channel": msg["channel"],
        "device": msg["device"] or "",
    }
    if msg.get("client_msg_id"):
        out["client_msg_id"] = msg["client_msg_id"]
    if msg.get("reply_to") is not None:
        out["reply_to"] = str(msg["reply_to"])
    turn_id = (msg.get("meta") or {}).get("turn_id")
    if turn_id:
        out["turn_id"] = turn_id
    return out


def parse_id(value) -> int | None:
    """id сообщения из запроса: 42, "42" или "m42"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s[:1] == "m":
        s = s[1:]
    return int(s) if s.isdigit() else None


# ── запись ─────────────────────────────────────────────────────────

def append(role: str, channel: str, text: str, *, device: str | None = None,
           client_msg_id: str | None = None, reply_to: int | None = None,
           meta: dict | None = None, ts: float | None = None) -> tuple[dict, bool]:
    """Добавить сообщение. Возвращает (сообщение, created).

    Повтор с теми же (device, client_msg_id) — уже записанное сообщение
    и created=False (окно переотправило после обрыва связи)."""
    if role not in ROLES:
        raise ValueError(f"role: {role!r}")
    if channel not in CHANNELS:
        raise ValueError(f"channel: {channel!r}")
    text = (text or "").strip()
    if not text:
        raise ValueError("пустой текст")
    with _lock:
        db = _db()
        if client_msg_id:
            r = db.execute(
                "SELECT * FROM chat_messages WHERE device IS ? AND client_msg_id = ?",
                (device, client_msg_id)).fetchone()
            if r is not None:
                return _row(r), False
        cur = db.execute(
            "INSERT INTO chat_messages (ts, role, channel, device, text,"
            " client_msg_id, reply_to, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time() if ts is None else ts, role, channel, device, text,
             client_msg_id or None, reply_to, _clean_meta(meta)))
        r = db.execute("SELECT * FROM chat_messages WHERE id = ?",
                       (cur.lastrowid,)).fetchone()
        msg = _row(r)
    _maybe_purge()
    return msg, True


# ── чтение ─────────────────────────────────────────────────────────

def get(msg_id: int) -> dict | None:
    with _lock:
        r = _db().execute("SELECT * FROM chat_messages WHERE id = ?",
                          (msg_id,)).fetchone()
    return _row(r) if r else None


def history(before_id: int | None = None, limit: int = 50,
            before_ts: float | None = None) -> tuple[list[dict], bool]:
    """Последние limit (≤ 100) сообщений до before_id / before_ts —
    по возрастанию id; has_more — есть ли ещё более ранние."""
    limit = max(1, min(int(limit or 50), HISTORY_MAX))
    where, args = [], []
    if before_id is not None:
        where.append("id < ?")
        args.append(int(before_id))
    if before_ts is not None:
        where.append("ts < ?")
        args.append(float(before_ts))
    sql = "SELECT * FROM chat_messages"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    with _lock:
        rows = _db().execute(sql, (*args, limit + 1)).fetchall()
    has_more = len(rows) > limit
    return [_row(r) for r in reversed(rows[:limit])], has_more


def _fts_query(q: str) -> str:
    """Фраза пользователя → безопасный запрос FTS5: слова в кавычках,
    последнее — префиксом (поиск по мере ввода)."""
    words = [w for w in "".join(c if c.isalnum() else " " for c in q).split() if w]
    if not words:
        return ""
    parts = [f'"{w}"' for w in words]
    parts[-1] += "*"
    return " ".join(parts)


def search(q: str, limit: int = 20) -> list[dict]:
    """Поиск по тексту (FTS5), новые сначала."""
    fq = _fts_query(q or "")
    if not fq:
        return []
    limit = max(1, min(int(limit or 20), SEARCH_MAX))
    with _lock:
        rows = _db().execute(
            "SELECT m.* FROM chat_fts f JOIN chat_messages m ON m.id = f.rowid"
            " WHERE chat_fts MATCH ? ORDER BY m.id DESC LIMIT ?",
            (fq, limit)).fetchall()
    return [_row(r) for r in rows]


def count() -> int:
    with _lock:
        return _db().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]


def last_id() -> int:
    with _lock:
        r = _db().execute("SELECT MAX(id) FROM chat_messages").fetchone()[0]
    return int(r or 0)


# ── изменение ──────────────────────────────────────────────────────

def delete(msg_id: int) -> bool:
    with _lock:
        cur = _db().execute("DELETE FROM chat_messages WHERE id = ?", (msg_id,))
    return cur.rowcount > 0


def clear() -> int:
    """Стереть весь журнал. Возвращает число удалённых сообщений."""
    with _lock:
        db = _db()
        n = db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        db.execute("DELETE FROM chat_messages")
        db.execute("INSERT INTO chat_fts (chat_fts) VALUES ('rebuild')")
        db.execute("DELETE FROM chat_read")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("VACUUM")
    _secure(_path())
    return n


def mark_read(device: str, last_read_id: int) -> int:
    """Отметить прочитанное на устройстве (только вперёд). Вернуть
    итоговый last_read_id."""
    last_read_id = max(0, min(int(last_read_id), last_id()))
    with _lock:
        db = _db()
        db.execute(
            "INSERT INTO chat_read (device, last_read_id, ts) VALUES (?, ?, ?)"
            " ON CONFLICT(device) DO UPDATE SET"
            " last_read_id = MAX(last_read_id, excluded.last_read_id), ts = excluded.ts",
            (device, last_read_id, time.time()))
        r = db.execute("SELECT last_read_id FROM chat_read WHERE device = ?",
                       (device,)).fetchone()
    return int(r[0])


def get_read(device: str) -> int:
    with _lock:
        r = _db().execute("SELECT last_read_id FROM chat_read WHERE device = ?",
                          (device,)).fetchone()
    return int(r[0]) if r else 0


# ── пауза записи ───────────────────────────────────────────────────

def is_paused() -> bool:
    """Запись на паузе: настройкой CHAT_LOG_PAUSED или командой «не записывай»."""
    if config.CHAT_LOG_PAUSED:
        return True
    with _lock:
        r = _db().execute("SELECT value FROM chat_settings WHERE key = 'paused'").fetchone()
    return bool(r and r[0] == "1")


def set_paused(paused: bool) -> None:
    with _lock:
        _db().execute(
            "INSERT INTO chat_settings (key, value) VALUES ('paused', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("1" if paused else "0",))


# ── срок хранения, экспорт ─────────────────────────────────────────

def purge_old(days: int | None = None) -> int:
    """Удалить сообщения старше days (по умолчанию CHAT_LOG_RETENTION_DAYS;
    0 — хранить бессрочно)."""
    days = config.CHAT_LOG_RETENTION_DAYS if days is None else days
    if not days or days <= 0:
        return 0
    with _lock:
        cur = _db().execute("DELETE FROM chat_messages WHERE ts < ?",
                            (time.time() - days * 86400,))
    if cur.rowcount:
        log.info(f"[chat_log] срок хранения {days} дн.: удалено {cur.rowcount}")
    return cur.rowcount


def _maybe_purge() -> None:
    global _last_purge
    now = time.monotonic()
    if now - _last_purge < _PURGE_EVERY_S:
        return
    _last_purge = now
    try:
        purge_old()
    except Exception as e:
        log.warning(f"[chat_log] чистка по сроку: {type(e).__name__}: {e}")


_ROLE_NAMES = {"user": "Мастер", "assistant": "Сакура", "system": "Система"}


def export(fmt: str = "md") -> str:
    """Весь журнал текстом: md — для чтения, json — как в протоколе."""
    with _lock:
        rows = [_row(r) for r in _db().execute(
            "SELECT * FROM chat_messages ORDER BY id").fetchall()]
    if fmt == "json":
        return json.dumps([to_wire(m) for m in rows], ensure_ascii=False, indent=1)
    out = ["# Журнал чата Сакуры", ""]
    day = None
    for m in rows:
        lt = time.localtime(m["ts"])
        d = time.strftime("%Y-%m-%d", lt)
        if d != day:
            out += [f"## {d}", ""]
            day = d
        who = _ROLE_NAMES.get(m["role"], m["role"])
        src = m["channel"] + (f", {m['device']}" if m["device"] else "")
        out.append(f"**{time.strftime('%H:%M:%S', lt)} {who}** ({src}): {m['text']}")
        out.append("")
    return "\n".join(out)


def stats() -> dict:
    """Число сообщений и размер файлов базы (байт) — для отчётов и /status."""
    path = _path()
    sizes = [os.path.getsize(p) if os.path.exists(p) else 0
             for p in (path, path + "-wal", path + "-shm")]
    return {"messages": count(), "bytes": sum(sizes), "db_bytes": sizes[0]}
