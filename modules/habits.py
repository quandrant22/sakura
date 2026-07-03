"""
modules/habits.py — Трекер привычек Мастера.

Отслеживает:
  - Когда ложится / встаёт (по активности в чате)
  - Когда играет (по window_watcher)
  - Когда работает (по окнам/времени)
  - Когда слушает музыку
  - Интенсивность общения по дням/неделям

Хранение: таблица habits в sakura.db.
Инжектится в промпт как краткая статистика.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional

log = logging.getLogger("sakura.habits")

HABIT_TYPES = {
    "sleep":     "сон",
    "wake":      "пробуждение",
    "gaming":    "игры",
    "work":      "работа",
    "music":     "музыка",
    "chat":      "общение",
    "idle":      "бездействие",
}

DAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_type  TEXT    NOT NULL,
            timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
            value       REAL    DEFAULT 1.0,
            metadata    TEXT    DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_habits_type_time
        ON habits(habit_type, timestamp)
    """)
    conn.commit()


def record(habit_type: str, value: float = 1.0, metadata: str = ""):
    """Записать событие привычки."""
    if habit_type not in HABIT_TYPES:
        return
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()
        conn.execute(
            "INSERT INTO habits (habit_type, value, metadata) VALUES (?, ?, ?)",
            (habit_type, value, metadata)
        )
        conn.commit()
    except Exception as e:
        log.error(f"[habits] Ошибка записи: {e}")


def record_from_activity(activity_type: str, window: str = "", metadata: str = ""):
    """Записать на основе активности (вызывать из window_watcher)."""
    type_map = {
        "gaming":   "gaming",
        "work":     "work",
        "music":    "music",
        "chat":     "chat",
        "idle":     "idle",
    }
    habit = type_map.get(activity_type)
    if habit:
        record(habit, metadata=metadata or window)


def record_sleep_event(is_sleep: bool):
    """Зафиксировать ложится/встаёт."""
    record("sleep" if is_sleep else "wake")


def get_habits_summary(days: int = 7) -> str:
    """
    Краткая статистика за N дней для системного промпта.
    Возвращает строку вида:
      Привычки за неделю: ложится ~01:30, встаёт ~10:20. Играет по вечерам.
    """
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT habit_type, timestamp, value
            FROM habits
            WHERE timestamp > ?
            ORDER BY timestamp
        """, (since,)).fetchall()

        if not rows:
            return ""

        by_type = {}
        for r in rows:
            t = r["habit_type"]
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(r)

        lines = []

        # Среднее время сна/подъёма
        sleep_times = []
        wake_times = []
        for r in by_type.get("sleep", []):
            try:
                h = datetime.fromisoformat(r["timestamp"]).hour + datetime.fromisoformat(r["timestamp"]).minute / 60
                sleep_times.append(h)
            except Exception:
                pass
        for r in by_type.get("wake", []):
            try:
                h = datetime.fromisoformat(r["timestamp"]).hour + datetime.fromisoformat(r["timestamp"]).minute / 60
                wake_times.append(h)
            except Exception:
                pass

        if sleep_times:
            avg = sum(sleep_times) / len(sleep_times)
            h, m = int(avg) % 24, int((avg % 1) * 60)
            lines.append(f"Ложится ~{h:02d}:{m:02d}")
        if wake_times:
            avg = sum(wake_times) / len(wake_times)
            h, m = int(avg) % 24, int((avg % 1) * 60)
            lines.append(f"Встаёт ~{h:02d}:{m:02d}")

        # Активность по типам
        gaming_count = len(by_type.get("gaming", []))
        work_count = len(by_type.get("work", []))
        chat_count = len(by_type.get("chat", []))

        if gaming_count > 3:
            lines.append("Много играет")
        if work_count > 5:
            lines.append("Много работает")
        if chat_count > 10:
            lines.append("Активно общается")

        # Самый активный день неделя
        day_counts = [0] * 7
        for r in rows:
            try:
                d = datetime.fromisoformat(r["timestamp"]).weekday()
                day_counts[d] += 1
            except Exception:
                pass
        if any(day_counts):
            max_day = day_counts.index(max(day_counts))
            lines.append(f"Самый активный день: {DAY_NAMES[max_day]}")

        if not lines:
            return ""

        return "ПРИВЫЧКИ (" + str(days) + " дн.): " + "; ".join(lines)

    except Exception as e:
        log.error(f"[habits] Ошибка сводки: {e}")
        return ""


def get_habit_trend(habit_type: str, days: int = 30) -> dict:
    """
    Тренд привычки: растёт, падает, стабильна.
    Возвращает {"trend": "up"|"down"|"stable", "count": int, "avg_per_day": float}
    """
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT timestamp FROM habits
            WHERE habit_type = ? AND timestamp > ?
        """, (habit_type, since)).fetchall()

        if len(rows) < 4:
            return {"trend": "stable", "count": len(rows), "avg_per_day": 0}

        first_half = len(rows) // 2
        second_half = len(rows) - first_half

        avg_first = first_half / (days / 2)
        avg_second = second_half / (days / 2)

        ratio = avg_second / max(avg_first, 0.01)

        if ratio > 1.3:
            trend = "up"
        elif ratio < 0.7:
            trend = "down"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "count": len(rows),
            "avg_per_day": round(len(rows) / days, 2),
        }

    except Exception:
        return {"trend": "stable", "count": 0, "avg_per_day": 0}


def get_context_for_prompt() -> str:
    """Обёртка для _build_system()."""
    summary = get_habits_summary(days=7)
    return summary
