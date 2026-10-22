"""tests/test_player_drain.py — Player.is_drained() и last_feed_ts."""

import threading

from desktop.core import voice as voice_module


def _player():
    # Без __init__: он открывает звуковое устройство
    p = voice_module.Player.__new__(voice_module.Player)
    p._rate = 24000
    p._buf = bytearray()
    p._lock = threading.Lock()
    p.last_feed_ts = 0.0
    return p


def test_is_drained_follows_buffer(monkeypatch):
    monkeypatch.setattr(voice_module.time, "monotonic", lambda: 42.0)
    p = _player()
    assert p.is_drained()

    p.feed(b"\x01\x00" * 100)
    assert not p.is_drained()
    assert p.last_feed_ts == 42.0

    out = bytearray(400)
    p._callback(out, 200, None, None)
    assert p.is_drained()


def test_feed_binary_updates_last_feed_ts(monkeypatch):
    monkeypatch.setattr(voice_module.time, "monotonic", lambda: 7.5)
    p = _player()
    p.feed_binary(b"\xc0\x5d\x00\x00" + b"\x00\x00" * 10)
    assert p.last_feed_ts == 7.5
    assert not p.is_drained()


def test_empty_feed_does_not_touch_last_feed_ts(monkeypatch):
    monkeypatch.setattr(voice_module.time, "monotonic", lambda: 9.0)
    p = _player()
    p.feed(b"")
    assert p.last_feed_ts == 0.0
