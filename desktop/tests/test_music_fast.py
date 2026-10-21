"""Я.Музыка без задержек: heartbeat не читает SMTC, трек — только из события, лайк — в фоне,
задержка цикла событий — в журнале."""
import asyncio
import json
import logging
import threading

from desktop.core import agent as agent_module
from desktop.core import config, music
from desktop.core.loop_lag import LoopLag


class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def _agent():
    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = _WS()
    a._current_track = {}
    return a


def test_heartbeat_does_not_read_smtc_and_pings_without_window_change(monkeypatch):
    async def boom():
        raise AssertionError("heartbeat читает SMTC")
    monkeypatch.setattr(music, "_smtc_get_info", boom)
    monkeypatch.setattr(agent_module, "PING_MAX_SEC", 0.05)
    monkeypatch.setattr(config, "WINDOW_POLL", 0.01)
    main = threading.get_ident()
    threads = []

    def window():
        threads.append(threading.get_ident())
        return "Блокнот"
    monkeypatch.setattr(agent_module, "get_active_window", window)
    a = _agent()
    a._payload = lambda kind: {"type": kind, "threaded": threading.get_ident() != main}

    async def go():
        task = asyncio.ensure_future(a._heartbeat())
        await asyncio.sleep(0.35)
        task.cancel()
    asyncio.run(go())
    pings = [m for m in a._ws.sent if m["type"] == "ping"]
    assert len(pings) >= 4  # окно то же, а ping идёт по таймеру
    assert all(p["threaded"] for p in pings) and all(t != main for t in threads)


def test_current_track_only_from_music_state_event(monkeypatch):
    from desktop.core.service import CoreService
    svc = CoreService.__new__(CoreService)
    svc._agent = _agent()
    svc._agent.push_current_track = lambda: asyncio.sleep(0)
    emitted = []
    svc._emit = emitted.append
    likes = []

    async def liked_for(title, artist):
        likes.append((title, artist, threading.get_ident()))
        return True
    from desktop.core.media import yandex_remote
    monkeypatch.setattr(yandex_remote.shared(), "liked_for", liked_for)

    async def no_cover(st):
        return None
    svc._music_cover = no_cover

    async def go():
        svc._on_music_state({"status": "ok", "seq": 4, "track_seq": 4, "title": "Т", "artist": "А", "album": "",
                             "playing": True, "changed": "track"}, None)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert svc._agent._current_track == {"title": "Т", "artist": "А", "album": "", "status": "играет"}
    assert {"type": "music_like", "seq": 4, "liked": True} in emitted
    assert [e["type"] for e in emitted][0] == "music_state"  # трек — сразу, лайк — следом


def test_loop_lag_warns_over_50ms(caplog):
    lag = LoopLag(clock=lambda: 0.0)
    with caplog.at_level(logging.WARNING, logger="sakura.loop"):
        lag.observe(12.0, now=0.0)
        lag.observe(75.4, now=0.0)
        lag.observe(90.0, now=0.5)   # в ту же секунду — не повторяем, копим максимум
        lag.observe(60.0, now=1.6)
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == ["[loop] lag 75 ms", "[loop] lag 90 ms"]
    rep = lag.report()
    assert rep["count"] == 4 and rep["max"] == 90.0


def test_loop_lag_measures_blocking_call():
    lag = LoopLag(period=0.01)

    async def go():
        task = asyncio.ensure_future(lag.run())
        await asyncio.sleep(0.03)
        import time
        time.sleep(0.12)  # синхронный вызов в корутине — то, что ловит сторож
        await asyncio.sleep(0.03)
        task.cancel()
    asyncio.run(go())
    assert max(lag._window) >= 80


def test_loop_debug_names_slow_coroutine(caplog):
    import os
    import time as _t

    from desktop.core.loop_lag import enable_debug

    async def heartbeat_like():
        _t.sleep(0.08)   # синхронный вызов в корутине

    async def go():
        assert enable_debug(env={"SAKURA_LOOP_DEBUG": "1"})
        assert asyncio.get_running_loop().slow_callback_duration == 0.05
        await asyncio.ensure_future(heartbeat_like())
    with caplog.at_level(logging.WARNING):
        asyncio.run(go())
    assert any("heartbeat_like" in r.getMessage() and "took" in r.getMessage() for r in caplog.records)
    assert enable_debug(asyncio.new_event_loop(), env={}) is False
    assert "SAKURA_LOOP_DEBUG" not in os.environ


def test_freeze_heap_makes_full_gc_cheap():
    import gc
    big = [[i] for i in range(300_000)]   # много отслеживаемых объектов, как модели и torch

    def full_gc_ms():
        import time as _t
        t = _t.perf_counter()
        gc.collect(2)
        return (_t.perf_counter() - t) * 1000
    try:
        before = min(full_gc_ms() for _ in range(3))
        from desktop.core.loop_lag import freeze_heap
        asyncio.run(freeze_heap(0))
        after = min(full_gc_ms() for _ in range(3))
    finally:
        gc.unfreeze()
    assert after < before / 3
    assert big


def test_file_index_entries_not_tracked_by_gc(tmp_path):
    import gc
    import json as _json

    from desktop.core.file_index import FileIndex
    cache = tmp_path / "idx.json"
    cache.write_text(_json.dumps({"paths": [f"C:\\d\\f{i}.txt" for i in range(1000)], "built": 1.0}), encoding="utf-8")
    idx = FileIndex(cache_path=str(cache))
    assert idx._load_cache()
    gc.collect()   # первая сборка снимает с учёта записи (кортежи строк),
    gc.collect()   # вторая — сам кортеж индекса: дальше полная сборка его не обходит
    assert not gc.is_tracked(idx._entries)
