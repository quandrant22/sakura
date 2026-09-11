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
from config import MAIN_MODEL

log = logging.getLogger("sakura.autonomous")


_tables_ready = False

def _ensure_tables():
    global _tables_ready
    if _tables_ready:
        return
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
    _tables_ready = True


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

    interests = get_sakura_interests()
    if not interests:
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

    from memory.db import _conn
    prev = _conn().execute(
        "SELECT content FROM news_digest WHERE sent=1 ORDER BY id DESC LIMIT 5"
    ).fetchall()
    recent_block = ""
    if prev:
        joined = "\n".join(f"— {r['content'][:120]}" for r in prev)
        recent_block = (
            f"\nТы уже писала это раньше — не повторяй формулировки и заходы:\n{joined}\n"
        )

    prompt = (
        f"Интересы Мастера: {', '.join(interests[:3])}\n\n"
        f"Найденные материалы:\n{found_text}\n\n"
        f"{recent_block}"
        "Напиши короткую 'утреннюю сводку' от Сакуры — как бы рассказала подруга, "
        "не сухой дайджест. 3-4 предложения. Выбери самое интересное. "
        "Начни как тебе естественно, без шаблонных зачинов."
    )

    try:
        from main import ask_gemini
        digest = await ask_gemini(prompt, save_history=False)
        if not digest:
            return ""

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
_pause_start: Optional[float] = None
_PAUSE_RESET_MIN = 10
_SPRINT_THRESHOLD_MIN = 90   # 1.5 часа без перерыва → предупреждение
_SPRINT_CPU_MIN = 30          # минимальный CPU% для «работы»


def update_sprint(cpu_percent: float, active_window: str) -> Optional[str]:
    """
    Обновляет статус рабочего спринта.
    Возвращает сообщение для Мастера если пора напомнить о перерыве.
    """
    global _sprint_start, _sprint_alerted, _pause_start

    is_working = (
        cpu_percent >= _SPRINT_CPU_MIN or
        any(w in active_window.lower() for w in
            ("code", "visual studio", "pycharm", "vim", "terminal", "cmd", "powershell"))
    )

    if is_working:
        _pause_start = None
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
        # Пауза — сбрасываем спринт если пауза длится дольше лимита
        if _pause_start is None:
            _pause_start = time.monotonic()
        elif (time.monotonic() - _pause_start) / 60 > _PAUSE_RESET_MIN:
            _sprint_start   = None
            _sprint_alerted = False

    return None


# ── №39: Голосовые заметки ────────────────────────────────────────────

_NOTE_KEYWORDS = (
    "запомни идею", "запиши идею", "сохрани идею",
    "сделай заметку", "запиши заметку",
    "не забудь записать", "запиши это",
)


def is_voice_note_request(text: str) -> bool:
    from modules.fuzzy import phrase_has_any
    return phrase_has_any(text.lower(), _NOTE_KEYWORDS)


async def save_voice_note(raw_text: str) -> str:
    """
    Структурирует голосовую заметку и сохраняет.
    Возвращает подтверждение.
    """
    _ensure_tables()

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
        from main import ask_gemini
        digest_structured = await ask_gemini(prompt, save_history=False)
        structured = (digest_structured or "").strip() or raw_text
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