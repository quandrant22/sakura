"""Run actual service orchestration with deliberate background/critical faults."""
import asyncio
import logging
import signal
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main as entrypoint


def run(coro):
    return asyncio.run(coro)


def test_background_failure_keeps_surfaces_alive(caplog):
    async def scenario():
        failed = asyncio.Event()
        replied = asyncio.Event()
        ws_alive = asyncio.Event()
        send = AsyncMock()

        async def broken():
            failed.set()
            raise RuntimeError("intentional background failure")

        async def polling():
            await failed.wait()
            await asyncio.sleep(0)
            await send("Telegram reply after background failure")
            replied.set()
            await asyncio.Event().wait()

        async def websocket():
            await failed.wait()
            ws_alive.set()
            await asyncio.Event().wait()

        service = asyncio.create_task(entrypoint.run_services(
            polling(), websocket(), [("broken_test_loop", broken())]))
        try:
            await asyncio.wait_for(replied.wait(), 2)
            await asyncio.wait_for(ws_alive.wait(), 2)
            assert not service.done()
            send.assert_awaited_once()
        finally:
            service.cancel()
            with pytest.raises(asyncio.CancelledError):
                await service

    with caplog.at_level(logging.ERROR):
        run(scenario())
    record = next(r for r in caplog.records if "[broken_test_loop] упал" in r.message)
    assert record.exc_info[0] is RuntimeError
    assert "Traceback" in caplog.text
    assert "intentional background failure" in caplog.text


@pytest.mark.parametrize("broken_surface", [0, 1])
def test_critical_failure_propagates_and_cancels_others(broken_surface):
    async def scenario():
        cancelled = asyncio.Event()

        async def broken():
            await asyncio.sleep(0)
            raise RuntimeError("critical failure")

        async def other():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        surfaces = [broken(), other()]
        if broken_surface:
            surfaces.reverse()
        with pytest.raises(RuntimeError, match="critical failure"):
            await entrypoint.run_services(*surfaces, [])
        assert cancelled.is_set()
    run(scenario())


def test_bridge_reuses_loaded_declarations(monkeypatch):
    import sakura_core.bridge as bridge
    monkeypatch.setattr(bridge, "_router", None)
    monkeypatch.setattr(bridge, "_executor", None)

    def unexpected_load():
        raise AssertionError("registry loaded again")

    monkeypatch.setattr("sakura_core.router.load", unexpected_load)
    monkeypatch.setattr("sakura_core.executor._load_registry", unexpected_load)
    assert bridge.get_router() is bridge.get_router()
    assert bridge.get_executor() is bridge.get_executor()


def test_shutdown_signal_stops_components_and_closes_resources(monkeypatch):
    from memory import db
    from sakura_core import tasks as task_registry

    calls = []
    stop_event = asyncio.Event()
    polling_stopped = asyncio.Event()
    websocket_closed = asyncio.Event()
    services_started = asyncio.Event()

    class WebSocketServer:
        def close(self):
            calls.append("websocket.close")

        async def wait_closed(self):
            calls.append("websocket.wait_closed")
            websocket_closed.set()

    class Dispatcher:
        async def stop_polling(self):
            calls.append("telegram.stop_polling")
            polling_stopped.set()

    class DiscordBot:
        async def close(self):
            calls.append("discord.close")

    async def fake_cancel_all(timeout):
        calls.append(("cancel_all", timeout))
        return set()

    def fake_db_close():
        calls.append("db.close")

    monkeypatch.setattr(task_registry, "cancel_all", fake_cancel_all)
    monkeypatch.setattr(db, "close", fake_db_close)

    async def polling():
        services_started.set()
        await polling_stopped.wait()

    async def websocket_surface():
        await websocket_closed.wait()

    async def background():
        await asyncio.Event().wait()

    async def scenario():
        started = time.monotonic()
        lifecycle = SimpleNamespace(
            polling=polling(),
            websocket=websocket_surface(),
            background=[("test-background", background())],
            dispatcher=Dispatcher(),
            websocket_server=WebSocketServer(),
            discord_bot=DiscordBot(),
        )
        service = asyncio.create_task(entrypoint.main(
            lifecycle=lifecycle, stop_event=stop_event,
        ))
        await services_started.wait()
        stop_event.set()
        await asyncio.wait_for(service, timeout=10)
        assert time.monotonic() - started < 10

    asyncio.run(scenario())

    assert calls == [
        "telegram.stop_polling",
        "websocket.close",
        "websocket.wait_closed",
        "discord.close",
        ("cancel_all", 5.0),
        "db.close",
    ]


def test_shutdown_signal_handlers_set_event():
    stop_event = asyncio.Event()

    class FakeLoop:
        def __init__(self):
            self.handlers = {}

        def add_signal_handler(self, sig, callback):
            self.handlers[sig] = callback

    loop = FakeLoop()
    entrypoint.install_shutdown_handlers(loop, stop_event)

    assert set(loop.handlers) == {signal.SIGTERM, signal.SIGINT}
    loop.handlers[signal.SIGTERM]()
    assert stop_event.is_set()


def test_log_live_threads_reports_stuck_threads_and_executor(caplog):
    """Снимок после shutdown: не-daemon поток (где висит) и работа executor-а."""
    import threading

    release = threading.Event()

    def _stuck_in_blocking_call():
        release.wait(5)

    holder = threading.Thread(target=_stuck_in_blocking_call,
                              name="stuck-holder", daemon=False)
    holder.start()

    async def scenario():
        loop = asyncio.get_running_loop()
        started = threading.Event()

        def _blocking_io():
            started.set()
            release.wait(5)

        job = asyncio.create_task(asyncio.to_thread(_blocking_io))
        await asyncio.to_thread(started.wait, 5)
        await asyncio.to_thread(lambda: None)
        with caplog.at_level(logging.INFO, logger=entrypoint.log.name):
            entrypoint.log_live_threads("тест", loop)
        release.set()
        await job

    try:
        run(scenario())
    finally:
        release.set()
        holder.join(5)

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "поток 'stuck-holder' daemon=False" in text
    assert "_stuck_in_blocking_call" in text, "не видно, где висит поток"
    assert "_blocking_io" in text, "не видно, чем занят поток executor-а"
    assert "state=busy" in text
    assert "state=free" in text
    assert "executor — потоков" in text


def test_log_live_threads_without_executor_does_not_fail(caplog):
    with caplog.at_level(logging.INFO, logger=entrypoint.log.name):
        entrypoint.log_live_threads("тест", None)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "живых потоков" in text and "не создавался" in text


def test_shutdown_default_executor_logs_timing_marks(caplog):
    class Loop:
        async def shutdown_default_executor(self):
            return "closed"

    loop = Loop()
    entrypoint._instrument_shutdown_default_executor(loop)
    entrypoint._instrument_shutdown_default_executor(loop)
    with caplog.at_level(logging.INFO, logger=entrypoint.log.name):
        assert asyncio.run(loop.shutdown_default_executor()) == "closed"

    marks = [record.message for record in caplog.records if "mark=" in record.message]
    assert len(marks) == 2
    assert "mark=shutdown_default_executor_begin at=" in marks[0]
    assert "mark=shutdown_default_executor_end at=" in marks[1]
