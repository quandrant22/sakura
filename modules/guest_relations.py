"""
modules/guest_relations.py — отношение Сакуры к конкретным гостям.

Мастер может влиять на отношение через комментарии в reply на уведомления.
Отношение сохраняется и влияет на тон общения с гостем и мнения Мастеру.
"""

import json
import os
import logging
from datetime import datetime

log = logging.getLogger(__name__)

RELATIONS_FILE = "memory/guest_relations.json"

# Уровни отношения: от -2 до +2
# -2 = враждебно, -1 = холодно, 0 = нейтрально, +1 = тепло, +2 = дружески
RELATION_LEVELS = {
    -2: "враждебное",
    -1: "холодное",
     0: "нейтральное",
    +1: "тёплое",
    +2: "дружеское",
}

# Ключевые слова для автоматического определения отношения из слов Мастера
_POSITIVE_SIGNALS = [
    "друг", "хороший", "близкий", "доверяю", "нравится", "классный",
    "норм", "окей", "ок", "свой", "хорошо его знаю", "давно знакомы",
    "приятель", "товарищ", "коллега", "знакомый",
]
_NEGATIVE_SIGNALS = [
    "не доверяю", "не нравится", "неприятный", "раздражает", "подозрительный",
    "чужой", "не хочу", "игнорируй", "грубый", "нахал", "спам",
]


def _load() -> dict:
    if not os.path.exists(RELATIONS_FILE):
        return {}
    try:
        with open(RELATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    tmp = RELATIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RELATIONS_FILE)


def get_relation(user_id: int) -> dict:
    """Возвращает данные об отношении к гостю."""
    data = _load()
    return data.get(str(user_id), {
        "level":    0,
        "label":    "нейтральное",
        "notes":    [],
        "updated":  None,
    })


def set_relation(user_id: int, level: int, note: str | None = None):
    """Устанавливает уровень отношения."""
    level = max(-2, min(2, level))
    data  = _load()
    key   = str(user_id)
    if key not in data:
        data[key] = {"level": 0, "label": "нейтральное", "notes": [], "updated": None}
    data[key]["level"]   = level
    data[key]["label"]   = RELATION_LEVELS[level]
    data[key]["updated"] = str(datetime.now())
    if note:
        data[key]["notes"].append({"text": note, "ts": str(datetime.now())})
        data[key]["notes"] = data[key]["notes"][-10:]  # храним последние 10
    _save(data)
    log.info(f"[relations] user={user_id} level={level} ({RELATION_LEVELS[level]})")


def adjust_relation(user_id: int, delta: int, note: str | None = None):
    """Сдвигает уровень отношения на delta."""
    current = get_relation(user_id)["level"]
    set_relation(user_id, current + delta, note)


def detect_relation_from_text(text: str) -> int | None:
    """
    Пытается определить желаемый уровень отношения из текста Мастера.
    Возвращает абсолютный уровень или None если не определить.
    """
    tl = text.lower()
    pos = sum(1 for s in _POSITIVE_SIGNALS if s in tl)
    neg = sum(1 for s in _NEGATIVE_SIGNALS if s in tl)
    if pos > neg:
        return min(2, pos)
    if neg > pos:
        return max(-2, -neg)
    return None


def get_relation_prompt(user_id: int, user_name: str) -> str:
    """
    Возвращает блок для системного промпта описывающий отношение к гостю.
    Пустая строка если нейтральное и без заметок.
    """
    rel = get_relation(user_id)
    level = rel["level"]
    notes = rel.get("notes", [])

    if level == 0 and not notes:
        return ""

    lines = [f"ОТНОШЕНИЕ К {user_name.upper()}: {rel['label'].upper()}"]

    if level == 2:
        lines.append(
            "Мастер сказал что это его хороший друг. "
            "Будь с ним тепло и дружелюбно — почти как со своим, но помни что это не Мастер."
        )
    elif level == 1:
        lines.append(
            "Мастер относится к этому человеку положительно. "
            "Будь мягче и приветливее чем с обычным гостем."
        )
    elif level == -1:
        lines.append(
            "Мастер относится к этому человеку настороженно. "
            "Будь вежлива но сдержана, не открывайся."
        )
    elif level == -2:
        lines.append(
            "Мастер не доверяет этому человеку. "
            "Будь формально вежлива, минимум информации, никакой близости."
        )

    if notes:
        last_notes = [n["text"] for n in notes[-3:]]
        lines.append("Что Мастер говорил об этом человеке: " + " | ".join(last_notes))

    return "\n".join(lines)