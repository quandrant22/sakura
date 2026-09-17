"""Проактивный цикл Сакуры (этап 6, коммит 3).

Перенесено из main.py: proactive_loop() — непрерывный цикл проверки
напоминаний, капсул, игровых событий, погоды и т.д.

Циклические зависимости с main.py (ask_gemini, send_telegram_text,
_get_active_ws) решаются ленивыми импортами внутри функций.
"""

from __future__ import annotations

import asyncio
import logging
import random

log = logging.getLogger("sakura.proactive")

# ── Состояние (перенесено из main.py) ───────────────────────────────────

_last_weather_refresh: float = 0.0
_proactive_attempts: dict[str, int] = {}   # task_id → сколько раз пытались
_PROACTIVE_MAX_ATTEMPTS = 3


async def proactive_loop():
    """Непрерывный цикл: напоминания, капсулы, игровые события, погода."""
    from datetime import date
    from modules.capsules import (get_due_capsules, make_open_prompt, mark_opened,
        get_due_sakura_capsules, make_sakura_open_prompt, mark_sakura_opened)
    from modules.device_manager import load_devices
    from modules.tasks import get_due_tasks, get_upcoming_tasks, mark_notified
    from modules.calendar_module import get_urgent_event
    from modules.proactive import (get_fact_trigger, can_send_message,
        mark_sent, has_recent_semantic_duplicate)
    from modules.window_watcher import is_quiet_mode
    from modules.weather import get_weather, apply_weather_to_mood
    from modules.game_detector import should_check_event
    from modules.reminders import get_unreminded_notes, mark_reminded

    global _last_weather_refresh
    await asyncio.sleep(60)
    while True:
        await asyncio.sleep(120 + random.randint(-30, 90))
        _ph = __import__('datetime').datetime.now().hour
        if _ph >= 23 or _ph < 7:
            await asyncio.sleep(300)
            continue

        # Ленивый импорт: _last_command_ts из modules.state (без цикла на main.py)
        from modules.state import _last_command_ts
        if __import__('time').monotonic() - _last_command_ts < 30:
            await asyncio.sleep(15)
            continue

        try:
            devices = load_devices().get("devices", {})
            trigger = None
            is_crit = False
            prompt  = None
            reply   = None
            _pending_task_id = None

            try:
                due = get_due_tasks()
                if due:
                    task    = due[0]
                    overdue = task.get("due_date", "") < str(date.today())
                    trigger = "task_overdue" if overdue else "task_due"
                    prompt  = f"{'Просроченная' if overdue else 'Наступила'} задача: {task['text']}. Напомни коротко."
                    is_crit = overdue
                    _pending_task_id = task["id"]
            except Exception as e:
                log.error(f"Task check error: {e}")

            if not trigger:
                try:
                    upcoming = get_upcoming_tasks(hours_ahead=0.5)
                    if upcoming:
                        trigger = "task_upcoming"
                        prompt  = f"Через 30 минут: {upcoming[0]['text']}. Напомни коротко."
                except Exception as e:
                    log.debug(f"[proactive] proactive_loop: {type(e).__name__}: {e}")

            if not trigger:
                try:
                    urgent = get_urgent_event()
                    if urgent:
                        trigger = "calendar_urgent"
                        prompt  = f"Через {urgent.get('minutes_left','?')} мин событие: {urgent['summary']}. Срочно предупреди."
                        is_crit = True
                except Exception as e:
                    log.debug(f"[proactive] proactive_loop: {type(e).__name__}: {e}")

            if not trigger:
                ftopic, fcrit, ftext = get_fact_trigger(devices)
                if ftopic and can_send_message(is_critical=fcrit, topic=ftopic):
                    from sakura_core.llm import ask_gemini as _ask
                    from config import MASTER_ID
                    # send_telegram_text через main — ленивый импорт
                    from adapters.telegram import send_telegram_text as _send_tg
                    await _send_tg(MASTER_ID, ftext)
                    mark_sent(topic=ftopic, text=ftext)
                    log.info(f"[proactive] факт ({ftopic}): {ftext}")
                    continue

            if trigger:
                if not can_send_message(is_critical=is_crit):
                    trigger = None
                    reply = None
                else:
                    _tk = str(_pending_task_id)
                    if _pending_task_id is not None:
                        if _proactive_attempts.get(_tk, 0) >= _PROACTIVE_MAX_ATTEMPTS:
                            log.warning("[proactive] задача %s: лимит попыток, помечаю доставленной", _tk)
                            mark_notified(_pending_task_id)
                            _proactive_attempts.pop(_tk, None)
                            trigger = None
                            reply = None
                        else:
                            _proactive_attempts[_tk] = _proactive_attempts.get(_tk, 0) + 1
                    if trigger:
                        from sakura_core.llm import ask_gemini as _ask
                        reply = await _ask(prompt, save_history=False)

                    if reply and not is_crit and has_recent_semantic_duplicate(reply):
                        log.info("[proactive] skip duplicate reminder: %s", reply)
                        if _pending_task_id is not None:
                            mark_notified(_pending_task_id)
                        continue

                    if __import__('time').monotonic() - _last_command_ts < 30:
                        continue

            try:
                if await asyncio.to_thread(is_quiet_mode):
                    await asyncio.sleep(120)
                    continue
            except Exception as e:
                log.debug(f"[proactive] proactive_loop: {type(e).__name__}: {e}")

            try:
                due_caps = await asyncio.to_thread(get_due_capsules)
                from sakura_core.llm import ask_gemini as _ask
                from config import MASTER_ID
                from adapters.telegram import send_telegram_text as _send_tg
                for cap in due_caps:
                    cap_reply = await _ask(make_open_prompt(cap), save_history=False)
                    if cap_reply:
                        await _send_tg(MASTER_ID, cap_reply)
                    await asyncio.to_thread(mark_opened, cap["id"])
            except Exception as e:
                log.debug(f"[proactive] proactive_loop: {type(e).__name__}: {e}")

            try:
                from modules.state import _pending_event_check
                from adapters.voice import _get_active_ws as _gaw
                ws_game, dev_game = _gaw()
                if ws_game and dev_game and await asyncio.to_thread(should_check_event, dev_game):
                    await ws_game.send(__import__("json").dumps({"type": "command", "action": "screenshot:"}))
                    _pending_event_check[dev_game] = True
            except Exception as e:
                log.debug(f"game_event_tick: {e}")

            try:
                due_sakura = await asyncio.to_thread(get_due_sakura_capsules)
                from sakura_core.llm import ask_gemini as _ask
                from config import MASTER_ID
                from adapters.telegram import send_telegram_text as _send_tg
                for cap in due_sakura:
                    cap_reply = await _ask(make_sakura_open_prompt(cap), save_history=False)
                    if cap_reply:
                        await _send_tg(MASTER_ID, cap_reply)
                    await asyncio.to_thread(mark_sakura_opened, cap["id"])
            except Exception as e:
                log.debug(f"sakura_capsules: {e}")

            try:
                notes = get_unreminded_notes()
                if notes and can_send_message(is_critical=False):
                    from sakura_core.llm import ask_gemini as _ask
                    from config import MASTER_ID
                    from adapters.telegram import send_telegram_text as _send_tg
                    note = random.choice(notes)
                    remind_prompt = (
                        f"Мастер записал идею: «{note['raw_text'][:80]}». "
                        "Вспомни об этом вскользь — одно предложение."
                    )
                    note_reply = await _ask(remind_prompt, save_history=False)
                    if note_reply:
                        await _send_tg(MASTER_ID, note_reply)
                        mark_reminded(note["id"])
            except Exception as e:
                log.debug(f"notes reminder: {e}")

            try:
                if __import__('time').monotonic() - _last_weather_refresh > 1800:
                    weather = await get_weather()
                    if weather:
                        await asyncio.to_thread(apply_weather_to_mood, weather)
                    _last_weather_refresh = __import__('time').monotonic()
            except Exception as e:
                log.debug(f"[proactive] proactive_loop: {type(e).__name__}: {e}")

            if trigger and reply:
                from sakura_core.llm import ask_gemini as _ask
                from config import MASTER_ID
                from adapters.telegram import send_telegram_text as _send_tg
                await _send_tg(MASTER_ID, reply)
                mark_sent(trigger, text=reply)
                if _pending_task_id is not None:
                    mark_notified(_pending_task_id)
                    _proactive_attempts.pop(str(_pending_task_id), None)
                log.info(f"Проактивное напоминание: {trigger}")
        except Exception as e:
            log.error(f"Proactive error: {e}")
