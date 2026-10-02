"""Sakura entry point — main() and background task orchestration."""

import atexit
import asyncio
import inspect
import logging
import os
import signal
from datetime import datetime
from types import SimpleNamespace

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
SHUTDOWN_TIMEOUT = 10.0


def _log_shutdown_mark(stage: str) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    log.info("[shutdown] mark=%s at=%s", stage, timestamp)


def _log_atexit_end() -> None:
    _log_shutdown_mark("atexit_end")


def _log_atexit_start() -> None:
    _log_shutdown_mark("atexit_start")


if __name__ == "__main__":
    atexit.register(_log_atexit_end)


import tqdm

tqdm.tqdm.monitor_interval = 0

from sakura_core.tasks import spawn


def _instrument_shutdown_default_executor(loop) -> None:
    if getattr(loop, "_sakura_shutdown_timing_installed", False):
        return

    original_shutdown = loop.shutdown_default_executor

    async def _shutdown_default_executor_with_timing(*args, **kwargs):
        _log_shutdown_mark("shutdown_default_executor_begin")
        try:
            return await original_shutdown(*args, **kwargs)
        finally:
            _log_shutdown_mark("shutdown_default_executor_end")

    loop.shutdown_default_executor = _shutdown_default_executor_with_timing
    loop._sakura_shutdown_timing_installed = True


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


async def _run_shutdown_steps(steps, deadline: float) -> None:
    loop = asyncio.get_running_loop()
    for name, callback in steps:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"shutdown deadline before {name}")
        result = callback()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=remaining)


def install_shutdown_handlers(loop, stop_event: asyncio.Event) -> None:
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    loop.add_signal_handler(signal.SIGINT, stop_event.set)


async def _run_lifecycle(lifecycle, stop_event: asyncio.Event) -> None:
    def _close_database():
        from memory.db import close as close_db
        close_db()

    await run_services_until_stopped(
        lifecycle.polling,
        lifecycle.websocket,
        lifecycle.background,
        stop_event,
        [("service components", lambda: graceful_shutdown(
            lifecycle.dispatcher, lifecycle.websocket_server, lifecycle.discord_bot,
        ))],
        [("sqlite", lambda: asyncio.to_thread(_close_database))],
    )


async def graceful_shutdown(dispatcher, websocket_server, discord_bot) -> None:
    """Stop external surfaces and cancel process-spawned background tasks."""
    from sakura_core.tasks import cancel_all

    log.info("[shutdown] stopping Telegram polling")
    polling_stop = asyncio.create_task(dispatcher.stop_polling(), name="telegram-stop")
    await asyncio.sleep(0)
    log.info("[shutdown] closing WebSocket server")
    websocket_server.close()
    log.info("[shutdown] stopping Discord bot")
    close_tasks = [
        polling_stop,
        asyncio.create_task(websocket_server.wait_closed(), name="websocket-close"),
        asyncio.create_task(discord_bot.close(), name="discord-close"),
    ]
    results = await asyncio.gather(*close_tasks, return_exceptions=True)
    for task, result in zip(close_tasks, results):
        if isinstance(result, BaseException):
            log.error("[shutdown] %s failed: %s", task.get_name(), result)
    log.info("[shutdown] cancelling spawned tasks")
    pending = await cancel_all(timeout=5.0)
    if pending:
        log.warning("[shutdown] spawned tasks still pending: %s",
                    ", ".join(task.get_name() for task in pending))
    log.info("[shutdown] spawned tasks stopped")


def _thread_where(frame, depth: int = 3) -> str:
    """Где висит поток: самый внутренний кадр + depth ближайших кадров
    вне stdlib (иначе видно только threading.wait/ssl.read)."""
    import sysconfig
    import traceback
    stdlib = sysconfig.get_paths()["stdlib"]
    stack = traceback.extract_stack(frame)
    own = [f for f in stack[:-1] if not f.filename.startswith(stdlib)]
    picked = [stack[-1]] + own[-depth:][::-1]
    return " <- ".join(
        f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in picked
    )


