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
