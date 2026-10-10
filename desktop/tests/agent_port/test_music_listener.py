import logging
import sys
import types

from desktop.core import music_listener


def test_loopback_prefers_pyaudiowpatch(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", types.ModuleType("pyaudiowpatch"))
    monkeypatch.setattr(music_listener, "_run_pyaudiowpatch", lambda: calls.append("pyaudio"))
    monkeypatch.setattr(music_listener, "_run_sounddevice", lambda: calls.append("sounddevice"))

    music_listener._run_loopback()

    assert calls == ["pyaudio"]


def test_loopback_uses_sounddevice_only_when_pyaudiowpatch_missing(monkeypatch, caplog):
    calls = []
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)
    monkeypatch.setattr(music_listener, "_run_sounddevice", lambda: calls.append("sounddevice"))

    with caplog.at_level(logging.DEBUG, logger="sakura.music_listener"):
        music_listener._run_loopback()

    assert calls == ["sounddevice"]
    assert "pyaudiowpatch недоступен" in caplog.text


def test_sounddevice_failure_is_debug_and_does_not_retry_pyaudio(monkeypatch, caplog):
    sounddevice = types.ModuleType("sounddevice")
    sounddevice.query_devices = lambda: (_ for _ in ()).throw(RuntimeError("loopback failed"))
    monkeypatch.setitem(sys.modules, "sounddevice", sounddevice)
    monkeypatch.setattr(music_listener, "_run_pyaudiowpatch", lambda: (_ for _ in ()).throw(AssertionError("unexpected retry")))

    with caplog.at_level(logging.DEBUG, logger="sakura.music_listener"):
        music_listener._run_sounddevice()

    assert "sounddevice loopback: loopback failed" in caplog.text
    assert any(record.levelno == logging.DEBUG for record in caplog.records)