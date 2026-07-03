"""
modules/speech_style.py — Перенимает словечки Мастера (бэклог №50).

Анализирует часто используемые слова и выражения Мастера.
Сакура постепенно начинает их использовать — со своим оттенком,
иногда с лёгкой иронией.

Хранение: таблица speech_patterns в sakura.db.
Обновляется при каждом сообщении от Мастера.
"""

import logging
import re
from collections import Counter
from typing import Optional

log = logging.getLogger("sakura.speech_style")

# Стоп-слова — не перенимаем
_STOP = {
    "это", "что", "как", "все", "там", "тут", "уже", "ещё", "еще",
    "можно", "нужно", "очень", "надо", "про", "для", "или", "если",
    "когда", "тебя", "меня", "него", "неё", "мне", "тебе", "себя",
    "они", "мы", "вы", "он", "она", "оно", "его", "её", "их",
    "так", "вот", "ну", "да", "нет", "эт", "ты", "я", "и", "в",
    "на", "с", "по", "из", "за", "до", "не", "а", "но", "то",
    "просто", "вообще", "типа", "блин", "ладно", "окей", "ок",
}

# Порог для «усвоения» словечка
_ADOPT_THRESHOLD = 7   # встречается N раз → Сакура начинает использовать
_MAX_ADOPTED     = 15  # максимум усвоенных слов


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS speech_patterns (
            word     TEXT    PRIMARY KEY,
            count    INTEGER NOT NULL DEFAULT 1,
            adopted  INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT  NOT NULL DEFAULT (date('now')),
            last_seen  TEXT  NOT NULL DEFAULT (date('now'))
        );
    """)
    conn.commit()


def track_message(text: str):
    """
    Анализирует сообщение Мастера, обновляет счётчики слов.
    Вызывать при каждом входящем сообщении.
    """
    _ensure_table()
    from memory.db import _conn

    # Извлекаем слова: только кириллица длиннее 4 символов
    words = re.findall(r'[а-яёА-ЯЁ]{4,}', text.lower())
    words = [w for w in words if w not in _STOP]
    if not words:
        return

    conn = _conn()
    for word in set(words):   # уникальные из сообщения
        existing = conn.execute(
            "SELECT count FROM speech_patterns WHERE word=?", (word,)
        ).fetchone()
        if existing:
            new_count = existing["count"] + 1
            adopted   = 1 if new_count >= _ADOPT_THRESHOLD else 0
            conn.execute("""
                UPDATE speech_patterns
                SET count=?, last_seen=date('now'), adopted=?
                WHERE word=?
            """, (new_count, adopted, word))
        else:
            conn.execute(
                "INSERT INTO speech_patterns(word, count) VALUES(?, 1)", (word,)
            )
    conn.commit()


def get_adopted_words() -> list[str]:
    """Список слов которые Сакура уже «усвоила»."""
    try:
        _ensure_table()
        from memory.db import _conn
        rows = _conn().execute("""
            SELECT word FROM speech_patterns
            WHERE adopted=1
            ORDER BY count DESC
            LIMIT ?
        """, (_MAX_ADOPTED,)).fetchall()
        return [r["word"] for r in rows]
    except Exception:
        return []


def get_style_hint() -> str:
    """
    Подсказка для промпта — какие словечки Мастера Сакура переняла.
    """
    words = get_adopted_words()
    if not words:
        return ""
    sample = words[:5]
    return (
        f"СТИЛЬ РЕЧИ: Мастер часто использует слова: {', '.join(sample)}. "
        "Ты постепенно переняла некоторые из них — используй их естественно "
        "в своей речи, иногда с лёгкой иронией. Не переусердствуй."
    )


def get_stats() -> dict:
    """Статистика для диагностики."""
    try:
        _ensure_table()
        from memory.db import _conn
        total   = _conn().execute("SELECT COUNT(*) FROM speech_patterns").fetchone()[0]
        adopted = _conn().execute("SELECT COUNT(*) FROM speech_patterns WHERE adopted=1").fetchone()[0]
        return {"total_words": total, "adopted": adopted}
    except Exception:
        return {}