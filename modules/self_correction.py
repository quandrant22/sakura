"""
modules/self_correction.py — Самокоррекция: учиться на ошибках.

Отслеживает:
  - Мастер поправил («не так, я имел в виду...»)
  - Сакура извинилась («извини, я не так хотела...»)
  - Неловкость (длинная пауза, повтор вопроса)

Сохраняет в self_memory с тегом `correction`.
Identity model учитывает: «я иногда путаю X и Y».
"""

import logging
import re
from datetime import datetime

log = logging.getLogger("sakura.correction")


# ── Паттерны поправок Мастера ────────────────────────────────────────

_CORRECTION_PATTERNS = [
    r"не так",
    r"не то",
    r"не имел в виду",
    r"не про это",
    r"ты не поняла",
    r"не правильно",
    r"перепутал",
    r"это не",
    r"вообще-то",
    r"на самом деле",
]

# Паттерны извинений Сакуры
_APOLOGY_PATTERNS = [
    r"извини",
    r"прости",
    r"я не так хотела",
    r"я не так подумала",
    r"мне жаль",
    r"ой",
    r"ошиблась",
]


def detect_correction(user_message: str, sakura_reply: str) -> dict | None:
    """
    Определяет, была ли поправка или извинение.
    Возвращает {"type": "correction"|"apology", "text": str} или None.
    """
    text_lower = user_message.lower()

    # Мастер поправил
    for pattern in _CORRECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return {"type": "correction", "text": user_message[:100]}

    # Сакура извинилась
    reply_lower = sakura_reply.lower()
    for pattern in _APOLOGY_PATTERNS:
        if re.search(pattern, reply_lower):
            return {"type": "apology", "text": sakura_reply[:100]}

    return None


def save_correction(correction: dict):
    """Сохраняет коррекцию в self_memory."""
    if not correction:
        return

    try:
        from memory.db import add_to_self

        if correction["type"] == "correction":
            text = f"Мастер поправил меня: «{correction['text'][:60]}». Стоит запомнить."
        else:
            text = f"Я извинилась: «{correction['text'][:60]}». Это было неуклюже."

        add_to_self(text, tag="correction")
        log.debug(f"[correction] Сохранено: {correction['type']}")
    except Exception as e:
        log.error(f"[correction] Ошибка: {e}")


def process_conversation(user_message: str, sakura_reply: str):
    """
    Анализирует диалог на наличие коррекций.
    Вызывать после каждого ответа Сакуры.
    """
    correction = detect_correction(user_message, sakura_reply)
    if correction:
        save_correction(correction)
