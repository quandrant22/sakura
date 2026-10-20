"""Мгновенный трек: логика состояний наблюдателя SMTC и метрика event→ui (без WinRT)."""
import asyncio

from desktop.core.media.smtc_watch import LOST_S, SmtcWatch, TrackState

A = {"title": "Песня", "artist": "Певица", "album": "Альбом", "playing": True, "position_s": 30.0, "duration_s": 200.0}


def test_track_change_emitted_once_position_tick_ignored():
    t = [0.0]
    s = TrackState(clock=lambda: t[0])
    first = s.update(A, True)
    assert first["changed"] == "track" and first["seq"] == 1
    assert s.update({**A, "position_s": 31.0}, True) is None  # обычное движение позиции — не событие
    nxt = s.update({**A, "title": "Другая"}, True)
    assert nxt["changed"] == "track" and nxt["seq"] == 2


def test_pause_and_restart_detected():
    s = TrackState()
    s.update(A, True)
    assert s.update({**A, "playing": False}, True)["changed"] == "playback"
    s.update({**A, "position_s": 100.0}, True)
    assert s.update({**A, "position_s": 0.4}, True)["changed"] == "restart"  # повтор трека — обнуление позиции


def test_optimistic_states():
    t = [0.0]
    s = TrackState(clock=lambda: t[0])
    assert s.update(None, True)["status"] == "starting"        # процесс есть, сессии нет — «Запускается…»
    s.update(A, True)
    assert s.update(None, True) is None                        # сессия мигнула — держим прошлое
    t[0] = LOST_S + 0.1
    assert s.update(None, True)["status"] == "starting"
    assert s.update(None, False)["status"] == "not_running"    # нет процесса — сразу


def test_watch_events_coalesced_and_reported():
    got = []
    infos = [A]

    async def read():
        return infos[-1]

    async def go():
        w = SmtcWatch(lambda st, t: got.append((st["title"], t)), read_info=read, process_running=lambda: True)
        w._loop = asyncio.get_running_loop()
        for _ in range(5):  # пачка событий WinRT — одно чтение
            w._event()
        await asyncio.sleep(0.15)
        infos.append({**A, "title": "Новая"})
        w._event()
        await asyncio.sleep(0.15)
    asyncio.run(go())
    assert [g[0] for g in got] == ["Песня", "Новая"] and all(g[1] is not None for g in got)


def test_service_metric_event_to_ui(monkeypatch):
    import time

    from desktop.core.service import CoreService
    svc = CoreService.__new__(CoreService)
    svc._agent = None
    emitted = []
    svc._emit = emitted.append
    svc._on_music_state({"status": "idle", "seq": 7}, time.monotonic() - 0.12)
    assert emitted[0]["type"] == "music_state"
    out = asyncio.run(svc.cmd_music_ui_ack({"seq": 7}))
    assert 100 <= out["ms"] < 1000
    m = asyncio.run(svc.cmd_music_metrics({}))
    assert m["count"] == 1 and m["p95"] == out["ms"]


def test_event_during_read_is_not_lost():
    """Событие пришло, пока шло чтение SMTC: после чтения — ещё одно, не ждём сторожа (1 с)."""
    got = []
    reads = []

    async def go():
        w = SmtcWatch(lambda st, t: got.append(st["title"]), process_running=lambda: True)

        async def read():
            reads.append(len(reads))
            if len(reads) == 1:
                # Трек сменился, пока шло первое чтение: WinRT присылает событие посреди чтения.
                w._event()
                await asyncio.sleep(0.05)
                return A
            return {**A, "title": "Новая"}
        w._read = read
        w._loop = asyncio.get_running_loop()
        w._event()
        await asyncio.sleep(0.2)  # меньше WATCHDOG_S: сторож не участвует
    asyncio.run(go())
    assert got == ["Песня", "Новая"]
    assert len(reads) == 2


def test_one_smtc_manager_per_process_reacquired_after_error(monkeypatch):
    """music: request_async() один раз на процесс; после ошибки WinRT — заново."""
    import sys
    import types

    from desktop.core import music
    calls = []

    class Mgr:
        def get_sessions(self):
            return []

        def get_current_session(self):
            raise RuntimeError("RPC_E_DISCONNECTED")

    async def request_async():
        calls.append(1)
        return Mgr()

    fake = types.ModuleType("winsdk.windows.media.control")
    fake.GlobalSystemMediaTransportControlsSessionManager = types.SimpleNamespace(request_async=request_async)
    fake.GlobalSystemMediaTransportControlsSessionPlaybackStatus = types.SimpleNamespace(
        PLAYING=4, PAUSED=5, STOPPED=3, CHANGING=2, CLOSED=0)
    monkeypatch.setitem(sys.modules, "winsdk.windows.media.control", fake)
    music.drop_manager()

    async def go():
        m1 = await music._manager()
        m2 = await music._manager()
        assert m1 is m2
        assert await music._smtc_get_info() is None      # ошибка → менеджер сброшен
        await music._manager()
    asyncio.run(go())
    music.drop_manager()
    assert len(calls) == 2


def test_watch_start_shares_manager_and_snapshot_has_seq():
    from desktop.core.media import smtc_watch
    subs = []

    class Mgr:
        def add_sessions_changed(self, cb):
            subs.append("sessions")

        def add_current_session_changed(self, cb):
            subs.append("current")

        def get_sessions(self):
            return []

    mgr = Mgr()

    async def manager():
        return mgr

    async def read():
        return A

    async def go():
        w = SmtcWatch(lambda st, t: None, read_info=read, process_running=lambda: True, manager=manager)
        await w.start()
        await asyncio.sleep(0.1)
        assert smtc_watch.active() is w
        snap = w.snapshot()
        assert snap["title"] == "Песня" and snap["seq"] == 1 and snap["track_seq"] == 1
    try:
        asyncio.run(go())
    finally:
        smtc_watch._ACTIVE.clear()
    assert subs == ["sessions", "current"]  # повторные чтения не переподписываются
