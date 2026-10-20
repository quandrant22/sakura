"""Озвучка: глушение микрофона на время речи и 700 мс после; частота чанков; окно дослушивания и музыка."""
import struct
from types import SimpleNamespace

from desktop.core import hearing as hearing_mod
from desktop.core import voice
from desktop.core.agent import Agent


def _hearing(state="idle", playing=False):
    h = hearing_mod.Hearing.__new__(hearing_mod.Hearing)
    h._mute_until = 0.0
    h.agent = SimpleNamespace(_state=state, player=SimpleNamespace(is_playing=lambda: playing))
    return h


def test_muted_while_speaking_even_with_empty_buffer():
    # Пауза между чанками: буфер пуст, но агент ещё говорит — микрофон глушится.
    h = _hearing(state="speaking", playing=False)
    assert h.tts_muted(now=100.0)


def test_mute_tail_700ms_after_speech():
    h = _hearing(state="speaking", playing=True)
    assert h.tts_muted(now=100.0)
    h.agent._state = "idle"
    h.agent.player = SimpleNamespace(is_playing=lambda: False)
    assert h.tts_muted(now=100.69)
    assert not h.tts_muted(now=100.71)
    assert hearing_mod._TTS_TAIL == 0.7


def test_not_muted_when_quiet():
    assert not _hearing().tts_muted(now=5.0)


def _player():
    p = voice.Player.__new__(voice.Player)
    p._rate = 24000
    p._buf = bytearray()
    import threading
    p._lock = threading.Lock()
    p._reset_response()
    return p


def test_resample_changes_length_by_rate():
    pcm = struct.pack("<480h", *([1000] * 480))  # 10 мс при 48 кГц
    out = voice.resample_pcm16(pcm, 48000, 24000)
    assert len(out) == 240 * 2
    assert voice.resample_pcm16(pcm, 24000, 24000) == pcm


def test_feed_with_other_rate_is_resampled():
    p = _player()
    p.feed(struct.pack("<220h", *([500] * 220)), 22050)  # 10 мс при 22,05 кГц
    assert len(p._buf) == round(220 * 24000 / 22050) * 2  # те же ~10 мс, но при 24 кГц


def test_feed_binary_uses_header_rate():
    p = _player()
    chunk = struct.pack("<I", 48000) + struct.pack("<480h", *([0] * 480))
    p.feed_binary(chunk)
    assert len(p._buf) == 240 * 2


def test_followup_not_opened_while_media_plays():
    a = Agent.__new__(Agent)
    opened = []
    a.hearing = SimpleNamespace(open_followup=lambda s: opened.append(s))
    a._turn_gen = 1
    a._state = "speaking"
    a._set_state = lambda s: None
    a.media = SimpleNamespace(audio=SimpleNamespace(playing={"music": True, "video": False}))
    a._tts_listen = 4
    a._on_audio_end(1)
    assert opened == []
    a.media.audio.playing["music"] = False
    a._tts_listen = 4
    a._on_audio_end(1)
    assert opened == [4.0]
