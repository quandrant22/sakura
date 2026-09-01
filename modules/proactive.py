"""
proactive.py — Проактивность Сакуры.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ЗАКРЫТЫЙ СПИСОК ПОВОДОВ (решение Мастера):
  Проактивное сообщение — ТОЛЬКО факт: новая ачивка, диск сервера >90%,
  память >90% дольше 10 мин, нагрузка > ядра×2 дольше 10 мин, устройство
  offline >30 мин, сессия 3+ часа. Никаких свободных размышлений и поиска:
  проактив НИКОГДА не ходит в интернет — поиск только по обращению Мастера.

Жёсткие правила:
  - Минимум 2 часа между любыми сообщениями (напоминания — отдельно)
  - Критичные (диск/память/устройство) — дедуп до изменения состояния
  - Необязательные (ачивка, долгая сессия) — вероятностный пропуск 50%
"""

import json
import os
import random
import re
from datetime import datetime, timedelta, date

PROACTIVE_FILE = "memory/proactive.json"

# Минимальные интервалы между сообщениями на одну тему (часы)
TOPIC_COOLDOWN = {
    "task_due":          2,
    "task_overdue":      1,
    "calendar":          1,
    "monitor_disk":      2,
    "monitor_mem":       2,
    "monitor_load":      2,
    "monitor_device":    2,
    "long_session":      6,
    "achievement":       1,
}

NIGHT_SILENT_START = 2
NIGHT_SILENT_END   = 7
LATE_NIGHT_START   = 22   # с 22:00 молчим (было 23)

MIN_INTERVAL_HOURS = 2    # минимум между любыми сообщениями
MAX_DAILY          = 10    # максимум в день (было 8-15)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _stem_word(word: str) -> str:
    w = (word or "").lower()
    for prefix in ("при", "про", "по", "на", "за", "пере", "с", "со", "в", "во", "вы", "об", "от", "до", "у"):
        if w.startswith(prefix) and len(w) > len(prefix) + 2:
            w = w[len(prefix):]
            break
    for suffix in ("ешь", "ет", "ют", "ут", "ит", "ил", "ила", "или", "ить", "ишь", "ать", "ять", "ется", "ятся", "алась", "ался", "я", "ы", "и"):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            w = w[:-len(suffix)]
            break
    return w


