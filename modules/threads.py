"""
modules/threads.py — несколько нитей разговора.

Сакура держит параллельные незакрытые темы и возвращается к ним:
  «а, ты про то что говорил насчёт VPS...»
  «кстати, ты так и не ответил — закончил тот проект?»

Как работает:
  - После каждого сообщения LLM извлекает «открытые вопросы» из диалога
  - Хранит до 5 незакрытых нитей с весом (давность, важность)
  - get_threads_context() → блок для промпта «помни что обсуждали»
  - get_thread_recall() → подсказка вернуться к старой теме (редко)
  - Нити закрываются когда тема явно разрешилась

Принципы:
  - Не спамить: возврат к нити не чаще раза в 10 сообщений
  - Не навязываться: подсказка «вернуться» — лёгкая, в конце ответа
  - Хранение в sakura.db, персистентно между сессиями

Публичный API:
  extract_threads(user_msg, reply)  — обновить нити (в extract_and_remember)
  get_threads_context() -> str      — блок для промпта
  get_thread_recall() -> str|None   — подсказка вернуться к нити
  close_thread(topic)               — закрыть нить (тема решена)
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

log = logging.getLogger("sakura.threads")

_RECALL_COOLDOWN = 600   # не предлагать возврат чаще раза в 10 минут
_MAX_THREADS     = 5     # максимум открытых нитей
_THREAD_TTL_DAYS = 7     # нить живёт 7 дней без упоминания

_last_recall_at: float = 0.0


# ── Хранилище ─────────────────────────────────────────────────────────

def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversation_threads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT    NOT NULL,
            summary     TEXT    NOT NULL,
            opened_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
            weight      REAL    NOT NULL DEFAULT 1.0,
            closed      INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


def _get_open_threads() -> list:
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute("""
            SELECT id, topic, summary, opened_at, last_seen, weight
            FROM conversation_threads
            WHERE closed = 0
              AND datetime(last_seen) > datetime('now', '-7 days')
            ORDER BY weight DESC, last_seen DESC
            LIMIT ?
        """, (_MAX_THREADS,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug(f"[threads] get: {e}")
        return []


def _upsert_thread(topic: str, summary: str, weight: float = 1.0):
    try:
        _ensure_table()
        from memory.db import _conn
        conn = _conn()
        # Ищем похожую открытую нить
        existing = conn.execute(
            "SELECT id FROM conversation_threads WHERE closed=0 AND topic=?",
            (topic[:80],)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE conversation_threads SET summary=?, last_seen=datetime('now'), "
                "weight=MIN(weight+0.3, 3.0) WHERE id=?",
                (summary[:200], existing[0])
            )
        else:
            # Если уже _MAX_THREADS — закрываем самую старую
            count = conn.execute(
                "SELECT COUNT(*) FROM conversation_threads WHERE closed=0"
            ).fetchone()[0]
            if count >= _MAX_THREADS:
                conn.execute(
                    "UPDATE conversation_threads SET closed=1 WHERE closed=0 "
                    "ORDER BY last_seen ASC LIMIT 1"
                )
            conn.execute(
                "INSERT INTO conversation_threads(topic, summary, weight) VALUES(?,?,?)",
                (topic[:80], summary[:200], weight)
            )
        conn.commit()
    except Exception as e:
        log.debug(f"[threads] upsert: {e}")


def _mark_seen(thread_id: int):
    try:
        from memory.db import _conn
        conn = _conn()
        conn.execute(
            "UPDATE conversation_threads SET last_seen=datetime('now') WHERE id=?",
            (thread_id,)
        )
        conn.commit()
    except Exception:
        pass


def close_thread(topic: str):
    """Закрыть нить — тема решена."""
    try:
        _ensure_table()
        from memory.db import _conn
        conn = _conn()
        conn.execute(
            "UPDATE conversation_threads SET closed=1 WHERE topic=? AND closed=0",
            (topic[:80],)
        )
        conn.commit()
    except Exception as e:
        log.debug(f"[threads] close: {e}")


# ── Извлечение нитей ─────────────────────────────────────────────────

# Маркеры незакрытых вопросов в тексте Мастера
_OPEN_SIGNALS = [
    "потом", "позже", "разберусь", "подумаю", "не знаю ещё",
    "надо будет", "планирую", "буду", "хочу", "собираюсь",
    "не успел", "не дошли руки", "когда-нибудь", "может быть",
    "посмотрим", "вернёмся", "к этому", "об этом позже",
]

# Маркеры закрытых тем
_CLOSE_SIGNALS = [
    "сделал", "готово", "закончил", "решил", "получилось",
    "разобрался", "всё", "уже", "выполнил", "завершил",
]


def extract_threads(user_msg: str, reply: str):
    """
    Анализирует диалог и обновляет нити.
    Вызывать из extract_and_remember — попутно, без доп. LLM-запроса.
    Используем простой keyword-детект чтобы не тратить квоту.
    """
    tl = user_msg.lower()

    # Детект закрытия: «сделал X» — ищем нить с похожей темой
    if any(w in tl for w in _CLOSE_SIGNALS):
        threads = _get_open_threads()
        for t in threads:
            # Грубая проверка: слово из темы есть в сообщении
            topic_words = [w for w in t["topic"].lower().split() if len(w) > 4]
            if any(w in tl for w in topic_words):
                close_thread(t["topic"])
                log.debug(f"[threads] закрыта: {t['topic']}")
                return

    # Детект открытия: незакрытое намерение
    if any(w in tl for w in _OPEN_SIGNALS):
        # Берём первые 60 символов как тему (грубо но без LLM)
        topic   = user_msg.strip()[:60].rstrip(" .,!?")
        summary = f"Мастер упомянул: «{topic}»"
        _upsert_thread(topic, summary, weight=1.0)
        log.debug(f"[threads] открыта: {topic[:40]}")


# ── Контекст для промпта ─────────────────────────────────────────────

def get_threads_context() -> str:
    """
    Блок для системного промпта — незакрытые темы.
    Молчим если нет ничего.
    """
    threads = _get_open_threads()
    if not threads:
        return ""

    lines = ["НЕЗАКРЫТЫЕ ТЕМЫ (можешь вернуться если уместно):"]
    for t in threads[:3]:
        age_days = (
            datetime.now() -
            datetime.fromisoformat(t["last_seen"])
        ).days
        age_str = f"{age_days}д назад" if age_days > 0 else "сегодня"
        lines.append(f"  • {t['summary']} ({age_str})")

    return "\n".join(lines)


def get_thread_recall() -> Optional[str]:
    """
    Подсказка вернуться к старой теме — редко, не навязчиво.
    Возвращает промпт-дополнение или None.
    """
    global _last_recall_at
    if time.time() - _last_recall_at < _RECALL_COOLDOWN:
        return None

    threads = _get_open_threads()
    if not threads:
        return None

    # Берём самую старую незакрытую нить (давно не всплывала)
    oldest = min(threads, key=lambda t: t["last_seen"])
    age_days = (
        datetime.now() -
        datetime.fromisoformat(oldest["last_seen"])
    ).days

    # Возвращаемся только если прошло хотя бы 2 дня
    if age_days < 2:
        return None

    _last_recall_at = time.time()
    _mark_seen(oldest["id"])

    return (
        f"Кстати, {age_days} дней назад Мастер говорил: «{oldest['summary']}». "
        f"Если уместно — вскользь спроси как дела с этим. Не навязывайся."
    )
