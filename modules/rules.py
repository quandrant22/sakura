"""
modules/rules.py — Постоянные правила общения.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Мастер говорит как хочет чтобы с ним общались — Сакура запоминает навсегда.
Правила не обрезаются, не забываются, всегда попадают в промпт.

Примеры:
  "называй меня Влад" → обращение меняется
  "говори прямо про секс" → тема разрешена
  "не спрашивай в конце каждого сообщения" → стиль
  "когда говорю про работу — не лезь с советами" → поведение
"""

import json
import os
from datetime import datetime

RULES_FILE = "memory/rules.json"

_ADDRESS_TRIGGERS = [
    "называй меня ", "зови меня ", "обращайся ко мне ",
    "можешь звать меня ", "буду для тебя ",
]
_FORGET_ADDRESS_TRIGGERS = [
    "забудь как меня называть", "называй меня снова мастер",
    "вернись к мастер", "обратно мастер",
]
_STYLE_TRIGGERS = {
    "не спрашивай":          "не заканчивать сообщения вопросом",
    "без вопросов в конце":  "не заканчивать сообщения вопросом",
    "говори короче":         "отвечать короче и лаконичнее",
    "отвечай короче":        "отвечать короче и лаконичнее",
    "можешь материться":     "материться когда уместно",
    "матерись":              "материться когда уместно",
    "говори прямо":          "говорить прямо и без обиняков",
    "без экивоков":          "говорить прямо и без обиняков",
    "не лезь с советами":    "не давать советов если не просят",
    "не советуй":            "не давать советов если не просят",
    "не упоминай работу":    "не поднимать тему работы если он сам не начал",
    "разбивай на сообщения": "разбивать длинные ответы на несколько сообщений",
}
_PERMISSION_TRIGGERS = [
    "говори открыто про ", "можешь говорить про ",
    "говори прямо про ", "не стесняйся про ",
]
_CANCEL_TRIGGERS = [
    "забудь что я говорил про ", "отмени правило про ",
    "больше не нужно ", "верни как было с ",
]


def load_rules() -> dict:
    if not os.path.exists(RULES_FILE):
        return _default()
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default()


def _default() -> dict:
    return {
        "address":     None,
        "style":       [],
        "permissions": [],
        "behaviors":   [],
        "updated":     str(datetime.now()),
    }


def save_rules(data: dict):
    data["updated"] = str(datetime.now())
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def detect_rule(text: str) -> dict | None:
    """Распознаёт правило в тексте. Возвращает {type, value} или None."""
    tl = text.lower().strip()

    if any(t in tl for t in _FORGET_ADDRESS_TRIGGERS):
        return {"type": "address_reset", "value": None}

    for trigger in _ADDRESS_TRIGGERS:
        if trigger in tl:
            name = tl.split(trigger, 1)[1].strip().strip(".,!?\"'")
            name = name.split()[0] if name else ""
            if name and len(name) > 1:
                return {"type": "address", "value": name}

    for trigger in _PERMISSION_TRIGGERS:
        if trigger in tl:
            topic = tl.split(trigger, 1)[1].strip().strip(".,!?")
            if topic:
                return {"type": "permission", "value": f"говорить открыто про {topic}"}

    for trigger, rule in _STYLE_TRIGGERS.items():
        if trigger in tl:
            return {"type": "style", "value": rule}

    for trigger in _CANCEL_TRIGGERS:
        if trigger in tl:
            topic = tl.split(trigger, 1)[1].strip().strip(".,!?")
            if topic:
                return {"type": "cancel", "value": topic}

    return None


def apply_rule(rule: dict) -> str:
    """Применяет правило, сохраняет, возвращает тип:значение."""
    data  = load_rules()
    rtype = rule["type"]
    val   = rule["value"]

    if rtype == "address":
        data["address"] = val
    elif rtype == "address_reset":
        data["address"] = None
    elif rtype == "style":
        if val not in data["style"]:
            data["style"].append(val)
    elif rtype == "permission":
        if val not in data["permissions"]:
            data["permissions"].append(val)
    elif rtype == "cancel":
        data["style"]       = [r for r in data["style"]       if val not in r]
        data["permissions"] = [r for r in data["permissions"] if val not in r]
        data["behaviors"]   = [r for r in data["behaviors"]   if val not in r]

    save_rules(data)
    return f"{rtype}:{val}"


def get_current_address() -> str | None:
    return load_rules().get("address")


def get_rules_context() -> str:
    """Блок для промпта — высокий приоритет, всегда соблюдать."""
    data        = load_rules()
    address     = data.get("address")
    style       = data.get("style", [])
    permissions = data.get("permissions", [])
    behaviors   = data.get("behaviors", [])

    if not any([address, style, permissions, behaviors]):
        return ""

    lines = ["ПРАВИЛА ОБЩЕНИЯ — соблюдать всегда без исключений:"]
    if address:
        lines.append(f"— Обращаться только «{address}», никогда не «Мастер»")
    for r in style:
        lines.append(f"— {r.capitalize()}")
    for p in permissions:
        lines.append(f"— Разрешено: {p}")
    for b in behaviors:
        lines.append(f"— {b.capitalize()}")

    return "\n".join(lines)