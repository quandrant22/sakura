"""
modules/briefing.py — Утренний брифинг (бэклог №17).

Классический JARVIS-момент: при первом подключении устройства
после сна Сакура собирает календарь + задачи + погоду + самопамять
+ годовщины из графа связей и произносит это одним голосовым блоком.

Интеграция в main.py:
  from modules.briefing import should_brief, run_briefing

  # В ws_handler, блок "register", после ритуального приветствия:
  if is_master_device(device_id) and await asyncio.to_thread(should_brief):
      asyncio.create_task(run_briefing(device_id, ws, ask_gemini_fn))

Формат брифинга: одно связное голосовое сообщение, 4-6 предложений.
Не список — нарратив от лица Сакуры.
"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, date

log = logging.getLogger("sakura.briefing")

BRIEFING_FILE = "memory/briefing.json"


# ── Состояние ────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(BRIEFING_FILE):
        return {"last_brief_date": None, "last_brief_hour": None}
    try:
        with open(BRIEFING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_brief_date": None, "last_brief_hour": None}


def _save(data: dict):
    dir_ = os.path.dirname(BRIEFING_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, BRIEFING_FILE)


def should_brief() -> bool:
    hour  = datetime.now().hour
    today = str(date.today())
    if not (6 <= hour <= 14):
        return False
    state = _load()
    if state.get("last_brief_date") == today:
        return False
    return True


def mark_briefed():
    data = _load()
    data["last_brief_date"] = str(date.today())
    data["last_brief_hour"] = datetime.now().hour
    _save(data)


# ── Сборка контента брифинга ─────────────────────────────────────────

def _get_calendar_snippet() -> str:
    try:
        from modules.calendar_module import get_calendar_context
        ctx = get_calendar_context()
        return ctx if ctx else ""
    except Exception:
        return ""


def _get_tasks_snippet() -> str:
    try:
        from modules.tasks import get_due_tasks, get_upcoming_tasks
        due      = get_due_tasks()
        upcoming = get_upcoming_tasks(hours_ahead=24)
        items    = [t["text"] for t in (due + upcoming)[:3]]
        if not items:
            return ""
        return "Задачи: " + "; ".join(items)
    except Exception:
        return ""


def _get_weather_snippet() -> str:
    try:
        import urllib.request
        url = "https://wttr.in/?format=%C+%t+%h"
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.read().decode("utf-8").strip()
    except Exception:
        return ""


def _get_self_snippet() -> str:
    try:
        from memory.db import _conn
        conn = _conn()
        rows = conn.execute(
            "SELECT text FROM self_memory ORDER BY RANDOM() LIMIT 1"
        ).fetchall()
        return rows[0]["text"] if rows else ""
    except Exception:
        return ""


def _get_anniversaries_snippet() -> str:
    """Годовщины событий из графа связей — самое личное в брифинге."""
    try:
        from modules.graph import anniversaries_today
        items = anniversaries_today()
        if not items:
            return ""
        parts = []
        for a in items[:2]:  # не больше двух
            years = a["years"]
            name  = a["name"]
            if years == 1:
                parts.append(f"год назад — {name}")
            else:
                parts.append(f"{years} года назад — {name}")
        return "Годовщины: " + "; ".join(parts)
    except Exception:
        return ""


async def build_briefing_prompt() -> str:
    loop = asyncio.get_event_loop()

    calendar      = await loop.run_in_executor(None, _get_calendar_snippet)
    tasks         = await loop.run_in_executor(None, _get_tasks_snippet)
    weather       = await loop.run_in_executor(None, _get_weather_snippet)
    self_mem      = await loop.run_in_executor(None, _get_self_snippet)
    anniversaries = await loop.run_in_executor(None, _get_anniversaries_snippet)

    now  = datetime.now()
    hour = now.hour
    if hour < 10:
        time_label = "Утро"
    elif hour < 13:
        time_label = "Доброе утро"
    else:
        time_label = "День"

    parts = [f"Сейчас {now.strftime('%H:%M')}, {time_label}."]
    if weather:
        parts.append(f"Погода: {weather}.")
    if calendar:
        parts.append(calendar)
    if tasks:
        parts.append(tasks)
    if anniversaries:
        parts.append(anniversaries)
    if self_mem:
        parts.append(f"Из вчерашних мыслей: {self_mem}")

    content = "\n".join(parts)

    return (
        f"Данные для брифинга:\n{content}\n\n"
        "Составь короткий утренний брифинг для Мастера — голосом, от лица Сакуры. "
        "Не список с пунктами, а живой нарратив: 4-5 предложений. "
        "Упомяни только то что реально есть в данных. "
        "Если есть годовщина — вплети её естественно, как личное воспоминание. "
        "Начни без 'Доброе утро'. Не говори 'брифинг' или 'сводка'. "
        "Можешь добавить одно своё наблюдение или вопрос в конце — живо, не формально."
    )


async def run_briefing(
    device_id: str,
    websocket,
    ask_gemini_fn,
    stream_tts_fn,
    telegram_bot=None,
    master_id=None,
):
    try:
        prompt = await build_briefing_prompt()
        reply  = await ask_gemini_fn(prompt, save_history=False)
        if not reply:
            return

        log.info(f"[briefing] Брифинг для {device_id}: {reply[:80]}…")

        await websocket.send(json.dumps({
            "type":      "reply",
            "device_id": device_id,
            "text":      reply,
        }))

        await stream_tts_fn(reply, websocket, device_id, literal=True)

        # Отправляем текст и в Telegram
        if telegram_bot and master_id:
            try:
                await telegram_bot.send_message(master_id, f"☀️ {reply}")
            except Exception as e:
                log.warning(f"[briefing] Telegram send error: {e}")

        mark_briefed()
        log.info("[briefing] Брифинг выполнен.")

    except Exception as e:
        log.error(f"[briefing] Ошибка: {e}")