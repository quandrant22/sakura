"""
modules/user_commands.py — пользовательский словарь команд.

Пользователь говорит Сакуре новую команду голосом или в TG:
  «когда я говорю X — делай Y»
  «запомни: X = Y»
  «добавь команду X»

Сохраняется в memory/user_commands.json.
Роутер проверяет этот словарь до LLM.
"""

import atexit
import json
import logging
import os
import re
import time
from datetime import datetime

log = logging.getLogger("sakura.user_commands")

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "..", "memory", "user_commands.json")

# ── Батч-сохранение счётчика uses ────────────────────────────────────
# Не пишем файл на каждое совпадение: сбрасываем буфер не чаще раза в
# _FLUSH_INTERVAL секунд. При выходе из процесса буфер пишется принудительно
# (atexit) — счётчик обязан переживать перезапуск.
_FLUSH_INTERVAL = 10.0
_last_flush    = 0.0
_pending_data   = None


def _load() -> dict:
    try:
        with open(COMMANDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.debug(f"[user_cmd] load: {e}")
        return {}


def _save(data: dict):
    global _last_flush, _pending_data
    os.makedirs(os.path.dirname(COMMANDS_FILE), exist_ok=True)
    with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _last_flush = time.monotonic()
    # Файл только что записан свежими данными — отложенный буфер устарел
    _pending_data = None


def flush_pending() -> None:
    """Сбрасывает отложенный счётчик uses на диск (по таймеру и при выходе)."""
    global _pending_data
    if _pending_data is not None:
        data, _pending_data = _pending_data, None
        try:
            _save(data)
        except Exception as e:
            log.warning(f"[user_cmd] flush_pending: {e}")


atexit.register(flush_pending)


def match(text: str) -> dict | None:
    """Ищет текст в пользовательском словаре. Возвращает action или None."""
    data = _load()
    if not data:
        return None
    tl = text.lower().strip().rstrip(".!?,")
    hit = None
    # Точное совпадение — приоритетнее частичного
    if tl in data:
        entry = data[tl]
        _increment_uses(entry)
        hit = entry
    else:
        # Частичное — по границам слов (триггеры < 3 символов — только точное).
        # Из всех совпавших выбираем САМЫЙ ДЛИННЫЙ триггер:
        # «заводи мотор» приоритетнее «мотор».
        best_key = None
        for key in data:
            if len(key) < 3:
                continue
            if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", tl):
                if best_key is None or len(key) > len(best_key):
                    best_key = key
        if best_key is not None:
            entry = data[best_key]
            _increment_uses(entry)
            hit = entry
    if hit is not None:
        _register_uses(data)
    return hit


def _register_uses(data: dict):
    """Сохраняет инкрементированный счётчик: сразу либо батчем."""
    global _last_flush, _pending_data
    if time.monotonic() - _last_flush >= _FLUSH_INTERVAL:
        _save(data)
    else:
        # Откладываем запись, но не теряем её при перезапуске
        _pending_data = data


def cleanup_auto(min_uses: int = 2, older_days: int = 30):
    """Удаляет auto/plan-записи с uses < min_uses старше older_days дней.

    Записи, созданные Мастером осознанно (source="user", легаси "manual"),
    НЕ удаляются никогда — только remove() или сам Мастер."""
    from datetime import timedelta
    data = _load()
    if not data:
        return 0
    cutoff = datetime.now() - timedelta(days=older_days)
    to_remove = []
    for key, val in data.items():
        if not isinstance(val, dict):
            continue
        src = val.get("source", "")
        if src not in ("auto", "plan"):
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


def _increment_uses(entry):
    """Инкрементирует поле uses для auto/plan-записей."""
    if isinstance(entry, dict) and entry.get("source") in ("auto", "plan"):
        entry["uses"] = entry.get("uses", 0) + 1


def _validate_action_plan(action: dict) -> tuple[bool, str]:
    """Прогоняет встроенный в команду план через валидацию планировщика.

    Формат хранения (как в ws_handlers): action["plan"] — СПИСОК шагов,
    risky — на верхнем уровне action. Формат не меняется, только проверка.
    Возвращает (ok, причина)."""
    plan = action.get("plan")
    if isinstance(plan, list):
        plan = {"steps": plan}
    elif isinstance(plan, dict):
        plan = {"steps": plan.get("steps"), "summary": plan.get("summary", "")}
    else:
        return False, "plan не является dict/list"
    try:
        from modules.planner import _validate_plan, _is_plan_risky
    except Exception as e:
        return False, f"планировщик недоступен: {e}"
    checked = _validate_plan(plan)
    if checked is None:
        return False, ("план невалиден: пустой, превышает MAX_STEPS, содержит "
                       "неизвестный примитив или суммарный wait больше лимита")
    # Как и планировщик — помечаем опасное (powershell, type_text, необратимые).
    # risky хранится рядом с plan, а не внутри него.
    if "risky" not in action:
        try:
            action["risky"] = _is_plan_risky(checked)
        except Exception as e:
            log.debug(f"[user_cmd] risky-оценка не удалась: {e}")
    return True, ""


def add(trigger: str, action: dict, source: str = "user") -> bool:
    """Добавляет команду в словарь.

    source="user" — создан Мастером осознанно («запомни…», конструктор):
    cleanup_auto такие записи не трогает.
    Невалидный план (action["plan"]) не сохраняется → False.
    """
    data = _load()
    trigger = trigger.lower().strip().rstrip(".!?,")
    if not trigger:
        log.warning("[user_cmd] отказ: пустой триггер")
        return False
    if source == "manual":  # легаси-имя осознанных команд
        source = "user"
    action = dict(action)
    action["source"] = source
    if source in ("auto", "plan"):
        action.setdefault("uses", 1)
    # Дата создания обязательна: без неё cleanup_auto не может проверить возраст
    action.setdefault("created_at", datetime.now().isoformat())
    if "plan" in action:
        ok, reason = _validate_action_plan(action)
        if not ok:
            log.warning(f"[user_cmd] отказ: {trigger!r}: {reason}")
            return False
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
