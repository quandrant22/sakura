"""Плеер озвучки: speaking — когда звук реально пошёл, idle — когда доиграл (с задержкой устройства),
уровень выведенного звука; в колбэке звука нет журнала и вызовов чужого кода."""
import logging
import struct
from types import SimpleNamespace

from desktop.core import voice

RATE = 24000
FRAMES = 240                 # 10 мс за вызов колбэка
BLOCK = FRAMES * 2


def make_player(monkeypatch, latency=0.0):
    monkeypatch.setattr(voice.config, "PLAYER_PREROLL_MS", 0, raising=False)
    monkeypatch.setattr(voice.Player, "_open_stream", lambda self: None)
    monkeypatch.setattr(voice.threading, "Thread", lambda *a, **k: SimpleNamespace(start=lambda: None))
    p = voice.Player(RATE)
    p._latency = latency
    p.started, p.ended = [], []
    p.on_start = p.started.append
    p.on_end = p.ended.append
    return p


def pull(p, times=1, time_info=None):
    for _ in range(times):
        p._callback(bytearray(BLOCK), FRAMES, time_info, None)


LOUD = struct.pack(f"<{FRAMES}h", *([12000, -12000] * (FRAMES // 2)))


def test_speaking_only_when_sound_goes_out(monkeypatch):
    p = make_player(monkeypatch)
    p.feed(LOUD)
    p._dispatch()
    assert p.started == []              # чанк пришёл, звука ещё нет
    pull(p)
    assert p.started == []              # колбэк только отмечает — вызовы из уведомителя
    p._dispatch()
    assert p.started == [p.resp_seq]


def test_start_waits_device_delay(monkeypatch):
    t = [100.0]
    monkeypatch.setattr(voice.time, "monotonic", lambda: t[0])
    p = make_player(monkeypatch)
    p.feed(LOUD)
    pull(p, time_info=SimpleNamespace(currentTime=5.0, outputBufferDacTime=5.12))
    p._dispatch()
    assert p.started == []              # звук ещё в устройстве (120 мс)
    t[0] += 0.13
    p._dispatch()
    assert p.started == [p.resp_seq]


def test_idle_after_real_end_with_device_tail(monkeypatch):
    t = [10.0]
    monkeypatch.setattr(voice.time, "monotonic", lambda: t[0])
    p = make_player(monkeypatch, latency=0.08)
    p.feed(LOUD * 2)
    p.flush()                           # tts_end
    pull(p)
    p._dispatch()
    pull(p)                             # последний блок ушёл в устройство
    p._dispatch()
    assert p.ended == []                # ещё 80 мс задержки + 10 мс блока
    t[0] += 0.1
    p._dispatch()
    assert p.ended == [p.resp_seq]


def test_tts_end_after_drained_buffer_and_without_audio(monkeypatch):
    t = [50.0]
    monkeypatch.setattr(voice.time, "monotonic", lambda: t[0])
    p = make_player(monkeypatch)
    p.feed(LOUD)
    pull(p, 3)                          # доиграл до tts_end (разрыв в конце)
    t[0] += 0.03                        # блок звука (10 мс) уже вышел
    p.flush()
    p._dispatch()
    assert p.ended == [p.resp_seq]
    q = make_player(monkeypatch)
    q.flush()                           # tts_end без звука — конец сразу
    q._dispatch()
    assert q.ended == [q.resp_seq]


def test_interrupt_cancels_pending_start_and_end(monkeypatch):
    p = make_player(monkeypatch)
    p.feed(LOUD)
    pull(p)
    p.interrupt()                       # «стоп» — отложенный старт прерванного ответа не придёт
    p._dispatch()
    assert p.started == [] and p.ended == []


def test_level_of_output(monkeypatch):
    p = make_player(monkeypatch)
    p.feed(LOUD)
    pull(p)
    assert p.level > 0.8
    pull(p)                             # тишина
    assert p.level == 0.0


def test_callback_never_logs(monkeypatch, caplog):
    p = make_player(monkeypatch)
    caplog.set_level(logging.DEBUG)
    p.feed(LOUD)
    caplog.clear()
    pull(p)
    pull(p, 3)                          # разрыв
    p.feed(LOUD)
    p.flush()
    pull(p, 2)                          # доиграл, итог разрывов
    assert caplog.records == []
    p._dispatch()
    assert any("underrun" in r.getMessage() for r in caplog.records)


def test_level_loop_at_most_30_per_second_and_source_by_state():
    import asyncio

    from desktop.core.agent import Agent
    a = Agent.__new__(Agent)
    a._state = "speaking"
    a.player = SimpleNamespace(level=0.0)
    a.hearing = SimpleNamespace(level=0.7)
    sent = []
    a.bus = SimpleNamespace(emit=lambda ev, **kw: sent.append((ev, kw["value"])))

    import time
    took = []

    async def go():
        task = asyncio.ensure_future(a._level_loop())
        t0 = time.monotonic()
        i = 0
        while time.monotonic() - t0 < 0.5:     # уровень меняется на каждом шаге цикла
            i += 1
            a.player.level = (i % 10) / 10
            await asyncio.sleep(0)
        a._state = "listening"
        await asyncio.sleep(0.1)
        took.append(time.monotonic() - t0)
        task.cancel()
    asyncio.run(go())
    assert all(ev == "level" for ev, _ in sent)
    assert len(sent) <= 30 * took[0] + 2        # не больше 30 в секунду
    assert sent[-1][1] == 0.7                   # listening — уровень микрофона


def test_level_follows_what_is_heard_with_device_delay(monkeypatch):
    """Bluetooth: блок звучит через 0,35 с после записи — уровень для капли тоже."""
    t = [10.0]
    monkeypatch.setattr(voice.time, "monotonic", lambda: t[0])
    p = make_player(monkeypatch)
    ti = SimpleNamespace(currentTime=1.0, outputBufferDacTime=1.35)
    p.feed(LOUD)
    pull(p, time_info=ti)                    # громкий блок записан в устройство
    assert p.level > 0.8                      # записанный
    assert p.level_at() == 0.0                # но ещё не слышен
    t[0] += 0.36
    assert p.level_at() > 0.8                 # прозвучал
    pull(p, time_info=ti)                     # тишина записана
    assert p.level_at() > 0.8                 # а слышен ещё голос
    t[0] += 0.36
    assert p.level_at() == 0.0
    p.feed(LOUD)
    pull(p, time_info=ti)
    p.interrupt()                             # «стоп» — очередь уровня сброшена
    t[0] += 1
    assert p.level_at() == 0.0
