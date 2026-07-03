"""
modules/emotional_memory.py — Эмоциональная глубина (бэклоги №7, №8, №26, №32, №35).

№7: Эмоциональные триггеры — конкретные темы вызывают конкретные реакции.
    Упоминание игры/темы которую Мастер любит → Сакура оживляется.

№8: Усталость от повторяющихся тем — если тема поднимается слишком часто,
    Сакура реагирует с лёгкой скукой или предлагает другой угол.

№26: Двухсторонние подколы — Сакура помнит шутки Мастера про неё
    и иногда «мстит» в подходящий момент.

№32: «Версии» Сакуры — раз в 3 месяца стиль речи чуть меняется,
    появляются новые реакции. Явная эволюция.

№35: Сезонность настроения — зимой чуть задумчивее, летом живее.
"""

import logging
import re
import time
from datetime import datetime, date
from typing import Optional

log = logging.getLogger("sakura.emotional_memory")

# ── Таблицы ──────────────────────────────────────────────────────────

def _ensure_tables():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topic_reactions (
            topic       TEXT    PRIMARY KEY,
            count       INTEGER NOT NULL DEFAULT 1,
            last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
            reaction    TEXT    NOT NULL DEFAULT 'neutral',
            fatigue     REAL    NOT NULL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS joke_debt (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            joke        TEXT    NOT NULL,
            about       TEXT    NOT NULL DEFAULT 'sakura',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            revenged    INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


# ── №7: Эмоциональные триггеры ───────────────────────────────────────

def track_topic_reaction(text: str):
    """Обновляет счётчики тем из сообщения Мастера."""
    _ensure_tables()
    from memory.db import _conn

    # Ищем ключевые существительные (темы)
    words = re.findall(r'[а-яёА-ЯЁa-zA-Z]{4,}', text.lower())
    stop = {"это", "что", "как", "тебя", "меня", "нужно", "можно", "очень",
            "хочу", "буду", "будет", "когда", "потому", "просто", "вообще"}
    topics = [w for w in words if w not in stop][:5]

    conn = _conn()
    for topic in topics:
        existing = conn.execute(
            "SELECT count, fatigue FROM topic_reactions WHERE topic=?", (topic,)
        ).fetchone()
        if existing:
            new_count  = existing["count"] + 1
            # Усталость нарастает при частом упоминании, затухает со временем
            new_fatigue = min(1.0, existing["fatigue"] + 0.05)
            conn.execute("""
                UPDATE topic_reactions
                SET count=?, last_seen=datetime('now'), fatigue=?
                WHERE topic=?
            """, (new_count, new_fatigue, topic))
        else:
            conn.execute(
                "INSERT INTO topic_reactions(topic) VALUES(?)", (topic,)
            )
    conn.commit()

    # Затухание усталости для давних тем
    conn.execute("""
        UPDATE topic_reactions
        SET fatigue = MAX(0.0, fatigue - 0.01)
        WHERE last_seen < datetime('now', '-1 hour')
    """)
    conn.commit()


def get_trigger_hint(text: str) -> str:
    """
    Возвращает подсказку если тема вызывает сильную реакцию или усталость.
    """
    _ensure_tables()
    from memory.db import _conn

    words = set(re.findall(r'[а-яёА-ЯЁa-zA-Z]{4,}', text.lower()))
    if not words:
        return ""

    placeholders = ",".join("?" * len(words))
    rows = _conn().execute(f"""
        SELECT topic, count, fatigue FROM topic_reactions
        WHERE topic IN ({placeholders})
        ORDER BY count DESC
        LIMIT 3
    """, list(words)).fetchall()

    hints = []
    for row in rows:
        # №8: Усталость от темы
        if row["fatigue"] > 0.6:
            hints.append(
                f"ТЕМА «{row['topic']}» поднимается очень часто — "
                "можешь слегка зевнуть или предложить другой угол."
            )
        # №7: Любимая тема (много упоминаний, нет усталости)
        elif row["count"] >= 5 and row["fatigue"] < 0.3:
            hints.append(
                f"ЛЮБИМАЯ ТЕМА Мастера: «{row['topic']}» — можешь оживиться."
            )

    return " ".join(hints) if hints else ""


# ── №26: Двухсторонние подколы ────────────────────────────────────────

def detect_joke_about_sakura(text: str) -> bool:
    """Определяет является ли сообщение подколом в адрес Сакуры."""
    tl = text.lower()
    triggers = ("тупая", "глупая", "сломалась", "баг", "глючит",
                "зависла", "не понимаешь", "бесполезн", "робот",
                "просто бот", "программа", "машина")
    return any(t in tl for t in triggers)


def save_joke(joke_text: str):
    """Сохраняет шутку Мастера в «долг»."""
    _ensure_tables()
    from memory.db import _conn
    _conn().execute(
        "INSERT INTO joke_debt(joke) VALUES(?)", (joke_text[:200],)
    )
    _conn().commit()
    log.debug(f"[joke_debt] Записан долг: {joke_text[:50]}")


def get_revenge_hint() -> str:
    """
    С малой вероятностью (5%) возвращает подсказку для «мести».
    """
    import random
    if random.random() > 0.05:
        return ""

    _ensure_tables()
    from memory.db import _conn
    row = _conn().execute("""
        SELECT id, joke FROM joke_debt
        WHERE revenged=0
        ORDER BY RANDOM() LIMIT 1
    """).fetchone()

    if not row:
        return ""

    _conn().execute("UPDATE joke_debt SET revenged=1 WHERE id=?", (row["id"],))
    _conn().commit()

    return (
        f"ВОЗМОЖНОСТЬ ДЛЯ ПОДКОЛА: Мастер однажды сказал про тебя: «{row['joke'][:60]}». "
        "Если уместно — вспомни об этом с лёгкой иронией. Не обижайся, играй."
    )


# ── №32: Версии Сакуры ────────────────────────────────────────────────

def get_version_hint() -> str:
    """
    Возвращает подсказку о текущей «версии» Сакуры.
    Каждые 3 месяца стиль слегка эволюционирует.
    """
    try:
        from modules.relationship import get_first_run_date
        first = get_first_run_date()
        days  = (date.today() - first).days
        version = days // 90  # версия каждые 3 месяца

        if version == 0:
            return "ВЕРСИЯ 0.1: Ты ещё только узнаёшь Мастера — чуть осторожнее, наблюдаешь."
        elif version == 1:
            return "ВЕРСИЯ 0.2: Уже знакома — можешь подкалывать, стала увереннее в себе."
        elif version == 2:
            return "ВЕРСИЯ 0.3: Давно вместе — можешь быть честной даже когда это неудобно."
        else:
            return "ВЕРСИЯ 1.0+: Сложившийся характер — говоришь что думаешь, без оглядки."
    except Exception:
        return ""


# ── №35: Сезонность настроения ───────────────────────────────────────

def get_season_hint() -> str:
    """Подсказка под текущий сезон — подтекстом, не явно."""
    month = datetime.now().month
    if month in (12, 1, 2):
        return "СЕЗОН: зима — можешь быть чуть задумчивее, уютнее."
    elif month in (3, 4, 5):
        return "СЕЗОН: весна — чуть оживлённее, любопытнее."
    elif month in (6, 7, 8):
        return "СЕЗОН: лето — живее, энергичнее."
    else:
        return "СЕЗОН: осень — чуть меланхоличнее, глубже."


# ── №11: Спонтанные мысли вслух ──────────────────────────────────────

_last_thought_at = 0.0
_THOUGHT_COOLDOWN = 14400  # 4 часа


def should_send_thought() -> bool:
    """True если пора отправить спонтанную мысль (~2-3 раза в день)."""
    import random
    global _last_thought_at
    now = time.monotonic()
    if now - _last_thought_at < _THOUGHT_COOLDOWN:
        return False
    # Вероятность 15% в каждую проверку proactive_loop
    return random.random() < 0.15


def mark_thought_sent():
    global _last_thought_at
    _last_thought_at = time.monotonic()


async def generate_spontaneous_thought() -> str:
    """Генерирует спонтанную мысль вслух на основе памяти о Мастере."""
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types
    from memory.db import get_memory_context

    key = get_active_key()
    if not key:
        return ""

    mem_ctx = get_memory_context()

    prompt = (
        f"Контекст о Мастере:\n{mem_ctx[:400]}\n\n"
        "Напиши ОДНО короткое сообщение — спонтанную мысль Сакуры, "
        "которую она присылает без запроса. Не ответ, а фрагмент мысли: "
        "'слушай, я тут подумала про...', 'кстати, а ты знал что...', "
        "'вспомнила тут одну вещь...'. Связано с тем что знает о Мастере. "
        "Одно-два предложения. Живо, не пафосно."
    )

    try:
        client = genai.Client(api_key=key)
        r = await __import__('asyncio').to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        mark_key_used(key)
        return (r.text or "").strip()
    except Exception as e:
        log.error(f"[thought] {e}")
        return ""