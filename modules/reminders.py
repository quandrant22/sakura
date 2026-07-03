"""
modules/reminders.py — напоминания и таймеры с голосовым оповещением.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

REMINDERS_FILE = "memory/reminders.json"

# ── Парсинг времени ────────────────────────────────────────────────

_TIME_WORDS = {
    "секунду": 1, "секунд": 1, "секунды": 1,
    "минуту": 60, "минут": 60, "минуты": 60,
    "час": 3600, "часа": 3600, "часов": 3600,
    "день": 86400, "дня": 86400, "дней": 86400,
}


def _parse_delay(text: str) -> int | None:
    """Парсит задержку из текста. Возвращает секунды или None."""
    tl = text.lower()

    # "через N минут/часов/секунд"
    m = re.search(r"через\s+(\d+)\s+(секунд[уы]?|минут[уы]?|час(?:ов|а)?|дн[яей]*)", tl)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        for word, secs in _TIME_WORDS.items():
            if unit.startswith(word[:3]):
                return n * secs

    # "через минуту", "через час"
    for word, secs in _TIME_WORDS.items():
        pattern = f"через\\s+{word}"
        if re.search(pattern, tl):
            return secs

    return None


def _parse_timer(text: str) -> int | None:
    """Парсит таймер: 'таймер на 10 минут'."""
    m = re.search(r"таймер\s+на\s+(\d+)\s+(секунд[уы]?|минут[уы]?|час(?:ов|а)?)", text.lower())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        for word, secs in _TIME_WORDS.items():
            if unit.startswith(word[:3]):
                return n * secs
    return None


# ── Хранилище ──────────────────────────────────────────────────────

def _load() -> list[dict]:
    if os.path.exists(REMINDERS_FILE):
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save(reminders: list[dict]):
    os.makedirs(os.path.dirname(REMINDERS_FILE), exist_ok=True)
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)


def add_reminder(text: str, delay_seconds: int, reminder_type: str = "reminder") -> dict:
    """Добавляет напоминание или таймер."""
    reminders = _load()
    entry = {
        "id": int(time.time() * 1000),
        "type": reminder_type,
        "text": text,
        "trigger_at": time.time() + delay_seconds,
        "created_at": datetime.now().isoformat(),
        "fired": False,
    }
    reminders.append(entry)
    _save(reminders)
    log.info(f"[reminders] добавлено: {reminder_type} через {delay_seconds}с")
    return entry


def get_pending() -> list[dict]:
    """Возвращает несработавшие напоминания."""
    now = time.time()
    return [r for r in _load() if not r.get("fired") and r["trigger_at"] > now]


def get_all() -> list[dict]:
    """Возвращает все активные напоминания."""
    return [r for r in _load() if not r.get("fired")]


def mark_fired(reminder_id: int):
    """Помечает напоминание как сработавшее."""
    reminders = _load()
    for r in reminders:
        if r["id"] == reminder_id:
            r["fired"] = True
    _save(reminders)


def format_reminders_list() -> str:
    """Форматирует список активных напоминаний."""
    active = get_all()
    if not active:
        return "Нет активных напоминаний."

    lines = []
    for r in active:
        remaining = r["trigger_at"] - time.time()
        if remaining <= 0:
            status = "сейчас сработает"
        elif remaining < 60:
            status = f"через {int(remaining)} сек"
        elif remaining < 3600:
            status = f"через {int(remaining // 60)} мин"
        else:
            status = f"через {int(remaining // 3600)} ч"
        label = "таймер" if r["type"] == "timer" else "напоминание"
        lines.append(f"• [{label}] {r['text'][:50]} — {status}")

    return "\n".join(lines)


# ── Парсинг команд ────────────────────────────────────────────────

def parse_reminder(text: str) -> dict | None:
    """
    Парсит голосовую команду напоминания.
    Возвращает {"text": ..., "delay": ...} или None.
    """
    tl = text.lower().strip()

    # "напомни через X [что делать]"
    m = re.match(r"напомни\s+через\s+", tl)
    if m:
        delay = _parse_delay(tl)
        if delay:
            what = re.sub(r"напомни\s+через\s+(?:\d+\s+)?\S+\s*", "", text).strip()
            if not what:
                what = "напоминание"
            return {"text": what, "delay": delay, "type": "reminder"}

    # "таймер на X"
    if "таймер" in tl:
        delay = _parse_timer(tl)
        if delay:
            return {"text": "таймер", "delay": delay, "type": "timer"}

    return None


# ── Фоновая проверка ───────────────────────────────────────────────

_reminder_callback = None


def set_callback(cb):
    """Устанавливает callback для отправки напоминания: cb(text)."""
    global _reminder_callback
    _reminder_callback = cb


async def check_loop(interval: int = 5):
    """Фоновый цикл проверки напоминаний."""
    while True:
        await asyncio.sleep(interval)
        now = time.time()
        reminders = _load()
        fired_any = False
        for r in reminders:
            if not r.get("fired") and r["trigger_at"] <= now:
                r["fired"] = True
                fired_any = True
                label = "Таймер" if r["type"] == "timer" else "Напоминание"
                msg = f"{label}: {r['text']}"
                log.info(f"[reminders] сработало: {msg}")
                if _reminder_callback:
                    try:
                        await _reminder_callback(msg)
                    except Exception as e:
                        log.error(f"[reminders] callback error: {e}")
        if fired_any:
            _save(reminders)
