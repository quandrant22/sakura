"""
proactive.py — Проактивность Сакуры.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Жёсткие правила:
  - Минимум 2 часа между любыми сообщениями
  - Максимум 4-10 проактивных сообщения в день
  - Никакого "жду", "здесь", "молчишь" — это запрещено в промптах
  - Разнообразие тем — одна тема не повторяется чаще раза в сутки
"""

import json
import os
from datetime import datetime, timedelta, date

PROACTIVE_FILE = "memory/proactive.json"

# Минимальные интервалы между сообщениями на одну тему (часы)
TOPIC_COOLDOWN = {
    "work_start":        24,
    "work_end":          24,
    "long_silence":      6,    # было 4 — теперь реже
    "task_due":          2,
    "task_overdue":      1,
    "calendar":          1,
    "battery":           2,
    "proactive_thought": 2,    # было 3 — теперь реже
    "boredom":           4,    # скука — не чаще раза в 4 часа
    "creative":          8,    # творчество — не чаще раза в 8 часов
}

NIGHT_SILENT_START = 2
NIGHT_SILENT_END   = 7
LATE_NIGHT_START   = 22   # с 22:00 молчим (было 23)

MIN_INTERVAL_HOURS = 2    # минимум между любыми сообщениями
MAX_DAILY          = 10    # максимум в день (было 8-15)


