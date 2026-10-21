"""Защищённый канал грузится в потоке: без cryptography «Безопасность» отвечает понятной ошибкой,
а цикл событий не ждёт импорт дольше 50 мс."""
import asyncio
import importlib
import time

import pytest

from desktop.core.securechannel import loader


@pytest.fixture(autouse=True)
def _fresh():
    loader.reset()
    yield
    loader.reset()


def _slow_missing(monkeypatch, delay=0.4):
    real = importlib.import_module

    def fake(name, *a, **k):
        if name.startswith("desktop.core.securechannel."):
            time.sleep(delay)   # тяжёлый импорт (DLL cryptography) и затем отказ
            raise ImportError("No module named 'cryptography'")
        return real(name, *a, **k)
    monkeypatch.setattr(loader.importlib, "import_module", fake)


async def _max_gap_while(coro):
    """Максимальный разрыв тиков цикла (мс), пока выполняется coro."""
    gaps, stop = [], False

    async def ticker():
        last = time.monotonic()
        while not stop:
            await asyncio.sleep(0.005)
            now = time.monotonic()
            gaps.append((now - last) * 1000)
            last = now
    t = asyncio.ensure_future(ticker())
    await asyncio.sleep(0.02)
    try:
        result = await coro
    except Exception as e:  # noqa: BLE001
        result = e
    stop = True
    await t
    return result, max(gaps)


def test_missing_cryptography_does_not_block_loop(monkeypatch):
    _slow_missing(monkeypatch)
    res, gap = asyncio.run(_max_gap_while(loader.load()))
    assert isinstance(res, loader.SecureUnavailable)
    assert "cryptography" in str(res)
    assert gap < 50


def test_security_screen_says_what_is_missing(monkeypatch):
    from desktop.core.api.server import ApiError
    from desktop.core.service import CoreService
    _slow_missing(monkeypatch, delay=0.2)
    svc = CoreService.__new__(CoreService)
    svc._agent = None
    svc.link = type("L", (), {"state_event": lambda self: {"proto": None}})()
    st, gap = asyncio.run(_max_gap_while(svc.cmd_secure_status({})))
    assert gap < 50
    assert "cryptography" in st["unavailable"] and st["keys"]["device_fp"] is None
    err, _ = asyncio.run(_max_gap_while(svc.cmd_secure_reset({})))
    assert isinstance(err, ApiError) and err.code == "unavailable" and "cryptography" in err.message


def test_loaded_once_in_thread():
    import threading
    main = threading.get_ident()
    seen = []
    real = loader.load_sync

    def spy():
        seen.append(threading.get_ident())
        real()
    loader.load_sync = spy
    try:
        asyncio.run(loader.load())
        asyncio.run(loader.load())
    finally:
        loader.load_sync = real
    assert len(seen) == 1 and seen[0] != main
