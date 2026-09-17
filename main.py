import asyncio
import logging

from config import MASTER_ID, MASTER_LAT, MASTER_LON
from config import get_active_key  # noqa: F401 (re-export: tests patch main.get_active_key)
from memory.memory import (
    get_history, clear_history,
    load_session_summary, save_session_summary,
)
from memory.db import ensure_ready, add_to_category as db_add_to_category
from modules.vps_monitor import start_monitor
from modules.mem_cache import apply_all_patches
from modules.tts_server import stream_tts_to_device, warmup_cache
from modules.relationship import check_milestone
from modules.intimacy_mode import reset_reflection_flag
from modules.reminders import set_callback as set_reminder_callback, check_loop as reminder_check_loop
from modules.discord_bot import start_bot as discord_start_bot
from modules.weather import set_location, get_weather, apply_weather_to_mood
from modules.learn_japanese import init_vocabulary
from modules.sakura_narrative import ensure_narrative
from modules.steam_integration import (
    load_library, steam_library_loop, steam_achievements_loop, set_achievement_callback,
)
from modules.reflection import reflection_loop
from sakura_core.proactive import proactive_loop
from sakura_core.memory_tasks import daily_analysis
from sakura_core.llm import ask_gemini
from sakura_core.llm import _strip_tone  # noqa: F401 (re-export)
from adapters.telegram import bot, dp, send_to_master, send_telegram_text
from adapters.telegram import handle_message  # noqa: F401 (re-export)
from adapters.voice import ws_handler, _get_active_ws
from modules.ws_auth import validate_secret_on_startup

import modules.tts_server as tts_server
from modules.state_arbiter import get_current_emotion

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _guarded_add(cat: str, item: str):
    from modules.intimacy_mode import consume_check, is_intimate_content
    if consume_check():
        log.info("[memory] reflection write skipped: intimacy in window")
        return False
    if is_intimate_content(item):
        log.info(f"[memory] интимный фильтр (reflection): {item[:40]}")
        return False
    return db_add_to_category(cat, item)


async def _init_japanese_vocab():
    await asyncio.sleep(5)
    try:
        await asyncio.to_thread(init_vocabulary)
    except Exception as e:
        log.error(f"[japanese] Ошибка инициализации: {e}")


async def _init_weather():
    await asyncio.sleep(3)
    if MASTER_LAT and MASTER_LON:
        set_location(MASTER_LAT, MASTER_LON)
    weather = await get_weather()
    if weather:
        await asyncio.to_thread(apply_weather_to_mood, weather)
        log.info(f"[weather] {weather['temp']}°C, {weather['desc']}")


async def main():
    import websockets
    from modules.proactive import mark_sent

    validate_secret_on_startup()
    await asyncio.to_thread(ensure_ready)
    asyncio.create_task(ensure_narrative())
    asyncio.create_task(_init_japanese_vocab())
    asyncio.create_task(_init_weather())
    asyncio.create_task(load_library())
    await start_monitor()
    apply_all_patches()

    milestone = await asyncio.to_thread(check_milestone)
    if milestone:
        async def _send_milestone():
            await asyncio.sleep(30)
            reply = await ask_gemini(milestone["prompt"], save_history=False)
            if reply:
                await send_to_master(reply)
        asyncio.create_task(_send_milestone())

    tts_server.start()
    asyncio.create_task(warmup_cache())

    async def _reminder_cb(msg: str):
        ws, dev = _get_active_ws()
        if ws:
            await stream_tts_to_device(msg, ws, dev or "laptop", literal=True, emotion=get_current_emotion())
        await send_to_master(msg)
    set_reminder_callback(_reminder_cb)
    asyncio.create_task(reminder_check_loop())

    async def _tg_notif_cb(chat_name, sender, text, urgent):
        from modules.notification_tracker import add_notification
        add_notification("telegram", f"{sender} в {chat_name}", text)
        if urgent:
            ws, dev = _get_active_ws()
            if ws:
                prompt = (
                    f"Поступило важное сообщение в Telegram от {sender} в {chat_name}: «{text[:80]}». "
                    "Скажи Мастеру одной короткой фразой обратить внимание."
                )
                reply = await ask_gemini(prompt, save_history=False)
                if reply:
                    await stream_tts_to_device(reply, ws, dev or "laptop", literal=True, emotion=get_current_emotion())

    try:
        from modules.tg_monitor import get_monitor
        tg_mon = get_monitor()
        tg_mon.set_callback(_tg_notif_cb)
        asyncio.create_task(tg_mon.start())
    except Exception as e:
        log.warning(f"[tg_monitor] Не удалось запустить: {e}")

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", 8765, max_size=None)

    async def _achievement_cb(game_name: str, ach: dict):
        ach_name = ach.get("name") or ach.get("apiname") or "достижение"
        text = f"Выбито достижение: {ach_name} ({game_name})."
        await send_telegram_text(MASTER_ID, text)
        mark_sent(topic="achievement", text=text)
    set_achievement_callback(_achievement_cb)

    asyncio.create_task(discord_start_bot())
    log.info("WebSocket сервер запущен на порту 8765")
    await asyncio.gather(
        dp.start_polling(bot),
        ws_server.wait_closed(),
        daily_analysis(),
        proactive_loop(),
        steam_library_loop(),
        steam_achievements_loop(),
        reflection_loop(
            bot                     = bot,
            master_id               = MASTER_ID,
            ask_gemini_fn           = ask_gemini,
            add_to_category_fn      = _guarded_add,
            clear_history_fn        = clear_history,
            save_session_summary_fn = save_session_summary,
            load_session_summary_fn = load_session_summary,
            get_history_fn          = get_history,
            on_night_done           = reset_reflection_flag,
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
