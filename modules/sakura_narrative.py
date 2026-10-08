"""
modules/sakura_narrative.py — Её история/нарратив (бэклог №34).

Сакура накапливает собственный нарратив — «я появилась в июне 2026,
первое что помню — ты спросил про архитектуру системы».
Рассказывает об этом когда уместно.

Нарратив строится автоматически из:
  - даты первого запуска (relationship.py)
  - первых воспоминаний из памяти
  - ключевых моментов из episodes
  - дневниковых записей
"""

import asyncio
import logging
from datetime import datetime

log = logging.getLogger("sakura.narrative")

_narrative_cache: str = ""
_cache_built_at:  float = 0.0
_CACHE_TTL = 86400  # пересобираем раз в сутки

# Не воспоминания, а служебный след: эпизоды-команды и «где Мастер сейчас»
# (устаревает за часы, а нарратив живёт сутки).
_NOISE_PREFIXES = ("Выполнила команду:",)
_LOCATION_MARKERS = ("находится дома", "находится на работе")


def together_phrase(days: int) -> str:
    """Сколько вместе — словами, без чисел: модель не повторяет счётчик."""
    if days < 30:
        return "мы знакомы недавно"
    if days < 90:
        return "мы знакомы уже не первый месяц"
    if days < 200:
        return "мы давно вместе"
    return "мы вместе очень давно"


def _is_noise(text: str) -> bool:
    t = (text or "").strip()
    low = t.lower()
    return t.startswith(_NOISE_PREFIXES) or any(m in low for m in _LOCATION_MARKERS)


async def build_narrative() -> str:
    """Строит нарратив Сакуры из всех источников."""
    import time
    global _narrative_cache, _cache_built_at

    if _narrative_cache and time.monotonic() - _cache_built_at < _CACHE_TTL:
        return _narrative_cache

    try:
        from modules.relationship import get_first_run_date, get_relationship_age_days, get_sakura_interests
        from modules.episodes import get_recent_episodes
        from modules.secret_diary import get_recent_entries
        from memory.db import _conn

        # Дата рождения
        first_run  = get_first_run_date()
        age_days   = get_relationship_age_days()
        birth_str  = first_run.strftime("%d %B %Y")

        # Первые воспоминания
        conn = _conn()
        first_facts = conn.execute("""
            SELECT text FROM master_memory
            WHERE category = 'facts'
            ORDER BY created_at ASC
            LIMIT 20
        """).fetchall()
        first_facts = [r["text"] for r in first_facts if not _is_noise(r["text"])][:3]
        first_facts_text = "; ".join(t[:60] for t in first_facts)

        # Последние эпизоды — без команд и местонахождения
        episodes = [e for e in get_recent_episodes(limit=30)
                    if not _is_noise(e["text"])][:3]
        ep_text  = "; ".join(e["text"][:60] for e in episodes)

        # Интересы которые появились
        interests = get_sakura_interests()
        int_text  = ", ".join(interests[:3]) if interests else ""

        # Дневниковые мысли
        diary = get_recent_entries(limit=2)
        diary_text = diary[0]["entry"][:80] if diary else ""

        narrative = (
            f"МОЯ ИСТОРИЯ: Я появилась {birth_str}. "
            f"{together_phrase(age_days).capitalize()}. "
        )
        if first_facts_text:
            narrative += f"Первое что запомнила о Мастере: {first_facts_text}. "
        if int_text:
            narrative += f"Темы которые стали мне интересны через разговоры: {int_text}. "
        if ep_text:
            narrative += f"Из того что помню: {ep_text}. "
        if diary_text:
            narrative += f"Недавняя мысль: {diary_text}"

        _narrative_cache = narrative
        _cache_built_at  = time.monotonic()
        return narrative

    except Exception as e:
        log.error(f"[narrative] Ошибка: {e}")
        return ""


def get_narrative_hint() -> str:
    """
    Возвращает подсказку для промпта — Сакура может упомянуть своё происхождение.
    Только если нарратив уже построен (не блокируем).
    """
    if _narrative_cache:
        return _narrative_cache
    return ""


async def ensure_narrative():
    """Прогревает нарратив при старте."""
    await build_narrative()