def _executor_worker_is_free(frame) -> bool:
    import linecache
    import traceback

    for entry in traceback.extract_stack(frame):
        path = entry.filename.replace("\\", "/")
        if (path.endswith("/concurrent/futures/thread.py")
                and entry.name == "_worker"):
            return "work_queue.get(" in linecache.getline(
                entry.filename, entry.lineno,
            )
    return False


def log_live_threads(stage: str, loop=None) -> None:
    """INFO-снимок того, что может держать процесс после shutdown.

    Живые потоки (имя, daemon, где висят) и незавершённая работа default
    executor-а loop-а (asyncio.to_thread / run_in_executor): очередь и
    рабочие потоки. asyncio.run при выходе ждёт executor
    (shutdown_default_executor), интерпретатор — не-daemon потоки.
    """
    import sys
    import threading

    try:
        frames = sys._current_frames()
        me = threading.get_ident()
        threads = threading.enumerate()
        log.info("[shutdown] %s: живых потоков %d", stage, len(threads))
        for t in threads:
            where = ("(этот поток)" if t.ident == me
                     else _thread_where(frames[t.ident]) if t.ident in frames
                     else "?")
            log.info("[shutdown]   поток %r daemon=%s: %s", t.name, t.daemon, where)

        executor = getattr(loop, "_default_executor", None) if loop else None
        if executor is None:
            log.info("[shutdown] %s: default executor не создавался", stage)
            return
        workers = [t for t in executor._threads if t.is_alive()]
        log.info("[shutdown] %s: executor — потоков %d (%s), в очереди %d",
                 stage, len(workers), ", ".join(t.name for t in workers) or "—",
                 executor._work_queue.qsize())
        import traceback
        for worker in workers:
            frame = frames.get(worker.ident)
            if frame is None:
                log.info("[shutdown] executor worker=%r state=unknown (нет кадра)",
                         worker.name)
                continue
            is_free = _executor_worker_is_free(frame)
            state = "free" if is_free else "busy"
            log.info("[shutdown] executor worker=%r state=%s",
                     worker.name, state)
            if not is_free:
                stack = "".join(traceback.format_stack(frame)).rstrip()
                log.info("[shutdown] executor worker=%r full stack:\n%s",
                         worker.name, stack)
    except Exception as e:  # диагностика не должна ломать остановку
        log.warning("[shutdown] снимок потоков не удался: %s: %s",
                    type(e).__name__, e)


