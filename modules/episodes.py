"""
modules/episodes.py — Эпизодическая память «сцена» (бэклог №2).

Хранит не сухой факт («Мастер играл в Phasmophobia»),
а момент с эмоциональным тегом и контекстом:
  {
    "text":      "Мастер позвал играть в хоррор в 2 ночи. Я держалась тихо.",
    "emotion":   "tender",           # valence/arousal в момент
    "valence":   0.4,
    "arousal":   0.6,
    "context":   "Phasmophobia",     # активное окно / тема
    "created_at": "2026-06-14T02:13",
    "weight":    1.0,                # важность (растёт при обращениях)
    "tags":      ["ночь", "игра", "хоррор"],
  }

Сакура может спонтанно «вспомнить» сцену в тему через get_recall().
Reflection пишет сцены через add_episode().

Хранение: таблица episodes в sakura.db (создаётся автоматически).
"""

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("sakura.episodes")

MAX_EPISODES   = 200   # максимум сцен (старые/малоценные вытесняются)
RECALL_HOURS   = 12    # минимум между спонтанными воспоминаниями
RECALL_PROB    = 0.15  # вероятность вспомнить при релевантном контексте


# ── Инициализация таблицы ─────────────────────────────────────────────

def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text        TEXT    NOT NULL,
            emotion     TEXT    NOT NULL DEFAULT 'neutral',
            valence     REAL    NOT NULL DEFAULT 0.0,
            arousal     REAL    NOT NULL DEFAULT 0.3,
            context     TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            last_recall TEXT,
            recall_count INTEGER NOT NULL DEFAULT 0,
            weight      REAL    NOT NULL DEFAULT 1.0,
            tags        TEXT    NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_ep_created ON episodes(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ep_weight  ON episodes(weight DESC);
    """)
    conn.commit()


# ── Запись ────────────────────────────────────────────────────────────

def add_episode(
    text:    str,
    emotion: str      = "neutral",
    valence: float    = 0.0,
    arousal: float    = 0.3,
    context: str      = "",
    tags:    list     = None,
    weight:  float    = 1.0,
) -> int:
    """
    Добавляет сцену в эпизодическую память.
    Возвращает id новой записи.
    Вызывать из reflection.py при ночной рефлексии.
    """
    _ensure_table()
    tags_json = json.dumps(tags or [], ensure_ascii=False)

    from memory.db import _conn
    conn = _conn()

    # Вытеснение если таблица переполнена
    count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    if count >= MAX_EPISODES:
        # Удаляем наименее ценную (низкий weight + давно не вспоминали)
        conn.execute("""
            DELETE FROM episodes WHERE id IN (
                SELECT id FROM episodes
                WHERE last_recall IS NULL OR
                      (julianday('now') - julianday(last_recall)) > 30
                ORDER BY weight ASC, recall_count ASC
                LIMIT 10
            )
        """)
        conn.commit()

    cur = conn.execute("""
        INSERT INTO episodes (text, emotion, valence, arousal, context, tags, weight)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (text.strip(), emotion, valence, arousal, context, tags_json, weight))
    conn.commit()
    log.debug(f"[episodes] +сцена [{emotion}]: {text[:60]}")
    return cur.lastrowid


# ── Поиск для спонтанного воспоминания ───────────────────────────────

def get_recall(current_context: str = "", current_emotion: str = "neutral") -> Optional[dict]:
    """
    Возвращает эпизод для спонтанного воспоминания или None.

    Логика:
      1. Проверяем кулдаун (не слишком часто)
      2. Ищем релевантный по контексту и эмоции
      3. Случайность * weight — не всегда одно и то же

    Формат ответа: {"text": ..., "emotion": ..., "context": ..., "prompt": ...}
    """
    import random
    _ensure_table()

    from memory.db import _conn
    conn = _conn()

    # Кулдаун
    last = conn.execute("""
        SELECT MAX(last_recall) FROM episodes WHERE last_recall IS NOT NULL
    """).fetchone()[0]
    if last:
        try:
            hours_ago = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
            if hours_ago < RECALL_HOURS:
                return None
        except Exception:
            pass

    # Поиск кандидатов — релевантные по контексту или эмоции
    candidates = conn.execute("""
        SELECT id, text, emotion, context, weight, recall_count
        FROM episodes
        WHERE length(text) > 20
        ORDER BY weight DESC, created_at DESC
        LIMIT 20
    """).fetchall()

    if not candidates:
        return None

    # Фильтруем по релевантности
    ctx_lower = current_context.lower()
    scored = []
    for row in candidates:
        score = row["weight"]
        # Бонус за совпадение контекста
        if ctx_lower and any(w in row["context"].lower() for w in ctx_lower.split()[:3]):
            score *= 2.0
        # Бонус за эмоциональное родство
        if row["emotion"] == current_emotion:
            score *= 1.5
        # Штраф за часто вспоминаемые
        score /= (1 + row["recall_count"] * 0.3)
        scored.append((score, row))

    if not scored:
        return None

    # Случайный выбор, взвешенный по score
    if random.random() > RECALL_PROB:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    _, chosen = scored[0] if random.random() < 0.6 else scored[min(1, len(scored) - 1)]

    # Обновляем статистику
    conn.execute("""
        UPDATE episodes
        SET recall_count = recall_count + 1,
            last_recall  = datetime('now'),
            weight       = weight + 0.1
        WHERE id = ?
    """, (chosen["id"],))
    conn.commit()

    # Промпт для Gemini — чтобы органично вплести воспоминание
    prompt_hint = (
        f"Сцена из памяти: «{chosen['text']}»\n"
        "Если уместно — оброни это воспоминание в разговоре. "
        "Одна фраза, живо. Не говори 'я помню' или 'ты рассказывал'."
    )

    return {
        "text":    chosen["text"],
        "emotion": chosen["emotion"],
        "context": chosen["context"],
        "prompt":  prompt_hint,
        "id":      chosen["id"],
    }


def get_recent_episodes(limit: int = 5) -> list[dict]:
    """Последние N сцен — для рефлексии и журнала."""
    _ensure_table()
    from memory.db import _conn
    conn = _conn()
    rows = conn.execute("""
        SELECT text, emotion, context, created_at, weight
        FROM episodes
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    _ensure_table()
    from memory.db import _conn
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    emotions = conn.execute("""
        SELECT emotion, COUNT(*) as n FROM episodes GROUP BY emotion ORDER BY n DESC
    """).fetchall()
    return {
        "total":   total,
        "emotions": {r["emotion"]: r["n"] for r in emotions},
    }