def load_state() -> dict:
    if not os.path.exists(PROACTIVE_FILE):
        return _default_state()
    try:
        with open(PROACTIVE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return _default_state()


def _default_state() -> dict:
    return {
        "last_message":     None,
        "messages_today":   0,
        "last_reset":       str(datetime.now().date()),
        "master_status":    "normal",
        "work_start_sent":  None,
        "work_end_sent":    None,
        "last_seen":        str(datetime.now()),
        "topics_today":     [],
        "last_topic":       "",
        "topic_timestamps": {},
        "late_night_sent":  None,
    }


def save_state(data: dict):
    with open(PROACTIVE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _reset_if_new_day(state: dict) -> dict:
    today = str(datetime.now().date())
    if state.get("last_reset") != today:
        state["messages_today"]  = 0
        state["last_reset"]      = today
        state["work_start_sent"] = None
        state["work_end_sent"]   = None
        state["topics_today"]    = []
        state["late_night_sent"] = None
    return state


def update_master_status(text: str):
    text_lower = text.lower()
    state = load_state()

    busy_triggers = ["завал", "занят", "не беспокой", "не мешай", "работаю",
                     "некогда", "позже", "срочно", "пишу код", "в потоке"]
    free_triggers = ["свободен", "освободился", "можешь писать", "скучно",
                     "закончил", "готово", "отдыхаю", "дома", "приехал"]

    if any(t in text_lower for t in busy_triggers):
        state["master_status"] = "busy"
    elif any(t in text_lower for t in free_triggers):
        state["master_status"] = "free"
    else:
        if state.get("master_status") == "busy":
            state["master_status"] = "normal"

    state["last_seen"] = str(datetime.now())
    save_state(state)


def get_master_status() -> str:
    return load_state().get("master_status", "normal")


def get_silence_context() -> dict:
    state     = load_state()
    last_seen = state.get("last_seen")
    now       = datetime.now()
    hour      = now.hour
    result    = {"silence_minutes": 0, "likely_reason": None}

    if not last_seen:
        return result

    try:
        last_dt = datetime.fromisoformat(last_seen)
        silence = now - last_dt
        result["silence_minutes"] = int(silence.total_seconds() / 60)
    except Exception:
        return result

    mins    = result["silence_minutes"]
    weekday = now.weekday()

    if NIGHT_SILENT_START <= hour < NIGHT_SILENT_END:
        result["likely_reason"] = "спит"
    elif weekday < 5 and 8 <= hour < 17:
        result["likely_reason"] = "на работе"
    elif mins < 30:
        result["likely_reason"] = "занят"
    elif mins < 120:
        result["likely_reason"] = "отвлёкся"
    else:
        result["likely_reason"] = "долго нет"

    return result


def _topic_on_cooldown(state: dict, topic: str) -> bool:
    timestamps = state.get("topic_timestamps", {})
    last_time  = timestamps.get(topic)
    if not last_time:
        return False
    try:
        last_dt  = datetime.fromisoformat(last_time)
        cooldown = timedelta(hours=TOPIC_COOLDOWN.get(topic, 6))
        return (datetime.now() - last_dt) < cooldown
    except Exception:
        return False


def can_send_message(is_critical: bool = False, topic: str = "") -> bool:
    state = load_state()
    state = _reset_if_new_day(state)
    save_state(state)

    now    = datetime.now()
    hour   = now.hour
    status = state.get("master_status", "normal")

    if is_critical:
        return True

    if status == "busy":
        return False

    # Глубокая ночь — молчим
    if NIGHT_SILENT_START <= hour < NIGHT_SILENT_END:
        return False

    # Поздний вечер — молчим
    if hour >= LATE_NIGHT_START:
        return False

    # Дневной лимит — жёсткий
    if state.get("messages_today", 0) >= MAX_DAILY:
        return False

    # Минимальный интервал — 3 часа
    last = state.get("last_message")
    if last:
        try:
            last_dt  = datetime.fromisoformat(last)
            elapsed  = now - last_dt
            if elapsed < timedelta(hours=MIN_INTERVAL_HOURS):
                return False
        except Exception:
            pass

    # Кулдаун темы
    if topic and _topic_on_cooldown(state, topic):
        return False

    return True


def mark_sent(topic: str = ""):
    state = load_state()
    now   = datetime.now()

    state["last_message"]   = str(now)
    state["messages_today"] = state.get("messages_today", 0) + 1
    state["last_topic"]     = topic

    if topic:
        topics = state.get("topics_today", [])
        if topic not in topics:
            topics.append(topic)
        state["topics_today"] = topics

        timestamps = state.get("topic_timestamps", {})
        timestamps[topic] = str(now)
        state["topic_timestamps"] = timestamps

    save_state(state)


def mark_work_event(event: str):
    state = load_state()
    today = str(date.today())
    if event == "work_start":
        state["work_start_sent"] = today
    elif event == "work_end":
        state["work_end_sent"] = today
    save_state(state)


def get_trigger(devices: dict, memory_ctx: str) -> tuple:
    now     = datetime.now()
    hour    = now.hour
    minute  = now.minute
    weekday = now.weekday()
    status  = get_master_status()
    state   = load_state()
    today   = str(now.date())
    silence = get_silence_context()

    if NIGHT_SILENT_START <= hour < NIGHT_SILENT_END:
        return None, False

    if hour >= LATE_NIGHT_START:
        return None, False

    # Критичные — батарея и нагрузка
    laptop = devices.get("laptop", {})
    if laptop.get("online"):
        sys_info = laptop.get("system_info", {})
        battery  = sys_info.get("battery")
        plugged  = sys_info.get("plugged", True)
        cpu      = sys_info.get("cpu", 0)
        ram      = sys_info.get("ram", 0)

        if battery and battery < 15 and not plugged:
            return f"Заряд ноутбука критический — {battery}%.", True

        if cpu > 95 and ram > 95:
            return f"Нагрузка критическая — CPU {cpu}%, RAM {ram}%.", True

        if battery and battery < 25 and not plugged and status != "busy":
            if not _topic_on_cooldown(state, "battery"):
                return f"Заряд ноутбука {battery}%, не подключён.", False

    # Начало рабочего дня
    if weekday < 5 and hour == 9 and minute < 30:
        if state.get("work_start_sent") != today:
            return "work_start", False

    # Конец рабочего дня
    if weekday < 5 and hour == 17 and minute < 30:
        if state.get("work_end_sent") != today:
            return "work_end", False

    # Долгое молчание — отключено полностью.
    # Сакура не пишет про отсутствие — она понимает что человек спит/занят.
    # Если нужно написать — напишет что-то своё через proactive_thought.
    pass  # long_silence триггер убран

    # Инициативное сообщение — редко, только со своей мыслью
    if memory_ctx and status in ["free", "normal"] and 10 <= hour < 21:
        if not _topic_on_cooldown(state, "proactive_thought"):
            last = state.get("last_message")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (now - last_dt) >= timedelta(hours=4):
                        return "proactive_thought", False
                except Exception:
                    pass

    # Скука и творческий импульс — когда энергия есть, а делать нечего
    try:
        from modules.disposition import current as _disp_cur
        _d = _disp_cur()
        if _d["willingness"] > 0.6 and status in ["free", "normal"] and 10 <= hour < 21:
            if not _topic_on_cooldown(state, "boredom"):
                last = state.get("last_message")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if (now - last_dt) >= timedelta(hours=6):
                            return "boredom", False
                    except Exception:
                        pass
    except Exception:
        pass

    # Творческий импульс — когда настроение стабильно хорошее и есть энергия
    try:
        from modules.disposition import current as _disp_cr
        _dc = _disp_cr()
        if (_dc["willingness"] > 0.75 and _dc["valence"] > 0.3
                and status in ["free", "normal"] and 12 <= hour < 22):
            if not _topic_on_cooldown(state, "creative"):
                last = state.get("last_message")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        if (now - last_dt) >= timedelta(hours=3):
                            return "creative", False
                    except Exception:
                        pass
    except Exception:
        pass

    return None, False