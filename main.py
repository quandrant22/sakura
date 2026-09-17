"""Sakura entry point — main() and background task orchestration."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def supervised(coro, name):
    """Log a failed background task without stopping critical surfaces.

    Cancellation is deliberately not swallowed: shutdown must still work.
    """
    try:
        await coro
    except Exception:
        log.exception("[%s] упал", name)


async def run_services(polling, websocket, background):
    """Critical surfaces own lifetime; background failures are isolated."""
    tasks = [asyncio.create_task(polling), asyncio.create_task(websocket)]
    tasks.extend(asyncio.create_task(supervised(coro, name), name=name)
                 for name, coro in background)
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    from config import MASTER_ID, MASTER_LAT, MASTER_LON
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
    from modules.sakura_narrative import ensure_narrative
    from modules.steam_integration import (
        load_library, steam_library_loop, steam_achievements_loop, set_achievement_callback,
    )
    from modules.reflection import reflection_loop
    from sakura_core.proactive import proactive_loop
    from sakura_core.memory_tasks import daily_analysis
    from sakura_core.llm import ask_gemini
    from sakura_core.startup import guarded_add, init_japanese_vocab, init_weather
    from sakura_core.callbacks import (
        make_reminder_cb, make_tg_notif_cb, make_achievement_cb,
    )
    from adapters.telegram import bot, dp, send_to_master, send_telegram_text
    from adapters.ws import ws_handler
    from adapters.voice import _get_active_ws
    from modules.ws_auth import validate_secret_on_startup
    import modules.tts_server as tts_server
    from modules.state_arbiter import get_current_emotion
    import websockets
    from modules.proactive import mark_sent

    from sakura_core.bridge import get_router
    get_router()  # Load handlers and validate reachability before starting services.
    validate_secret_on_startup()
    await asyncio.to_thread(ensure_ready)
    asyncio.create_task(ensure_narrative())
    asyncio.create_task(init_japanese_vocab())
    asyncio.create_task(init_weather(MASTER_LAT, MASTER_LON))
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

    set_reminder_callback(await make_reminder_cb(_get_active_ws, stream_tts_to_device, send_to_master, get_current_emotion))
    asyncio.create_task(reminder_check_loop())

    try:
        from modules.tg_monitor import get_monitor
        tg_mon = get_monitor()
        tg_mon.set_callback(await make_tg_notif_cb(_get_active_ws, stream_tts_to_device, ask_gemini))
        asyncio.create_task(tg_mon.start())
    except Exception as e:
        log.warning(f"[tg_monitor] Не удалось запустить: {e}")

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", 8765, max_size=None)

    set_achievement_callback(await make_achievement_cb(MASTER_ID, send_telegram_text, mark_sent))
    asyncio.create_task(discord_start_bot())
    log.info("WebSocket сервер запущен на порту 8765")
    await run_services(
        dp.start_polling(bot),
        ws_server.wait_closed(),
        [
            ("daily_analysis", daily_analysis()),
            ("proactive_loop", proactive_loop()),
            ("steam_library_loop", steam_library_loop()),
            ("steam_achievements_loop", steam_achievements_loop()),
            ("reflection_loop", reflection_loop(
                bot=bot, master_id=MASTER_ID, ask_gemini_fn=ask_gemini,
                add_to_category_fn=lambda cat, item: guarded_add(db_add_to_category, cat, item),
                clear_history_fn=clear_history,
                save_session_summary_fn=save_session_summary,
                load_session_summary_fn=load_session_summary,
                get_history_fn=get_history, on_night_done=reset_reflection_flag,
            )),
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
