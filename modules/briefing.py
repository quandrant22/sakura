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
from sakura_core.tasks import spawn
from config import BACKGROUND_MODEL_CHAIN

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
        from urllib.parse import quote

        import config
        # Город Мастера, метрическая система, по-русски: без города wttr.in
        # определял место по IP сервера и отвечал в Фаренгейтах.
        city = quote(getattr(config, "MASTER_CITY", "") or "")
        url = f"https://wttr.in/{city}?format=%C+%t+%h&m&lang=ru"
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


def _get_schedule_snippet() -> str:
    """Пары на сегодня и изменения расписания за сутки (sakura_core/schedule)."""
    try:
        from datetime import timedelta

        from sakura_core.schedule import query
        from sakura_core.schedule.diff import room_suffix, short_subject
        from sakura_core.schedule.store import get_store
        now = datetime.now()  # noqa: DTZ005 — локальное время (R10)
        if not query.has_data():
            return ""
        parts = []
        lessons = query.on(now.date())
        if lessons:
            parts.append("Пары сегодня: " + "; ".join(
                f"{x.start:%H:%M} {short_subject(x.subject)}{room_suffix(x.room)}" for x in lessons))
        changed = []
        for h in get_store().history():
            try:
                at = datetime.fromisoformat(h["at"])
            except (KeyError, ValueError):
                continue
            if now - at <= timedelta(hours=24):
                changed += [c.get("kind", "") for c in h.get("changes", [])]
        if changed:
            parts.append(f"Расписание за сутки поменялось (изменений: {len(changed)}).")
        if query.is_stale(now):
            parts.append("Расписание давно не обновлялось.")
        return " ".join(parts)
    except (ImportError, OSError, ValueError, KeyError):
        return ""


async def build_briefing_facts() -> str:
    """Факты сводки без инструкций для модели: время, погода, календарь,
    пары, задачи, годовщины. Источники независимы — читаются одновременно;
    недоступный источник просто не попадает в сводку."""
    calendar, tasks, weather, self_mem, anniversaries, schedule = await asyncio.gather(
        asyncio.to_thread(_get_calendar_snippet),
        asyncio.to_thread(_get_tasks_snippet),
        asyncio.to_thread(_get_weather_snippet),
        asyncio.to_thread(_get_self_snippet),
        asyncio.to_thread(_get_anniversaries_snippet),
        asyncio.to_thread(_get_schedule_snippet),
    )

    now  = datetime.now()
    hour = now.hour
    if hour < 5:
        time_label = "Ночь"
    elif hour < 10:
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
    if schedule:
        parts.append(schedule)
    if tasks:
        parts.append(tasks)
    if anniversaries:
        parts.append(anniversaries)
    if self_mem:
        parts.append(f"Из вчерашних мыслей: {self_mem}")
    return "\n".join(parts)


async def build_briefing_prompt() -> str:
    content = await build_briefing_facts()

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
        reply  = await ask_gemini_fn(
            prompt, save_history=False, chain=BACKGROUND_MODEL_CHAIN,
        )
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