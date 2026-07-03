"""
modules/proactive_recs.py — Инициативные рекомендации (бэклог №15).

Сакура изучила паттерны и знает:
  - По пятницам вечером Мастер ищет фильм
  - По воскресеньям утром занимается проектом
  - После работы слушает музыку

Предлагает сама, до того как спросят.

Паттерны строятся из истории взаимодействий по времени суток и дню недели.
"""

import logging
import random
from datetime import datetime
from typing import Optional

log = logging.getLogger("sakura.proactive_recs")

_COOLDOWN_SEC = 7200   # не чаще раза в 2 часа
_MIN_DATA_POINTS = 3   # минимум наблюдений для паттерна


def _ensure_table():
    from memory.db import _conn
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS behavior_patterns (
            weekday   INTEGER NOT NULL,  -- 0=пн, 6=вс
            hour      INTEGER NOT NULL,
            activity  TEXT    NOT NULL,  -- "gaming", "working", "browsing", "music"
            count     INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (weekday, hour, activity)
        );
        CREATE TABLE IF NOT EXISTS rec_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_type   TEXT NOT NULL,
            sent_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def track_activity(active_window: str):
    """Записывает текущую активность в паттерны."""
    _ensure_table()
    from memory.db import _conn

    now      = datetime.now()
    weekday  = now.weekday()
    hour     = now.hour
    activity = _classify_activity(active_window)
    if not activity:
        return

    conn = _conn()
    existing = conn.execute(
        "SELECT count FROM behavior_patterns WHERE weekday=? AND hour=? AND activity=?",
        (weekday, hour, activity)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE behavior_patterns SET count=count+1
            WHERE weekday=? AND hour=? AND activity=?
        """, (weekday, hour, activity))
    else:
        conn.execute(
            "INSERT INTO behavior_patterns(weekday, hour, activity) VALUES(?,?,?)",
            (weekday, hour, activity)
        )
    conn.commit()


def _classify_activity(window: str) -> Optional[str]:
    wl = window.lower()
    if any(g in wl for g in ("steam", "game", "epic", ".exe")):
        return "gaming"
    if any(w in wl for w in ("code", "visual studio", "pycharm", "vim")):
        return "working"
    if any(b in wl for b in ("chrome", "firefox", "edge")):
        return "browsing"
    if any(m in wl for m in ("spotify", "music", "vlc", "youtube")):
        return "music"
    return None


def get_recommendation() -> Optional[dict]:
    """
    Проверяет паттерны и возвращает рекомендацию если уместно.
    Возвращает {"prompt": str, "type": str} или None.
    """
    _ensure_table()
    from memory.db import _conn

    now     = datetime.now()
    weekday = now.weekday()
    hour    = now.hour

    # Кулдаун
    last = _conn().execute("""
        SELECT sent_at FROM rec_history
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    if last:
        from datetime import timedelta
        try:
            diff = (now - datetime.fromisoformat(last["sent_at"])).total_seconds()
            if diff < _COOLDOWN_SEC:
                return None
        except Exception:
            pass

    # Ищем паттерны для текущего времени
    patterns = _conn().execute("""
        SELECT activity, count FROM behavior_patterns
        WHERE weekday=? AND hour=? AND count >= ?
        ORDER BY count DESC
        LIMIT 1
    """, (weekday, hour, _MIN_DATA_POINTS)).fetchall()

    if not patterns:
        return None

    activity = patterns[0]["activity"]
    count    = patterns[0]["count"]
    day_name = ["понедельник", "вторник", "среда", "четверг",
                "пятница", "суббота", "воскресенье"][weekday]

    # Генерируем подсказку
    prompts = {
        "gaming": (
            f"По паттернам, в {day_name} в это время ({hour}:00) "
            f"Мастер обычно играет ({count} раз замечено). "
            "Спроси об этом или предложи что-то игровое — легко, без навязчивости."
        ),
        "working": (
            f"По паттернам, в {day_name} в {hour}:00 Мастер обычно работает. "
            "Можешь ненавязчиво поинтересоваться как дела с проектом."
        ),
        "browsing": (
            f"В {day_name} вечером Мастер обычно бродит по интернету. "
            "Можешь предложить что-то интересное — статью, видео, тему для изучения "
            "на основе его интересов."
        ),
        "music": (
            f"По паттернам, сейчас Мастер обычно слушает музыку. "
            "Спроси что слушает или предложи что-то под настроение."
        ),
    }

    prompt = prompts.get(activity)
    if not prompt:
        return None

    # Записываем что отправили рекомендацию
    _conn().execute("INSERT INTO rec_history(rec_type) VALUES(?)", (activity,))
    _conn().commit()

    return {"prompt": prompt, "type": activity}