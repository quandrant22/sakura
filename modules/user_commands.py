"""
modules/user_commands.py — пользовательский словарь команд.

Пользователь говорит Сакуре новую команду голосом или в TG:
  «когда я говорю X — делай Y»
  «запомни: X = Y»
  «добавь команду X»

Сохраняется в memory/user_commands.json.
Роутер проверяет этот словарь до LLM.
"""

import json
import logging
import os
import re

log = logging.getLogger("sakura.user_commands")

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "..", "memory", "user_commands.json")


def _load() -> dict:
    try:
        with open(COMMANDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(COMMANDS_FILE), exist_ok=True)
    with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def match(text: str) -> dict | None:
    """Ищет текст в пользовательском словаре. Возвращает action или None."""
    data = _load()
    if not data:
        return None
    tl = text.lower().strip().rstrip(".!?,")
    # Точное совпадение
    if tl in data:
        entry = data[tl]
        _increment_uses(entry)
        return entry
    # Частичное — по границам слов (триггеры < 3 символов — только точное)
    for key, action in data.items():
        if len(key) < 3:
            continue
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", tl):
            _increment_uses(action)
            return action
    return None


def cleanup_auto(min_uses: int = 2, older_days: int = 30):
    """Удаляет auto-записи с uses < min_uses старше older_days дней."""
    from datetime import datetime, timedelta
    data = _load()
    if not data:
        return 0
    cutoff = datetime.now() - timedelta(days=older_days)
    to_remove = []
    for key, val in data.items():
        if not isinstance(val, dict) or val.get("source") != "auto":
            continue
        if val.get("uses", 0) >= min_uses:
            continue
        ts = val.get("created_at")
        if ts:
            try:
                if datetime.fromisoformat(ts) > cutoff:
                    continue
            except Exception:
                pass
        to_remove.append(key)
    for k in to_remove:
        del data[k]
    if to_remove:
        _save(data)
    return len(to_remove)
    tl = text.lower().strip().rstrip(".!?,")
    # Точное совпадение
    if tl in data:
        entry = data[tl]
        _increment_uses(entry)
        return entry
    # Частичное — по границам слов (триггеры < 3 символов — только точное)
    for key, action in data.items():
        if len(key) < 3:
            continue
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", tl):
            _increment_uses(action)
            return action
    return None


def _increment_uses(entry):
    """Инкрементирует поле uses для auto-записей."""
    if isinstance(entry, dict) and entry.get("source") == "auto":
        entry["uses"] = entry.get("uses", 0) + 1


def add(trigger: str, action: dict, source: str = "manual") -> bool:
    """Добавляет команду в словарь."""
    data = _load()
    trigger = trigger.lower().strip().rstrip(".!?,")
    if source == "auto":
        action = dict(action)
        action["source"] = "auto"
        action["uses"] = action.get("uses", 1)
    data[trigger] = action
    _save(data)
    log.info(f"[user_cmd] добавлено: {trigger!r} → {action}")
    return True


def remove(trigger: str) -> bool:
    """Удаляет команду из словаря."""
    data = _load()
    trigger = trigger.lower().strip()
    if trigger in data:
        del data[trigger]
        _save(data)
        return True
    return False


def list_all() -> dict:
    return _load()


# ── Парсер фраз обучения ──────────────────────────────────────────────

# Маппинг слов → action
_KNOWN_ACTIONS = {
    # Музыка
    "следующий трек": {"action": "music_next"},
    "предыдущий трек": {"action": "music_prev"},
    "пауза": {"action": "music_play_pause"},
    "лайк": {"action": "music_like"},
    "дизлайк": {"action": "music_dislike"},
    "повтор": {"action": "music:repeat"},
    "перемешать": {"action": "music:shuffle"},
    "моя волна": {"action": "music:wave"},
    "что играет": {"action": "music_info"},
    "что у меня играет": {"action": "music_info"},
    "что у меня сейчас играет": {"action": "music_info"},
    "включить музыку": {"action": "open_app", "arg": "яндекс музыка"},
    # YouTube
    "пауза ютуб": {"action": "youtube_pause", "agent": True},
    "следующее видео": {"action": "youtube_next", "agent": True},
    "полный экран": {"action": "youtube_fullscreen", "agent": True},
    "субтитры": {"action": "youtube_sub_toggle", "agent": True},
    # Браузер
    "новая вкладка": {"action": "browser:tab_new"},
    "закрыть вкладку": {"action": "browser:tab_close"},
    "дублировать вкладку": {"action": "browser:tab_dup"},
    "обновить страницу": {"action": "browser:tab_reload"},
    # Система
    "скриншот": {"action": "screenshot:"},
    "громче": {"action": "volume_up:20"},
    "тише": {"action": "volume_down:20"},
}


def parse_teaching(text: str) -> tuple[str, dict] | None:
    """
    Парсит фразу обучения и возвращает (триггер, action) или None.

    Примеры:
      «запомни: волна = моя волна» → ("волна", music:wave)
      «когда я говорю репит — ставь повтор» → ("репит", music:repeat)
      «добавь команду: тихо = тише» → ("тихо", volume_down:20)
    """
    tl = text.lower().strip()

    # Паттерны обучения
    patterns = [
        r"запомни[:]?\s*[«\"']?(.+?)[»\"']?\s*[=—-]\s*[«\"']?(.+?)[»\"']?\s*$",
        r"когда я говорю\s*[«\"']?(.+?)[»\"']?\s*[—-]\s*(.+)$",
        r"добавь команду[:]?\s*[«\"']?(.+?)[»\"']?\s*[=—-]\s*[«\"']?(.+?)[»\"']?\s*$",
        r"команда\s*[«\"']?(.+?)[»\"']?\s*[=—-]\s*[«\"']?(.+?)[»\"']?\s*$",
    ]

    for pattern in patterns:
        m = re.search(pattern, tl)
        if m:
            trigger = m.group(1).strip().strip("«»\"'")
            meaning = m.group(2).strip().strip("«»\"'")

            # Ищем meaning в известных действиях
            for key, action in _KNOWN_ACTIONS.items():
                if key in meaning or meaning in key:
                    return trigger, action

            # Если не нашли — пробуем как open_app
            if any(w in meaning for w in ("открой", "запусти", "включи")):
                app = meaning
                for w in ("открой", "запусти", "включи"):
                    app = app.replace(w, "").strip()
                if app:
                    return trigger, {"action": "open_app", "arg": app}

    return None
