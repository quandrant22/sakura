"""tests/test_player_underrun.py — счёт разрывов и предзаполнение плеера (без звуковой карты)."""

import logging

import pytest

from core import voice

RATE = 24000
FRAMES = 240                 # 10 мс за вызов callback
BLOCK = FRAMES * 2           # байт на вызов


def make_player(monkeypatch, preroll_ms=0):
    monkeypatch.setattr(voice.config, "PLAYER_PREROLL_MS", preroll_ms, raising=False)
    monkeypatch.setattr(voice.Player, "_open_stream", lambda self: None)
    monkeypatch.setattr(voice.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: None})())
    return voice.Player(RATE)


def pull(p, times=1):
    """Фейковый поток: вызвать callback, вернуть сколько байт было не тишиной."""
    out = []
    for _ in range(times):
        buf = bytearray(BLOCK)
        p._callback(buf, FRAMES, None, None)
        out.append(bytes(buf))
    return out


def test_underrun_counted_and_logged(monkeypatch, caplog):
    p = make_player(monkeypatch)
    caplog.set_level(logging.INFO, logger="sakura.voice")
    p.feed(b"\x01\x00" * FRAMES)   # 10 мс
    pull(p)                        # звук пошёл
    pull(p, 3)                     # 30 мс пусто — один разрыв
    p.feed(b"\x01\x00" * FRAMES)
    pull(p)
    pull(p, 2)                     # второй разрыв 20 мс
    p.feed(b"\x01\x00" * FRAMES)
    p.flush()                      # tts_end
    pull(p)                        # доиграл — итог
    msgs = [r.getMessage() for r in caplog.records if "underrun" in r.getMessage()]
    assert msgs == ["[voice] underrun: 2 раз, всего 50 мс, макс. пауза 30 мс"]


def test_no_underrun_no_log(monkeypatch, caplog):
    p = make_player(monkeypatch)
    caplog.set_level(logging.INFO, logger="sakura.voice")
    p.feed(b"\x01\x00" * FRAMES * 2)
    p.flush()
    pull(p, 3)
    assert not [r for r in caplog.records if "underrun" in r.getMessage()]


def test_tail_after_tts_end_not_underrun(monkeypatch):
    p = make_player(monkeypatch)
    p.feed(b"\x01\x00" * (FRAMES // 2))
    p.flush()
    pull(p, 2)
    assert p._ur_count == 0


def test_preroll_waits_for_enough_audio(monkeypatch):
    p = make_player(monkeypatch, preroll_ms=30)
    p.feed(b"\x01\x00" * FRAMES)               # 10 мс < 30 мс
    assert pull(p)[0] == bytes(BLOCK)          # тишина, ждём
    p.feed(b"\x01\x00" * FRAMES * 2)           # всего 30 мс
    assert pull(p)[0] != bytes(BLOCK)          # пошёл звук


def test_preroll_starts_on_tts_end(monkeypatch):
    p = make_player(monkeypatch, preroll_ms=500)
    p.feed(b"\x01\x00" * FRAMES)
    p.flush()
    assert pull(p)[0] != bytes(BLOCK)


def test_preroll_starts_after_timeout(monkeypatch):
    p = make_player(monkeypatch, preroll_ms=500)
    t = [100.0]
    monkeypatch.setattr(voice.time, "monotonic", lambda: t[0])
    p.feed(b"\x01\x00" * FRAMES)
    assert pull(p)[0] == bytes(BLOCK)
    t[0] += 0.7
    assert pull(p)[0] != bytes(BLOCK)


def test_preroll_off_by_default(monkeypatch):
    p = make_player(monkeypatch)
    p.feed(b"\x01\x00" * FRAMES)
    assert pull(p)[0] != bytes(BLOCK)
