"""
modules/mood.py — Эмоциональное состояние Сакуры.
Накапливается между сессиями, влияет на тон.
"""

import json
import os
from datetime import datetime

MOOD_FILE = "memory/mood.json"

MOODS = {
    "happy":   "хорошее настроение",
    "playful": "игривое настроение",
    "tender":  "нежное настроение",
    "neutral": "",
    "worried": "немного беспокоится",
    "annoyed": "немного раздражена",
    "lonely":  "скучает",
    "proud":   "гордится мастером",
}

ENERGY_LEVELS = {
    "high":   "энергичная",
    "normal": "",
    "low":    "немного уставшая",
}


def load_mood() -> dict:
    if not os.path.exists(MOOD_FILE):
        return _default()
    try:
        with open(MOOD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default()


def _default() -> dict:
    return {
        "mood":               "neutral",
        "energy":             "normal",
        "note":               "",
        "updated":            str(datetime.now()),
        "last_interaction":   str(datetime.now()),
        "silence_applied":    False,
    }


def _atomic_write(data: dict):
    import tempfile
    dir_ = os.path.dirname(MOOD_FILE) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                     encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, MOOD_FILE)


def save_mood(data: dict):
    _atomic_write(data)


def update_mood(mood: str, energy: str = None, note: str = ""):
    data = load_mood()
    if mood in MOODS:
        data["mood"] = mood
    if energy and energy in ENERGY_LEVELS:
        data["energy"] = energy
    if note:
        data["note"] = note
    data["updated"]          = str(datetime.now())
    data["silence_applied"]  = False
    save_mood(data)


def mark_interaction():
    """Вызывается при каждом сообщении от Мастера."""
    data = load_mood()
    data["last_interaction"] = str(datetime.now())
    data["silence_applied"]  = False

    mood = data.get("mood", "neutral")
    if mood == "lonely":
        data["mood"] = "happy"
        data["note"] = ""
    elif mood == "worried":
        data["mood"] = "neutral"
        data["note"] = ""

    save_mood(data)


def _apply_silence_effect(data: dict):
    if data.get("silence_applied"):
        return
    last = data.get("last_interaction")
    if not last:
        return
    try:
        silence_h = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
        hour_now  = datetime.now().hour

        # Ночью молчание нормально
        if 2 <= hour_now < 9:
            return

        mood = data.get("mood", "neutral")
        if silence_h > 24 and mood not in ("lonely", "annoyed"):
            data["mood"]            = "lonely"
            data["note"]            = ""
            data["silence_applied"] = True
            save_mood(data)
        elif silence_h > 8 and mood == "neutral":
            data["mood"]            = "worried"
            data["note"]            = ""
            data["silence_applied"] = True
            save_mood(data)
    except Exception:
        pass


def get_current_mood() -> dict:
    mood = load_mood()
    _apply_silence_effect(mood)
    return mood


def get_mood_context() -> str:
    """Блок для промпта — только если есть что сказать."""
    data   = get_current_mood()
    mood   = data.get("mood", "neutral")
    energy = data.get("energy", "normal")

    # Нейтральное состояние — ничего не пишем
    if mood == "neutral" and energy == "normal":
        return ""

    parts = []
    mood_desc   = MOODS.get(mood, "")
    energy_desc = ENERGY_LEVELS.get(energy, "")

    if mood_desc:
        parts.append(mood_desc)
    if energy_desc:
        parts.append(energy_desc)

    if not parts:
        return ""

    return f"НАСТРОЕНИЕ САКУРЫ: {', '.join(parts)}"


def auto_detect_mood_from_reply(reply: str, user_message: str):
    """Автоматически определяет настроение по разговору."""
    combined = (user_message + " " + reply).lower()

    if any(w in combined for w in ["смеёмся", "смешно", "весело", "хаха", "лол"]):
        update_mood("playful")
        return
    if any(w in combined for w in ["люблю", "скучаю", "нежно", "обнял", "котик"]):
        update_mood("tender")
        return
    if any(w in user_message.lower() for w in ["получилось", "сделал", "победил", "наконец"]):
        update_mood("proud")
        return
    if any(w in user_message.lower() for w in ["бесит", "надоело", "злой", "ненавижу"]):
        update_mood("worried")
        return