"""Run actual service orchestration with deliberate background/critical faults."""
import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

import main as entrypoint


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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
