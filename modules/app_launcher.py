"""
modules/app_launcher.py — Умный запуск приложений.

Расширяет device_commands.py:
  - Запоминает какие приложения используются в какое время
  - Предлагает умные дефолты (утром → браузер, вечером → Steam)
  - Учит новые ассоциации от Мастера
  - Предсказывает что может понадобиться

Хранение: таблица app_usage в sakura.db.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("sakura.app_launcher")

# Умные дефолты по времени суток
TIME_DEFAULTS = {
    "morning":   {"primary": "browser", "secondary": "telegram"},
    "afternoon": {"primary": "code", "secondary": "browser"},
    "evening":   {"primary": "steam", "secondary": "discord"},
    "night":     {"primary": "browser", "secondary": "music"},
}

# Дни недели → типичные активности
WEEKDAY_ACTIVITY = {
    0: "work",    # пн
    1: "work",    # вт
    2: "work",    # ср
    3: "work",    # чт
    4: "work",    # пт
    5: "gaming",  # сб
    6: "gaming",  # вс
}


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_usage (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name    TEXT    NOT NULL,
            hour        INTEGER NOT NULL,
            weekday     INTEGER NOT NULL,
            count       INTEGER DEFAULT 1,
            last_used   TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_usage_time
        ON app_usage(app_name, hour, weekday)
    """)
    conn.commit()


def record_launch(app_name: str):
    """Записать запуск приложения."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()

        # Проверяем есть ли уже запись
        existing = conn.execute("""
            SELECT id, count FROM app_usage
            WHERE app_name = ? AND hour = ? AND weekday = ?
        """, (app_name, hour, weekday)).fetchone()

        if existing:
            conn.execute("""
                UPDATE app_usage
                SET count = count + 1, last_used = datetime('now')
                WHERE id = ?
            """, (existing["id"],))
        else:
            conn.execute("""
                INSERT INTO app_usage (app_name, hour, weekday)
                VALUES (?, ?, ?)
            """, (app_name, hour, weekday))

        conn.commit()
    except Exception as e:
        log.error(f"[app_launcher] Ошибка записи: {e}")


def get_smart_default() -> Optional[str]:
    """
    Умный дефолт: какое приложение вероятнее всего нужно сейчас.
    Используется когда Мастер говорит «открой что-нибудь».
    """
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()

        # Ищем самое частое приложение для этого времени
        row = conn.execute("""
            SELECT app_name, SUM(count) as total
            FROM app_usage
            WHERE hour BETWEEN ? AND ?
            GROUP BY app_name
            ORDER BY total DESC
            LIMIT 1
        """, (max(0, hour - 1), min(23, hour + 1))).fetchone()

        if row:
            return row["app_name"]

        # Фолбэк на время суток
        if 6 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 22:
            period = "evening"
        else:
            period = "night"

        return TIME_DEFAULTS.get(period, {}).get("primary")

    except Exception:
        return None


def get_usage_stats(app_name: str, days: int = 30) -> dict:
    """Статистика использования приложения."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        since = (datetime.now() - timedelta(days=days)).isoformat()
        row = conn.execute("""
            SELECT SUM(count) as total, MAX(last_used) as last
            FROM app_usage
            WHERE app_name = ? AND last_used > ?
        """, (app_name, since)).fetchone()

        return {
            "total": row["total"] or 0,
            "last_used": row["last"],
        }
    except Exception:
        return {"total": 0, "last_used": None}


def get_top_apps(days: int = 7, limit: int = 10) -> list[dict]:
    """Топ приложений за период."""
    try:
        from memory.db import _conn
        _ensure_table()
        conn = _conn()

        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT app_name, SUM(count) as total
            FROM app_usage
            WHERE last_used > ?
            GROUP BY app_name
            ORDER BY total DESC
            LIMIT ?
        """, (since, limit)).fetchall()

        return [{"app": r["app_name"], "count": r["total"]} for r in rows]
    except Exception:
        return []


def get_context_for_prompt() -> str:
    """Краткая статистика для промпта."""
    try:
        top = get_top_apps(days=7, limit=3)
        if not top:
            return ""

        apps_str = ", ".join(f"{a['app']}({a['count']})" for a in top)
        return f"ЧАСТЫЕ ПРИЛОЖЕНИЯ: {apps_str}"
    except Exception:
        return ""
