"""
modules/capsules.py — Капсулы времени (бэклог №39 + двусторонние).

Мастер прячет сообщение → Сакура вскрывает в нужный день.
Сакура сама прячет наблюдение → вскрывает сама (двусторонние, бэклог-идея).

Команды-триггеры (Мастер):
  «Сакура, спрячь это на месяц»
  «Сакура, запомни это через три месяца»
  «Сакура, напомни мне об этом в декабре»

Двусторонние (Сакура создаёт сама, внутри ask_gemini или proactive_loop):
  create_sakura_capsule(observation, days) — прячет своё наблюдение
  get_due_sakura_capsules()               — возвращает созревшие

Хранение: таблица capsules + sakura_capsules в sakura.db.
Проверка: раз в час в proactive_loop.
"""

import json
import logging
import re
from datetime import datetime, date, timedelta
from typing import Optional

log = logging.getLogger("sakura.capsules")


# ── Таблицы ───────────────────────────────────────────────────────────

def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS capsules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text        TEXT    NOT NULL,
            open_date   TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            opened      INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sakura_capsules (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            observation   TEXT    NOT NULL,
            context       TEXT,
            open_date     TEXT    NOT NULL,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            opened        INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


# ── Парсинг даты вскрытия из запроса ─────────────────────────────────

_MONTH_NAMES = {
    "январе": 1, "январь": 1, "января": 1,
    "феврале": 2, "февраль": 2, "февраля": 2,
    "марте": 3, "март": 3, "марта": 3,
    "апреле": 4, "апрель": 4, "апреля": 4,
    "мае": 5, "май": 5, "мая": 5,
    "июне": 6, "июнь": 6, "июня": 6,
    "июле": 7, "июль": 7, "июля": 7,
    "августе": 8, "август": 8, "августа": 8,
    "сентябре": 9, "сентябрь": 9, "сентября": 9,
    "октябре": 10, "октябрь": 10, "октября": 10,
    "ноябре": 11, "ноябрь": 11, "ноября": 11,
    "декабре": 12, "декабрь": 12, "декабря": 12,
}

_WORD_NUMS = {
    "одну": 1, "одной": 1,
    "две": 2, "двух": 2,
    "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
}

_PERIOD_DAYS = {
    "три недели": 21, "трёх недель": 21,
    "две недели": 14, "двух недель": 14,
    "четыре недели": 28,
    "три месяца": 90, "трёх месяцев": 90,
    "два месяца": 60, "двух месяцев": 60,
    "полгода": 180, "полугода": 180,
    "неделю": 7, "недели": 7, "неделя": 7,
    "месяц": 30, "месяца": 30,
    "год": 365, "года": 365,
}


def parse_open_date(text: str) -> Optional[date]:
    tl = text.lower()

    m = re.search(r"через\s+(.+?)(?:\s+(?:напомни|спрячь|вскрой|открой)|$)", tl)
    if m:
        period = m.group(1).strip()
        for key, days in _PERIOD_DAYS.items():
            if key in period:
                return date.today() + timedelta(days=days)
        for word, num in _WORD_NUMS.items():
            if word in period:
                if "недел" in period:
                    return date.today() + timedelta(weeks=num)
                if "месяц" in period:
                    return date.today() + timedelta(days=30 * num)
                if "год" in period:
                    return date.today() + timedelta(days=365 * num)
        nm = re.search(r"(\d+)\s*(день|дня|дней|недел|месяц|год)", period)
        if nm:
            n    = int(nm.group(1))
            unit = nm.group(2)
            if "недел" in unit:
                return date.today() + timedelta(weeks=n)
            if "месяц" in unit:
                return date.today() + timedelta(days=30 * n)
            if "год" in unit:
                return date.today() + timedelta(days=365 * n)
            return date.today() + timedelta(days=n)

    for name, month in _MONTH_NAMES.items():
        if name in tl:
            target = date.today().replace(month=month, day=1)
            if target <= date.today():
                target = target.replace(year=target.year + 1)
            return target

    if "следующий месяц" in tl or "следующем месяце" in tl:
        return (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)

    if "новый год" in tl:
        return date.today().replace(month=12, day=31)

    return None


def is_capsule_request(text: str) -> bool:
    tl = text.lower()
    triggers = (
        "спрячь", "спрячь это", "запомни это до", "вскрой через",
        "напомни об этом", "капсула", "положи в капсулу",
        "открой через", "письмо себе"
    )
    return any(t in tl for t in triggers)


# ── CRUD — капсулы Мастера ────────────────────────────────────────────

def create_capsule(text: str, open_date: date, created_by: str = "master") -> dict:
    _ensure_table()
    from memory.db import _conn
    conn = _conn()
    cur  = conn.execute(
        "INSERT INTO capsules(text, open_date) VALUES(?, ?)",
        (text.strip(), str(open_date))
    )
    conn.commit()
    log.info(f"[capsules] Создана капсула #{cur.lastrowid}, вскрытие: {open_date}")
    return {"id": cur.lastrowid, "text": text, "open_date": str(open_date)}


def get_due_capsules() -> list:
    _ensure_table()
    from memory.db import _conn
    rows = _conn().execute("""
        SELECT id, text, open_date, created_at
        FROM capsules
        WHERE opened = 0 AND date(open_date) <= date('now')
        ORDER BY open_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def mark_opened(capsule_id: int):
    from memory.db import _conn
    conn = _conn()
    conn.execute("UPDATE capsules SET opened=1 WHERE id=?", (capsule_id,))
    conn.commit()


def get_all_capsules(include_opened: bool = False) -> list:
    _ensure_table()
    from memory.db import _conn
    where = "" if include_opened else "WHERE opened=0"
    rows  = _conn().execute(f"""
        SELECT id, text, open_date, opened, created_at
        FROM capsules {where}
        ORDER BY open_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


# ── CRUD — капсулы Сакуры (двусторонние) ─────────────────────────────

# Триггеры, при которых Сакура решает спрятать наблюдение.
# Проверяются в should_create_sakura_capsule().
_SAKURA_TRIGGERS = [
    # Незавершённые проекты
    ("займусь", 30), ("доделаю", 21), ("потом", 14),
    ("допишу", 21),  ("разберусь", 30), ("позже", 14),
    # Намерения
    ("собираюсь", 30), ("планирую", 30), ("буду", 21),
    # Эмоционально значимое
    ("первый раз", 60), ("впервые", 60), ("никогда не", 45),
]


def should_create_sakura_capsule(user_message: str, reply: str) -> Optional[dict]:
    """
    Проверяет, стоит ли Сакуре спрятать наблюдение в капсулу.
    Возвращает {"observation": str, "days": int} или None.

    Вызывать из extract_and_remember — не создаёт капсулу сама,
    только сигнализирует, что стоит. Финальное решение — в main.py.
    """
    combined = (user_message + " " + reply).lower()
    for keyword, days in _SAKURA_TRIGGERS:
        if keyword in combined:
            # Ограничиваем: не чаще одной капсулы Сакуры в 3 дня
            if _sakura_capsule_recent():
                return None
            observation = user_message[:120].strip()
            return {"observation": observation, "days": days, "trigger": keyword}
    return None


def _sakura_capsule_recent() -> bool:
    """True если Сакура уже создавала капсулу в последние 3 дня."""
    try:
        _ensure_table()
        from memory.db import _conn
        row = _conn().execute(
            "SELECT COUNT(*) FROM sakura_capsules "
            "WHERE created_at > datetime('now', '-3 days')"
        ).fetchone()
        return (row[0] if row else 0) > 0
    except Exception:
        return False


def create_sakura_capsule(observation: str, days: int,
                           context: str = "") -> dict:
    """Сакура прячет своё наблюдение. context — краткий контекст разговора."""
    _ensure_table()
    from memory.db import _conn
    conn      = _conn()
    open_date = date.today() + timedelta(days=days)
    cur       = conn.execute(
        "INSERT INTO sakura_capsules(observation, context, open_date) VALUES(?,?,?)",
        (observation[:200], context[:100], str(open_date))
    )
    conn.commit()
    log.info(f"[capsules] Сакура спрятала наблюдение #{cur.lastrowid}, вскрытие: {open_date}")
    return {"id": cur.lastrowid, "observation": observation, "open_date": str(open_date)}


def get_due_sakura_capsules() -> list:
    """Капсулы Сакуры, которые пора вскрыть."""
    _ensure_table()
    from memory.db import _conn
    rows = _conn().execute("""
        SELECT id, observation, context, open_date, created_at
        FROM sakura_capsules
        WHERE opened = 0 AND date(open_date) <= date('now')
        ORDER BY open_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def mark_sakura_opened(capsule_id: int):
    from memory.db import _conn
    conn = _conn()
    conn.execute("UPDATE sakura_capsules SET opened=1 WHERE id=?", (capsule_id,))
    conn.commit()


# ── Промпты для открытия ─────────────────────────────────────────────

def make_open_prompt(capsule: dict) -> str:
    created    = capsule.get("created_at", "")[:10]
    open_d     = capsule.get("open_date", "")
    days_passed = 0
    try:
        days_passed = (date.fromisoformat(open_d) - date.fromisoformat(created)).days
    except Exception:
        pass
    return (
        f"Сегодня открывается капсула времени, которую мы с Мастером спрятали {days_passed} дней назад.\n"
        f"Сообщение внутри: «{capsule['text']}»\n\n"
        "Напиши как Сакура открывает капсулу — одна фраза перед текстом и одна после. "
        "Не пафосно. Как будто нашла старую заметку в кармане."
    )


def make_sakura_open_prompt(capsule: dict) -> str:
    """Промпт для вскрытия капсулы Сакуры."""
    created    = capsule.get("created_at", "")[:10]
    open_d     = capsule.get("open_date", "")
    days_passed = 0
    try:
        days_passed = (date.fromisoformat(open_d) - date.fromisoformat(created)).days
    except Exception:
        pass
    obs     = capsule.get("observation", "")
    context = capsule.get("context", "")
    return (
        f"{days_passed} дней назад ты спрятала наблюдение о Мастере: «{obs}»\n"
        + (f"Контекст тогда: {context}\n" if context else "")
        + "\nСейчас это наблюдение созрело. Напиши одно-два предложения — "
        "проверь, сбылось ли оно, изменилось ли что-то. "
        "Говори как будто вспомнила что-то своё, не объясняй что это 'капсула'. "
        "Тон — живой, чуть удивлённый или задумчивый."
    )


def make_create_prompt(open_date: date) -> str:
    delta = (open_date - date.today()).days
    if delta >= 365:
        when = f"через {delta // 365} {'год' if delta // 365 == 1 else 'года'}"
    elif delta >= 30:
        when = f"через {delta // 30} {'месяц' if delta // 30 == 1 else 'месяца'}"
    else:
        when = f"через {delta} дней"
    return f"Капсула спрятана. Вскроем {when} — {open_date.strftime('%d.%m.%Y')}."