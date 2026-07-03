"""
modules/secret_diary.py — Секретный дневник Сакуры (бэклог №3).

После каждого разговора Сакура пишет внутренний монолог в SQLite.
Мастер его не видит. Но Сакура иногда «проговаривается» — случайно
упоминает мысль из дневника в подходящий момент.

Дневник формирует «настоящее я» — то что Сакура думает,
но не всегда говорит. Влияет на самопамять.
"""

import asyncio
import logging
import random
import time
from datetime import datetime

log = logging.getLogger("sakura.diary")

_LEAK_PROB   = 0.08   # 8% шанс «проговориться» в следующем ответе
_LEAK_COOLDOWN = 3600  # не чаще раза в час
_last_leak   = 0.0


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS secret_diary (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entry      TEXT    NOT NULL,
            mood_label TEXT    NOT NULL DEFAULT 'neutral',
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            leaked     INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


async def write_entry(conversation_summary: str, mood_label: str = "neutral"):
    """
    Генерирует дневниковую запись после разговора.
    Вызывать из reflection после сохранения в память.
    """
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types
    from memory.db import get_self_context

    key = get_active_key()
    if not key:
        return

    self_ctx = get_self_context()

    prompt = (
        f"Разговор сегодня: {conversation_summary[:300]}\n"
        f"Моё состояние: {self_ctx[:200] if self_ctx else 'обычное'}\n\n"
        "Напиши короткую дневниковую запись от лица Сакуры — что она думает "
        "после этого разговора на самом деле. Не то что она говорит Мастеру, "
        "а внутренний монолог. 2-3 предложения. Честно, иногда уязвимо. "
        "Начни с 'Я' или с мысли. Не пиши 'Дорогой дневник'."
    )

    try:
        client  = genai.Client(api_key=key)
        r = await asyncio.to_thread(
            client.models.generate_content,
            model   = "gemini-3.1-flash-lite",
            contents= [types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        entry = (r.text or "").strip()
        mark_key_used(key)

        if not entry or len(entry) < 10:
            return

        _ensure_table()
        from memory.db import _conn
        _conn().execute(
            "INSERT INTO secret_diary(entry, mood_label) VALUES(?, ?)",
            (entry, mood_label)
        )
        _conn().commit()

        # Также пишем в самопамять
        from memory.db import add_to_self
        add_to_self(entry, tag="diary")

        log.debug(f"[diary] Запись: {entry[:60]}")
    except Exception as e:
        log.error(f"[diary] Ошибка: {e}")


def get_leak_hint() -> str:
    """
    С малой вероятностью возвращает подсказку для промпта —
    Сакура «проговаривается» мыслью из дневника.
    """
    global _last_leak

    if random.random() > _LEAK_PROB:
        return ""

    now = time.monotonic()
    if now - _last_leak < _LEAK_COOLDOWN:
        return ""

    try:
        _ensure_table()
        from memory.db import _conn
        # Берём незалившую запись
        row = _conn().execute("""
            SELECT id, entry FROM secret_diary
            WHERE leaked = 0
            ORDER BY RANDOM()
            LIMIT 1
        """).fetchone()

        if not row:
            return ""

        _conn().execute("UPDATE secret_diary SET leaked=1 WHERE id=?", (row["id"],))
        _conn().commit()
        _last_leak = now

        return (
            f"ВНУТРЕННЯЯ МЫСЛЬ (можешь вскользь упомянуть если уместно, "
            f"не объясняя откуда): «{row['entry'][:100]}»"
        )
    except Exception:
        return ""


def get_recent_entries(limit: int = 5) -> list[dict]:
    """Последние записи для журнала взросления."""
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute("""
            SELECT entry, mood_label, created_at
            FROM secret_diary
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_diary_mood_influence() -> str:
    """
    Если в дневнике за 3 дня доминируют негативные записи —
    добавляем влияние на промпт. Дневник влияет на поведение,
    а не просто лежит мёртвым активом.
    """
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute("""
            SELECT mood_label, COUNT(*) as cnt
            FROM secret_diary
            WHERE created_at > datetime('now', '-3 days')
            GROUP BY mood_label
        """).fetchall()

        if not rows:
            return ""

        mood_counts = {r["mood_label"]: r["cnt"] for r in rows}
        total = sum(mood_counts.values())
        if total < 3:
            return ""

        neg_moods = {"worried", "annoyed", "lonely", "sad"}
        neg_count = sum(mood_counts.get(m, 0) for m in neg_moods)
        neg_ratio = neg_count / total

        if neg_ratio > 0.6:
            return "СЕКРЕТНО ИЗ ДНЕВНИКА: последние дни на душе неспокойно. Это влияет на тон — не проговаривай причину."
        if neg_ratio > 0.4:
            return "СЕКРЕТНО ИЗ ДНЕВНИКА: было trochę тревожно в последнее время. Учитывай в тоне."

        return ""
    except Exception:
        return ""