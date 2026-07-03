"""
modules/timeline.py — Временная память Сакуры.
Хранит события с датой и контекстом.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta

TIMELINE_FILE = "memory/timeline.json"
MAX_EVENTS    = 200

EVENT_TYPES = {
    "moment":      "Момент",
    "achievement": "Достижение",
    "struggle":    "Трудность",
    "game":        "Игра",
    "work":        "Работа",
    "mood":        "Настроение",
    "idea":        "Идея",
    "music":       "Музыка",
    "personal":    "Личное",
}


def _atomic_write(data):
    dir_ = os.path.dirname(TIMELINE_FILE) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                     encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, TIMELINE_FILE)


def load_timeline() -> list:
    if not os.path.exists(TIMELINE_FILE):
        return []
    try:
        with open(TIMELINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_timeline(events: list):
    if len(events) > MAX_EVENTS:
        events = events[-MAX_EVENTS:]
    _atomic_write(events)


def add_event(text: str, event_type: str = "moment",
              master_mood: str = "", context: str = "", tags: list = None):
    if not text or len(text.strip()) < 5:
        return
    events = load_timeline()
    events.append({
        "id":          len(events) + 1,
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "time":        datetime.now().strftime("%H:%M"),
        "datetime":    str(datetime.now()),
        "text":        text.strip()[:300],
        "type":        event_type if event_type in EVENT_TYPES else "moment",
        "master_mood": master_mood.strip(),
        "context":     context.strip(),
        "tags":        tags or [],
    })
    save_timeline(events)


def get_recent_events(days: int = 3, limit: int = 8) -> list:
    events = load_timeline()
    cutoff = datetime.now() - timedelta(days=days)
    recent = [
        e for e in events
        if datetime.fromisoformat(e["datetime"]) >= cutoff
    ]
    return recent[-limit:]


def get_events_by_type(event_type: str, limit: int = 5) -> list:
    events = load_timeline()
    return [e for e in events if e.get("type") == event_type][-limit:]


def get_timeline_context(days: int = 2, limit: int = 5) -> str:
    """
    Блок для промпта — только реально свежие и важные события.
    Не включаем рабочие события если они вчерашние.
    """
    events = get_recent_events(days=days, limit=limit)
    if not events:
        return ""

    today    = datetime.now().strftime("%Y-%m-%d")
    filtered = []
    for e in events:
        # Рабочие события — только если сегодня
        if e.get("type") == "work" and e.get("date") != today:
            continue
        filtered.append(e)

    if not filtered:
        return ""

    lines = ["НЕДАВНЕЕ (живая память):"]
    for e in reversed(filtered):
        line = f"— {e['date']} {e['time']}: {e['text']}"
        if e.get("master_mood"):
            line += f" [{e['master_mood']}]"
        lines.append(line)

    return "\n".join(lines)


def get_achievements_context(limit: int = 3) -> str:
    events = get_events_by_type("achievement", limit=limit)
    if not events:
        return ""
    lines = ["ДОСТИЖЕНИЯ:"]
    for e in events:
        lines.append(f"— {e['date']}: {e['text']}")
    return "\n".join(lines)


def extract_and_save_from_dialogue(user_message: str, reply: str, context: dict = None):
    """Извлекает значимые моменты из диалога."""
    msg_lower = user_message.lower()
    ctx       = context or {}
    location  = ctx.get("master", {}).get("location_desc", "")
    activity  = ctx.get("master", {}).get("activity", "")

    achievement_triggers = [
        "сделал", "закончил", "завершил", "прошёл", "победил",
        "наконец", "получилось", "вышло", "справился", "реализовал",
    ]
    if any(t in msg_lower for t in achievement_triggers):
        add_event(user_message[:200], "achievement",
                  master_mood="на подъёме" if any(w in msg_lower for w in ["наконец", "получилось"]) else "",
                  context=location or activity, tags=["#достижение"])
        return

    struggle_triggers = [
        "не получается", "застрял", "баг", "не работает", "сломалось",
        "устал", "надоело", "бесит", "не могу", "проблема",
    ]
    if any(t in msg_lower for t in struggle_triggers):
        add_event(user_message[:200], "struggle",
                  master_mood="на нуле" if any(w in msg_lower for w in ["устал", "надоело"]) else "раздражён",
                  context=location or activity, tags=["#трудность"])
        return

    idea_triggers = ["идея", "придумал", "что если", "а вдруг", "хочу добавить"]
    if any(t in msg_lower for t in idea_triggers):
        add_event(user_message[:200], "idea", context=location or activity, tags=["#идея"])
        return

    if activity == "gaming" and len(user_message) > 20:
        add_event(user_message[:200], "game",
                  context=ctx.get("master", {}).get("current_app", "игра"),
                  tags=["#игра"])
        return

    mood_triggers = ["рад", "счастлив", "злой", "грустно", "обидно", "кайф", "люблю"]
    if any(t in msg_lower for t in mood_triggers):
        add_event(user_message[:200], "mood", context=location or activity, tags=["#настроение"])