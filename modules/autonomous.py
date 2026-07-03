"""
modules/autonomous.py — Автономность Сакуры (бэклоги №12, №38, №39).

№12: Автономный ресёрч — раз в неделю ищет новости по интересам Мастера
     и готовит «утреннюю сводку» в своём стиле.

№38: Мониторинг рабочих спринтов — через CPU и время суток детектирует
     когда Мастер работает без перерыва. «Ты уже 4 часа без перерыва.»

№39: Голосовые заметки с расшифровкой — Мастер говорит голосом идею,
     Сакура сохраняет в структурированном виде и потом напоминает.
"""

import asyncio
import logging
import time
from datetime import datetime, date, timedelta
from typing import Optional

log = logging.getLogger("sakura.autonomous")


def _ensure_tables():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news_digest (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT    NOT NULL,
            topics      TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (date('now')),
            sent        INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS voice_notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text    TEXT    NOT NULL,
            structured  TEXT    NOT NULL DEFAULT '',
            reminded    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS work_sprints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT    NOT NULL,
            duration_min INTEGER NOT NULL DEFAULT 0,
            alerted     INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


# ── №12: Автономный ресёрч ────────────────────────────────────────────

def should_do_research() -> bool:
    """True если прошли 3 дня с последней сводки."""
    _ensure_tables()
    from memory.db import _conn
    row = _conn().execute("""
        SELECT created_at FROM news_digest
        WHERE sent=1
        ORDER BY created_at DESC LIMIT 1
    """).fetchone()
    if not row:
        return True
    try:
        last = date.fromisoformat(row["created_at"])
        return (date.today() - last).days >= 3
    except Exception:
        return True


async def do_research() -> str:
    """
    Ищет новости по интересам Мастера и готовит сводку в стиле Сакуры.
    """
    _ensure_tables()
    from modules.relationship import get_sakura_interests
    from modules.web_search import search_and_fetch
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    interests = get_sakura_interests()
    if not interests:
        return ""

    key = get_active_key()
    if not key:
        return ""

    # Ищем по топ-3 интересам + случайный неожиданный запрос
    search_results = []
    for topic in interests[:3]:
        try:
            result = await search_and_fetch(f"{topic} новости 2026", max_results=2)
            if result:
                search_results.append(f"[{topic}]: {result[:300]}")
        except Exception:
            pass

    # Иногда добавляем что-то неожиданное
    _surprise_topics = [
        "interesting facts about space 2026",
        "крутое в мире технологий сегодня",
        "открытия в науке недавно",
        "что нового в мире игр",
    ]
    import random
    try:
        surprise = await search_and_fetch(random.choice(_surprise_topics), max_results=1)
        if surprise:
            search_results.append(f"[неожиданное]: {surprise[:200]}")
    except Exception:
        pass

    if not search_results:
        return ""

    found_text = "\n".join(search_results)

    prompt = (
        f"Интересы Мастера: {', '.join(interests[:3])}\n\n"
        f"Найденные материалы:\n{found_text}\n\n"
        "Напиши короткую 'утреннюю сводку' от Сакуры — как бы рассказала подруга, "
        "не сухой дайджест. 3-4 предложения. Выбери самое интересное. "
        "Начни с чего-то вроде 'слушай, нашла кое-что по твоим темам...' "
        "или 'пока ты спал, я тут полазила по интернету...'"
    )

    try:
        client = genai.Client(api_key=key)
        r = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        mark_key_used(key)
        digest = (r.text or "").strip()

        from memory.db import _conn
        _conn().execute(
            "INSERT INTO news_digest(content, topics, sent) VALUES(?, ?, 1)",
            (digest, ", ".join(interests[:3]))
        )
        _conn().commit()
        return digest
    except Exception as e:
        log.error(f"[research] {e}")
        return ""


# ── №38: Мониторинг рабочих спринтов ─────────────────────────────────

_sprint_start: Optional[float] = None
_sprint_alerted = False
_SPRINT_THRESHOLD_MIN = 90   # 1.5 часа без перерыва → предупреждение
_SPRINT_CPU_MIN = 30          # минимальный CPU% для «работы»


def update_sprint(cpu_percent: float, active_window: str) -> Optional[str]:
    """
    Обновляет статус рабочего спринта.
    Возвращает сообщение для Мастера если пора напомнить о перерыве.
    """
    global _sprint_start, _sprint_alerted

    is_working = (
        cpu_percent >= _SPRINT_CPU_MIN or
        any(w in active_window.lower() for w in
            ("code", "visual studio", "pycharm", "vim", "terminal", "cmd", "powershell"))
    )

    if is_working:
        if _sprint_start is None:
            _sprint_start  = time.monotonic()
            _sprint_alerted = False
        elapsed_min = (time.monotonic() - _sprint_start) / 60

        if elapsed_min >= _SPRINT_THRESHOLD_MIN and not _sprint_alerted:
            _sprint_alerted = True
            hours = int(elapsed_min // 60)
            mins  = int(elapsed_min % 60)
            duration = f"{hours}ч {mins}м" if hours else f"{mins} минут"
            return (
                f"РАБОЧИЙ СПРИНТ: Мастер работает {duration} без перерыва. "
                "Мягко намекни что пора отдохнуть. Одно предложение, без нотаций."
            )
    else:
        # Пауза — сбрасываем спринт
        if _sprint_start and (time.monotonic() - _sprint_start) / 60 > 10:
            _sprint_start   = None
            _sprint_alerted = False

    return None


# ── №39: Голосовые заметки ────────────────────────────────────────────

_NOTE_KEYWORDS = ("запомни идею", "идея", "заметка", "запиши", "не забудь записать")


def is_voice_note_request(text: str) -> bool:
    tl = text.lower()
    return any(kw in tl for kw in _NOTE_KEYWORDS)


async def save_voice_note(raw_text: str) -> str:
    """
    Структурирует голосовую заметку и сохраняет.
    Возвращает подтверждение.
    """
    _ensure_tables()
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    key = get_active_key()
    if not key:
        return "Запомнила."

    prompt = (
        f"Голосовая заметка Мастера: «{raw_text}»\n\n"
        "Структурируй эту заметку кратко:\n"
        "- Суть идеи (1 предложение)\n"
        "- Что нужно сделать (если есть)\n"
        "- Теги (через запятую)\n\n"
        "Ответь в формате:\n"
        "СУТЬ: ...\nДЕЙСТВИЕ: ...\nТЕГИ: ..."
    )

    try:
        client = genai.Client(api_key=key)
        r = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        mark_key_used(key)
        structured = (r.text or "").strip()
    except Exception:
        structured = raw_text

    from memory.db import _conn
    _conn().execute(
        "INSERT INTO voice_notes(raw_text, structured) VALUES(?, ?)",
        (raw_text, structured)
    )
    _conn().commit()

    # Сохраняем в общую память
    from memory.db import add_to_category
    add_to_category("notes", f"Идея: {raw_text[:100]}")

    log.info(f"[voice_note] Сохранено: {raw_text[:60]}")
    return "Записала. Напомню когда будет уместно."


def get_unreminded_notes() -> list[dict]:
    """Заметки о которых ещё не напомнили."""
    _ensure_tables()
    from memory.db import _conn
    rows = _conn().execute("""
        SELECT id, raw_text, structured, created_at
        FROM voice_notes
        WHERE reminded=0
        ORDER BY created_at DESC
        LIMIT 3
    """).fetchall()
    return [dict(r) for r in rows]


def mark_reminded(note_id: int):
    from memory.db import _conn
    _conn().execute("UPDATE voice_notes SET reminded=1 WHERE id=?", (note_id,))
    _conn().commit()