async def run_services_until_stopped(
    polling,
    websocket,
    background,
    stop_event: asyncio.Event,
    shutdown_steps,
    final_steps=(),
) -> None:
    """Run service surfaces until failure or stop request, then shut down boundedly."""
    tasks = [asyncio.create_task(polling, name="telegram-polling"),
             asyncio.create_task(websocket, name="websocket-server")]
    tasks.extend(asyncio.create_task(supervised(coro, name), name=name)
                 for name, coro in background)
    service_completion = asyncio.gather(*tasks)
    stop_waiter = asyncio.create_task(stop_event.wait(), name="shutdown-event")
    try:
        done, _pending = await asyncio.wait(
            (service_completion, stop_waiter),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if service_completion in done:
            await service_completion
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + SHUTDOWN_TIMEOUT
        shutdown_task = asyncio.create_task(
            _run_shutdown_steps(shutdown_steps, deadline),
            name="graceful-shutdown",
        )
        _done, shutdown_pending = await asyncio.wait(
            (shutdown_task,), timeout=max(0.0, deadline - loop.time()),
        )
        unfinished = []
        if shutdown_pending:
            shutdown_task.cancel()
            unfinished.append(shutdown_task.get_name())
        elif shutdown_task.exception() is not None:
            error = shutdown_task.exception()
            if isinstance(error, asyncio.TimeoutError):
                log.warning("[shutdown] step deadline exceeded: %s", error)
            else:
                log.error("[shutdown] step failed: %s", error)

        for task in tasks:
            task.cancel()
        _done, pending = await asyncio.wait(
            tasks, timeout=max(0.0, deadline - loop.time()),
        )
        unfinished.extend(task.get_name() for task in pending)
        if final_steps and loop.time() < deadline:
            try:
                await _run_shutdown_steps(final_steps, deadline)
            except asyncio.TimeoutError as error:
                unfinished.append("final shutdown steps")
                log.warning("[shutdown] final step deadline exceeded: %s", error)
            except Exception:
                log.exception("[shutdown] final step failed")
        if unfinished:
            log.warning("[shutdown] deadline %.1fs; unfinished tasks: %s",
                        SHUTDOWN_TIMEOUT, ", ".join(unfinished))
        log_live_threads("конец shutdown", loop)
    finally:
        stop_waiter.cancel()
        if not service_completion.done():
            for task in tasks:
                task.cancel()
            service_completion.cancel()
        await asyncio.gather(service_completion, return_exceptions=True)


async def main(*, lifecycle=None, stop_event=None):
    loop = asyncio.get_running_loop()
    _instrument_shutdown_default_executor(loop)
    if stop_event is None:
        stop_event = asyncio.Event()
    install_shutdown_handlers(loop, stop_event)
    if lifecycle is not None:
        await _run_lifecycle(lifecycle, stop_event)
        return

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
    from modules.discord_bot import bot as discord_bot, start_bot as discord_start_bot
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
    from modules.ws_auth import MAX_WS_MESSAGE_SIZE
    import modules.tts_server as tts_server
    from modules.state_arbiter import get_current_emotion
    import websockets
    from modules.proactive import mark_sent

    from sakura_core.bridge import get_router
    get_router()  # Load handlers and validate reachability before starting services.
    validate_secret_on_startup()
    await asyncio.to_thread(ensure_ready)
    spawn(ensure_narrative(), name="ensure-narrative")
    spawn(init_japanese_vocab(), name="init-japanese-vocab")
    spawn(init_weather(MASTER_LAT, MASTER_LON), name="init-weather")
    spawn(load_library(), name="load-steam-library")
    await start_monitor()
    apply_all_patches()

    milestone = await asyncio.to_thread(check_milestone)
    if milestone:
        async def _send_milestone():
            await asyncio.sleep(30)
            reply = await ask_gemini(milestone["prompt"], save_history=False)
            if reply:
                await send_to_master(reply)
        spawn(_send_milestone(), name="send-milestone")

    tts_server.start()
    spawn(warmup_cache(), name="warmup-tts-cache")

    set_reminder_callback(await make_reminder_cb(_get_active_ws, stream_tts_to_device, send_to_master, get_current_emotion))
    spawn(reminder_check_loop(), name="reminder-check-loop")

    try:
        from modules.tg_monitor import get_monitor
        tg_mon = get_monitor()
        tg_mon.set_callback(await make_tg_notif_cb(_get_active_ws, stream_tts_to_device, ask_gemini))
        spawn(tg_mon.start(), name="telegram-monitor")
    except Exception as e:
        log.warning(f"[tg_monitor] Не удалось запустить: {e}")

    ws_host = os.getenv("WS_HOST", "0.0.0.0")
    ws_server = await websockets.serve(
        ws_handler,
        ws_host,
        8765,
        max_size=MAX_WS_MESSAGE_SIZE,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=0.5,
    )

    set_achievement_callback(await make_achievement_cb(MASTER_ID, send_telegram_text, mark_sent))
    spawn(discord_start_bot(), name="discord-bot")
    log.info("WebSocket сервер запущен на порту 8765")

    await _run_lifecycle(SimpleNamespace(
        polling=dp.start_polling(bot, handle_signals=False),
        websocket=ws_server.wait_closed(),
        background=[
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
        dispatcher=dp,
        websocket_server=ws_server,
        discord_bot=discord_bot,
    ), stop_event)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        _log_shutdown_mark("asyncio_run_exit")
        atexit.register(_log_atexit_start)
        # asyncio.run уже дождался default executor; держать выход теперь
        # могут только не-daemon потоки (их ждёт threading._shutdown).
        log_live_threads("после asyncio.run")
