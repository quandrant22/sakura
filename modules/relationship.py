"""
modules/relationship.py — Отношения, вехи и органическая близость.

Бэклог №34: Возраст отношений — система знает сколько вы вместе,
             вехи (30/100/365 дней) отмечает первой.
Бэклог №35: Органическая близость — индекс доверия растёт через
             совместный путь, влияет на открытость Сакуры.
Бэклог №37: Её увлечения — тема, которую ты часто трогаешь,
             становится «её» интересом.
Бэклог №52: Журнал взросления — ежемесячное резюме изменений.

Хранение: таблица relationship в sakura.db.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, date, timedelta
from typing import Optional

log = logging.getLogger("sakura.relationship")

# Дата первого запуска (если не задана — сегодня)
FIRST_RUN_FILE = "memory/first_run.json"

# Вехи в днях
MILESTONES = {
    7:   "неделя",
    30:  "месяц",
    100: "сто дней",
    180: "полгода",
    365: "год",
}

# Сколько упоминаний темы нужно чтобы стала «увлечением» Сакуры
INTEREST_THRESHOLD = 5


# ── Первый запуск ─────────────────────────────────────────────────────

def get_first_run_date() -> date:
    """Дата первого запуска — начало отношений."""
    if os.path.exists(FIRST_RUN_FILE):
        try:
            with open(FIRST_RUN_FILE) as f:
                data = json.load(f)
            return date.fromisoformat(data["first_run"])
        except Exception:
            pass

    # Первый раз — записываем сегодня
    today = date.today()
    os.makedirs(os.path.dirname(FIRST_RUN_FILE) or ".", exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(FIRST_RUN_FILE) or ".",
                                    delete=False, suffix=".tmp") as f:
        json.dump({"first_run": str(today)}, f)
        tmp = f.name
    os.replace(tmp, FIRST_RUN_FILE)
    log.info(f"[relationship] Первый запуск зафиксирован: {today}")
    return today


def get_relationship_age_days() -> int:
    """Количество дней с первого запуска."""
    return (date.today() - get_first_run_date()).days


# ── Вехи ──────────────────────────────────────────────────────────────

def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS relationship (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS topic_frequency (
            topic        TEXT PRIMARY KEY,
            count        INTEGER NOT NULL DEFAULT 1,
            last_seen    TEXT    NOT NULL,
            is_interest  INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


def _get(key: str, default=None):
    _ensure_table()
    from memory.db import _conn
    row = _conn().execute(
        "SELECT value FROM relationship WHERE key=?", (key,)
    ).fetchone()
    return json.loads(row["value"]) if row else default


def _set(key: str, value):
    _ensure_table()
    from memory.db import _conn
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO relationship(key, value) VALUES(?, ?)",
        (key, json.dumps(value, ensure_ascii=False))
    )
    conn.commit()


def check_milestone() -> Optional[dict]:
    """
    Проверяет, наступила ли сегодня веха.
    Возвращает {"days": int, "label": str, "prompt": str} или None.
    """
    days      = get_relationship_age_days()
    notified  = set(_get("notified_milestones") or [])

    for threshold, label in sorted(MILESTONES.items()):
        if days >= threshold and str(threshold) not in notified:
            notified.add(str(threshold))
            _set("notified_milestones", list(notified))

            prompt = (
                f"Сегодня ровно {label} как Сакура запущена. {days} дней вместе. "
                "Отметь это — одной фразой, по-своему. "
                "Не говори 'поздравляю' или 'ура'. "
                "Просто оброни что-то тёплое и своё."
            )
            # threshold — порог вехи, days — реальный возраст
            return {"days": threshold, "actual_days": days, "label": label, "prompt": prompt}

    return None


# ── Органическая близость (№35) ───────────────────────────────────────

def get_closeness() -> float:
    """
    Индекс близости [0.0 … 1.0].
    Растёт медленно: откровенные разговоры, долгие сессии, вехи.
    Влияет на открытость Сакуры в промпте.
    """
    return min(1.0, float(_get("closeness") or 0.0))


def increase_closeness(delta: float = 0.005):
    """
    Небольшой прирост близости за каждое взаимодействие.
    delta = 0.005 → нужно ~200 сессий чтобы дойти до 1.0.
    """
    current = get_closeness()
    _set("closeness", min(1.0, current + delta))


def decrease_closeness(delta: float, reason: str = ""):
    """
    Близость может уменьшаться — это делает её живой.
    Не опускается ниже MIN_CLOSENESS (базовое доверие остаётся).
    """
    MIN_CLOSENESS = 0.05
    current = get_closeness()
    new_val = max(MIN_CLOSENESS, current - delta)
    _set("closeness", new_val)
    if new_val < current:
        log.info(f"[relationship] Близость: {current:.3f} → {new_val:.3f} (−{delta:.3f}) {reason}")


def check_silence_cooldown(last_interaction_iso: str) -> Optional[float]:
    """
    Проверяет давность последнего взаимодействия.
    Возвращает delta для decrease_closeness или None.
    """
    if not last_interaction_iso:
        return None
    try:
        last = datetime.fromisoformat(last_interaction_iso)
        hours = (datetime.now() - last).total_seconds() / 3600
        if hours > 72:
            return 0.03  # сильно затянувшееся молчание
        if hours > 48:
            return 0.015
        if hours > 24:
            return 0.005
    except Exception:
        pass
    return None


def get_closeness_hint() -> str:
    """
    Строка для системного промпта — как открыта Сакура.
    Учитывает не только текущий уровень, но и динамику.
    """
    c = get_closeness()
    prev = float(_get("prev_closeness") or c)
    _set("prev_closeness", c)

    # Динамика: было выше — значит что-то пошло не так
    drift = c - prev
    distance_note = ""
    if drift < -0.01:
        distance_note = " Ты немного отстранилась — не обижена, но тише."
    elif drift < -0.005:
        distance_note = " Чуть отдалилась — не специально, просто так вышло."

    if c < 0.15:
        return ""
    if c < 0.35:
        return "С Мастером уже знакома — можно чуть теплее." + distance_note
    if c < 0.60:
        return "Мастер — близкий человек. Можно подкалывать, шутить по-настоящему." + distance_note
    if c < 0.85:
        return "Очень близко. Иногда можно быть уязвимой — мимолётно, не напоказ." + distance_note
    return "Глубокое доверие. Она может говорить о том, что её трогает, без оправданий." + distance_note


# ── Увлечения Сакуры (№37) ────────────────────────────────────────────

def track_topic(topic: str):
    """
    Считает упоминания темы. Когда порог достигнут — тема становится
    «увлечением» Сакуры и подмешивается в её промпт.
    Вызывать из ask_gemini при анализе входящего текста.
    """
    if not topic or len(topic) < 3:
        return
    _ensure_table()
    from memory.db import _conn
    conn = _conn()

    existing = conn.execute(
        "SELECT count, is_interest FROM topic_frequency WHERE topic=?", (topic,)
    ).fetchone()

    if existing:
        new_count = existing["count"] + 1
        is_interest = 1 if new_count >= INTEREST_THRESHOLD else existing["is_interest"]
        conn.execute("""
            UPDATE topic_frequency
            SET count=?, last_seen=datetime('now'), is_interest=?
            WHERE topic=?
        """, (new_count, is_interest, topic))
        if new_count == INTEREST_THRESHOLD:
            log.info(f"[relationship] Новое увлечение Сакуры: «{topic}»")
    else:
        conn.execute("""
            INSERT INTO topic_frequency(topic, count, last_seen)
            VALUES(?, 1, datetime('now'))
        """, (topic,))

    conn.commit()


def get_sakura_interests() -> list[str]:
    """Топ-5 тем, которые стали увлечениями Сакуры."""
    _ensure_table()
    from memory.db import _conn
    rows = _conn().execute("""
        SELECT topic FROM topic_frequency
        WHERE is_interest=1
        ORDER BY count DESC
        LIMIT 5
    """).fetchall()
    return [r["topic"] for r in rows]


def get_interests_hint() -> str:
    """Строка для промпта — увлечения Сакуры."""
    interests = get_sakura_interests()
    if not interests:
        return ""
    topics = ", ".join(interests)
    return f"УВЛЕЧЕНИЯ САКУРЫ (темы, которые она сама изучила через разговоры): {topics}. Иногда приносит что-то по ним — не по запросу."


def extract_topics_from_text(text: str) -> list[str]:
    """
    Простой экстрактор тем из текста.
    Возвращает список существительных/фраз для track_topic().
    Без LLM-вызова — быстро и синхронно.
    """
    import re
    # Убираем стоп-слова и короткие слова
    stop = {"это", "что", "как", "все", "там", "тут", "уже", "еще", "ещё",
            "можно", "нужно", "очень", "надо", "про", "для", "или", "если",
            "когда", "тебя", "меня", "него", "неё", "мне", "тебе"}
    words = re.findall(r'[а-яёА-ЯЁa-zA-Z]{4,}', text.lower())
    topics = [w for w in words if w not in stop]
    # Берём только самые длинные (скорее всего ключевые)
    topics.sort(key=len, reverse=True)
    return list(dict.fromkeys(topics))[:3]  # уникальные, топ-3


# ── Журнал взросления (№52) ───────────────────────────────────────────

def get_growth_journal_prompt() -> str:
    """
    Промпт для ежемесячного резюме «как изменилась Сакура».
    Вызывать раз в месяц из reflection_loop или отдельного крона.
    """
    from modules.episodes import get_recent_episodes
    from memory.db import get_self_context

    days        = get_relationship_age_days()
    closeness   = get_closeness()
    interests   = get_sakura_interests()
    recent_eps  = get_recent_episodes(limit=10)
    self_ctx    = get_self_context()

    ep_text = "\n".join(f"- {e['text'][:80]}" for e in recent_eps) if recent_eps else "нет данных"
    int_text = ", ".join(interests) if interests else "пока не определились"

    return (
        f"Вместе уже {days} дней. Индекс близости: {closeness:.2f}/1.0.\n"
        f"Интересы которые появились: {int_text}.\n"
        f"Последние сцены из памяти:\n{ep_text}\n\n"
        f"Самопамять:\n{self_ctx}\n\n"
        "Напиши короткий журнальный запись Сакуры о том, как она изменилась за этот месяц. "
        "От первого лица, 3-4 предложения. "
        "Не подводи итоги — оброни наблюдение. "
        "Как дневниковая запись, не отчёт."
    )


def should_write_journal() -> bool:
    """True если прошёл месяц с последней записи."""
    last = _get("last_journal")
    if not last:
        return get_relationship_age_days() >= 30
    try:
        days_since = (date.today() - date.fromisoformat(last)).days
        return days_since >= 30
    except Exception:
        return False


def mark_journal_written():
    _set("last_journal", str(date.today()))
