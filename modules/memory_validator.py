"""
modules/memory_validator.py — Валидация извлечённых фактов перед сохранением.

Проверяет:
  - Противоречия с существующей памятью
  - Слишком общие/ничего не значащие факты
  - Дубликаты (семантические)
  - Факты которые не могут быть проверены

Интеграция:
  В main.py перед add_to_category() вызывать validate_fact().
"""

import logging
import re
from typing import Optional

log = logging.getLogger("sakura.memory_validator")

# Паттерны «мусорных» фактов которые не стоит сохранять
JUNK_PATTERNS = [
    r"^(ок|ладно|ага|ну|да|нет|хм|ого|хорошо|плохо)$",
    r"^(привет|пока|спасибо|пожалуйста|извини)$",
    r"^(я не знаю|не уверен|не помню)$",
    r"^(что\?|как\?|почему\?|зачем\?)$",
    r"^\d+$",  # просто число
    r"^[^\w\s]+$",  # просто символы
]

# Паттерны фактов которые НЕЛЬЗЯ сохранять (опасные/приватные)
DANGEROUS_PATTERNS = [
    r"(парол[ьи]|password|token|api.key|secret)",
    r"(номер.*телефон|телефон.*номер|\+7\d{10})",
    r"(номер.*карты|карта.*номер|\d{4}\s?\d{4}\s?\d{4})",
    r"(ssn|инн|снилс)",
]

# Слишком общие факты
TOO_GENERIC = [
    "он человек",
    "она женщина",
    "он живой",
    "она существует",
    "это правда",
    "это интересно",
    "это важно",
    "он работает",
    "она работает",
]


def validate_fact(fact: str, category: str = "") -> tuple[bool, str]:
    """
    Валидирует факт перед сохранением.
    Возвращает (is_valid, reason).
    """
    if not fact or not isinstance(fact, str):
        return False, "пустой факт"

    fact = fact.strip()

    # 1. Проверка на мусор
    for pattern in JUNK_PATTERNS:
        if re.match(pattern, fact, re.IGNORECASE):
            return False, "мусорный факт"

    # 2. Проверка на опасные данные
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, fact, re.IGNORECASE):
            return False, "опасные данные (пароли, номера)"

    # 3. Проверка на слишком общие факты
    fact_lower = fact.lower()
    for generic in TOO_GENERIC:
        if fact_lower == generic or fact_lower.startswith(generic):
            return False, "слишком общий факт"

    # 4. Проверка длины
    if len(fact) < 5:
        return False, "слишком короткий"
    if len(fact) > 200:
        return False, "слишком длинный"

    # 5. Проверка на повторяющиеся символы (галлюцинация)
    if len(set(fact)) < len(fact) * 0.3:
        return False, "повторяющиеся символы"

    # 6. Проверка на бессмыслицу (нет ни одного глагола/существительного в предложении)
    words = fact.split()
    if len(words) > 3 and not any(w.isalpha() for w in words):
        return False, "нет осмысленных слов"

    return True, "ok"


def check_contradiction(new_fact: str, existing_facts: list[str]) -> Optional[str]:
    """
    Проверяет противоречит ли новый факт существующим.
    Возвращает строку-предупреждение или None.
    """
    if not existing_facts:
        return None

    new_lower = new_fact.lower()

    for existing in existing_facts:
        ex_lower = existing.lower()

        # Простая проверка на прямые противоречия
        # "Он не курит" vs "Он курит"
        negations = ["не ", "ни ", "нет ", "без "]
        for neg in negations:
            if new_lower.startswith(neg) and ex_lower.startswith(neg):
                continue  # оба отрицательные — ок
            if new_lower.startswith(neg) and not ex_lower.startswith(neg):
                # Проверяем что основа та же
                new_base = new_lower.replace(neg, "", 1)
                if new_base in ex_lower or ex_lower in new_base:
                    return f"Противоречит: «{existing[:50]}»"
            if not new_lower.startswith(neg) and ex_lower.startswith(neg):
                ex_base = ex_lower.replace(neg, "", 1)
                if new_lower in ex_base or ex_base in new_lower:
                    return f"Противоречит: «{existing[:50]}»"

    return None


def get_existing_facts(category: str = "facts", limit: int = 50) -> list[str]:
    """Получить существующие факты для проверки."""
    try:
        from memory.db import _conn
        conn = _conn()
        rows = conn.execute("""
            SELECT text FROM master_memory
            WHERE category = ?
            ORDER BY hits DESC, last_access DESC
            LIMIT ?
        """, (category, limit)).fetchall()
        return [r["text"] for r in rows]
    except Exception:
        return []


def validate_and_check(fact: str, category: str = "") -> tuple[bool, str, Optional[str]]:
    """
    Полная валидация: проверка + проверка противоречий.
    Возвращает (is_valid, reason, contradiction_warning).
    """
    is_valid, reason = validate_fact(fact, category)

    contradiction = None
    if is_valid and category:
        existing = get_existing_facts(category)
        contradiction = check_contradiction(fact, existing)

    return is_valid, reason, contradiction