def _get_significant_terms(text: str) -> set[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return set()
    terms = []
    for raw in normalized.split():
        if len(raw) <= 4:
            continue
        stem = _stem_word(raw)
        if stem:
            terms.append(stem)
    return set(terms)


def is_semantically_similar(text_a: str, text_b: str) -> bool:
    if not text_a or not text_b:
        return False
    terms_a = _get_significant_terms(text_a)
    terms_b = _get_significant_terms(text_b)
    if not terms_a or not terms_b:
        return False
    overlap = terms_a & terms_b
    if not overlap:
        return False
    return len(overlap) / max(1, len(terms_a | terms_b)) > 0.4


def _get_recent_messages(state: dict) -> list[dict]:
    messages = state.get("recent_messages", [])
    if not messages:
        return []
    cleaned = []
    for item in messages[-15:]:
        if isinstance(item, dict):
            cleaned.append(item)
    return cleaned


def add_recent_message(text: str, topic: str = "", source: str = "proactive"):
    state = load_state()
    recent = _get_recent_messages(state)
    recent.append({"text": text, "topic": topic, "source": source, "ts": str(datetime.now())})
    state["recent_messages"] = recent[-15:]
    save_state(state)


def has_recent_semantic_duplicate(text: str) -> bool:
    state = load_state()
    for item in _get_recent_messages(state):
        if is_semantically_similar(text, item.get("text", "")):
            return True
    return False


def should_skip_by_probability(state: dict) -> bool:
    recent = _get_recent_messages(state)
    if not recent:
        return random.random() < 0.35

    recent_proactive = [item for item in recent if item.get("source") == "proactive"]
    recent_window = [
        item for item in recent_proactive
        if item.get("ts") and datetime.fromisoformat(item["ts"]) > datetime.now() - timedelta(hours=3)
    ]
    if recent_window:
        return random.random() < 0.7
    return random.random() < 0.35


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
        "recent_messages":  [],
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


def mark_sent(topic: str = "", text: str = ""):
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

    if text:
        recent = state.get("recent_messages", [])
        recent.append({"text": text, "topic": topic, "source": "proactive", "ts": str(now)})
        state["recent_messages"] = recent[-15:]
    save_state(state)


def mark_work_event(event: str):
    state = load_state()
    today = str(date.today())
    if event == "work_start":
        state["work_start_sent"] = today
    elif event == "work_end":
        state["work_end_sent"] = today
    save_state(state)


def get_fact_trigger(devices: dict) -> tuple:
    """Закрытый список фактических поводов проактива. → (topic, is_critical, текст).

    Никакой генерации и поиска — только готовый факт из таблицы поводов.
    Критичные (диск/память/нагрузка/устройство) дедупятся до изменения
    состояния; долгая сессия — один раз за сессию, с пропуском 50%.
    """
    now   = datetime.now()
    state = load_state()
    ms    = state.setdefault("monitor_state", {})

    # ── Сервер: диск / память / нагрузка (vps_monitor) ──
    try:
        from modules.vps_monitor import get_metrics
        m = get_metrics() or {}
    except Exception:
        m = {}

    disk = float(m.get("disk") or 0)
    if disk > 90:
        if ms.get("disk_sent") != round(disk):
            ms["disk_sent"] = round(disk)
            save_state(state)
            return "monitor_disk", True, f"Диск сервера заполнен на {disk:.0f}%."
    elif ms.pop("disk_sent", None) is not None:
        save_state(state)

    ram = float(m.get("ram") or 0)
    if ram > 90:
        since = ms.get("mem_high_since")
        if not since:
            ms["mem_high_since"] = str(now)
            save_state(state)
        elif now - datetime.fromisoformat(since) >= timedelta(minutes=10):
            if ms.get("mem_sent") != round(ram):
                ms["mem_sent"] = round(ram)
                save_state(state)
                return "monitor_mem", True, f"Память сервера: {ram:.0f}%."
    else:
        had = ms.pop("mem_high_since", None) is not None
        had = ms.pop("mem_sent", None) is not None or had
        if had:
            save_state(state)

    load1 = float(m.get("load1") or 0)
    cores = os.cpu_count() or 1
    if load1 > cores * 2:
        since = ms.get("load_high_since")
        if not since:
            ms["load_high_since"] = str(now)
            save_state(state)
        elif now - datetime.fromisoformat(since) >= timedelta(minutes=10):
            if ms.get("load_sent") != round(load1, 1):
                ms["load_sent"] = round(load1, 1)
                save_state(state)
                return "monitor_load", True, f"Нагрузка на сервер высокая: {load1:.1f}."
    else:
        had = ms.pop("load_high_since", None) is not None
        had = ms.pop("load_sent", None) is not None or had
        if had:
            save_state(state)

    # ── Устройство offline > 30 минут (было online) ──
    notified = ms.setdefault("offline_notified", {})
    dev_dirty = False
    for dev_id, dev in (devices or {}).items():
        online = bool((dev or {}).get("online"))
        if not online:
            if notified.get(dev_id):
                continue
            last_seen = (dev or {}).get("last_seen") or ""
            try:
                dt = datetime.fromisoformat(last_seen)
                if now - dt < timedelta(minutes=30):
                    continue
                hhmm = dt.strftime("%H:%M")
            except Exception:
                continue
            notified[dev_id] = True
            dev_dirty = True
            save_state(state)
            return "monitor_device", True, f"Устройство {dev_id} недоступно с {hhmm}."
        elif notified.pop(dev_id, None) is not None:
            dev_dirty = True
    if dev_dirty:
        save_state(state)

    # ── Долгая сессия: 3+ часа в одной игре (один раз за сессию, пропуск 50%) ──
    try:
        from modules.steam_integration import get_current_session
        sess = get_current_session()
    except Exception:
        sess = None
    if sess and sess.get("minutes", 0) >= 180:
        if ms.get("long_session_game") != sess.get("name"):
            ms["long_session_game"] = sess.get("name")
            save_state(state)
            if random.random() < 0.5:
                return "long_session", False, f"В игре {sess['name']} три часа."
    elif sess is None and ms.pop("long_session_game", None) is not None:
        save_state(state)

    return None, False, ""