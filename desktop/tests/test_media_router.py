"""Диспетчер медиа: все 30 действий music.* и youtube.* из реестра → встроенный или
внешний плеер; current_track и active_window для сервера; менеджер звука."""
from pathlib import Path

import pytest
import yaml

from desktop.core.media.audio_session import AudioSession
from desktop.core.media.router import (
    BUILTIN_IDLE_S,
    MUSIC_ACTIONS,
    YOUTUBE_ACTIONS,
    MediaRouter,
    canonical,
)

CAPS = yaml.safe_load((Path(__file__).resolve().parents[2] / "sakura_core" / "capabilities.yaml")
                      .read_text(encoding="utf-8"))
MEDIA_IDS = [c["id"] for c in CAPS if c.get("executor") == "agent" and c["id"].split(".")[0] in ("music", "youtube")]

# Ожидаемая встроенная команда для каждого действия (None — всегда внешний путь).
EXPECTED = {
    "music.play_pause": ("music", "toggle", None), "music.next": ("music", "next", None),
    "music.prev": ("music", "prev", None), "music.seek_back": ("music", "seekBy", -10),
    "music.seek_forward": ("music", "seekBy", 10), "music.shuffle": ("music", "shuffle", None),
    "music.repeat": ("music", "repeat", None), "music.mute": ("music", "mute", None),
    "music.volume_up": ("music", "volumeBy", 10), "music.volume_down": ("music", "volumeBy", -10),
    "music.now_playing": ("music", "now_playing", None), "music.like": ("music", "like", None),
    "music.dislike": ("music", "dislike", None), "music.liked_tracks": ("music", "play_liked", None),
    "music.playlists": ("music", "list_playlists", None), "music.history": ("music", "list_history", None),
    "music.wave": ("music", "wave", None), "music.podcasts": None,
    "youtube.pause": ("video", "toggle", None), "youtube.forward": ("video", "seekBy", 10),
    "youtube.rewind": ("video", "seekBy", -10), "youtube.next": ("video", "next", None),
    "youtube.fullscreen": ("video", "fullscreen", None), "youtube.mini": ("video", "mini", None),
    "youtube.speed_up": ("video", "rateBy", 0.25), "youtube.speed_down": ("video", "rateBy", -0.25),
    "youtube.sub_toggle": ("video", "subtitles", None), "youtube.theater": ("video", "theater", None),
    "youtube.like": None, "youtube.trending": None,
}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_registry_has_30_media_actions_all_known():
    assert len(MEDIA_IDS) == 30
    assert sorted(MEDIA_IDS) == sorted(EXPECTED)
    assert len(MUSIC_ACTIONS) == 18 and len(YOUTUBE_ACTIONS) == 12


@pytest.mark.parametrize("cid", sorted(EXPECTED))
def test_builtin_when_active(cid):
    r = MediaRouter(clock=Clock())
    r.update("music", status="playing")
    r.update("video", status="playing")
    route = r.plan(cid)
    exp = EXPECTED[cid]
    if exp is None:
        assert route.target == "external"
    else:
        assert (route.target, route.player, route.cmd, route.arg) == ("builtin", *exp)


@pytest.mark.parametrize("cid", sorted(EXPECTED))
def test_external_when_builtin_idle(cid):
    r = MediaRouter(clock=Clock())
    assert r.plan(cid).target == "external"


def test_paused_less_than_10_minutes_still_builtin():
    clock = Clock()
    r = MediaRouter(clock=clock)
    r.update("music", status="paused")
    clock.t += BUILTIN_IDLE_S - 1
    assert r.plan("music.play_pause").target == "builtin"
    clock.t += 2
    assert r.plan("music.play_pause").target == "external"


def test_legacy_spellings_and_volume_arg():
    r = MediaRouter(clock=Clock())
    r.update("music", status="playing")
    assert r.plan("music:next").cmd == "next"
    assert r.plan("music_play_pause").cmd == "toggle"
    assert r.plan("music.volume_up", "20").arg == 20
    assert r.plan("music.volume_down", "5").arg == -5
    assert r.plan("music.volume_up", "500").arg == 10
    r.update("video", status="playing")
    assert r.plan("youtube_forward").arg == 10
    assert r.plan("browser.back") is None and r.plan("volume") is None
    assert canonical("music.unknown") is None


def test_current_track_same_shape_as_smtc():
    clock = Clock()
    r = MediaRouter(clock=clock)
    assert r.current_track() is None
    r.update("music", status="playing", title="Song", artist="Artist", album="LP", position=75, duration=200)
    assert r.current_track() == {"title": "Song", "artist": "Artist", "album": "LP", "status": "играет",
                                 "position": "1:15", "duration": "3:20", "progress": 37}
    r.update("music", status="paused")
    assert r.current_track()["status"] == "пауза"
    assert r.now_playing_text() == "Artist — Song (пауза)"


def test_active_window_hint_for_youtube():
    r = MediaRouter(clock=Clock())
    assert r.active_window_hint() is None
    r.update("video", status="playing", source="youtube", title="Лекция")
    hint = r.active_window_hint()
    assert "youtube" in hint.lower() and "Sakura Player" in hint
    r.update("video", status="playing", source="local", title="Фильм")
    assert "youtube" not in r.active_window_hint().lower()


# ── менеджер звука ───────────────────────────────────────────────────

def test_ducking_on_listen_and_speak():
    events = []
    s = AudioSession(duck_pct=30, emit=events.append)
    s.set_playing("music", True)
    s.set_voice_state("listening")
    assert events[-1] == {"type": "audio_duck", "gains": {"video": 0.3, "music": 0.3}, "ramp_ms": 150}
    s.set_voice_state("speaking")          # те же уровни — нового события нет
    assert len(events) == 1
    s.set_voice_state("thinking")
    assert events[-1] == {"type": "audio_duck", "gains": {"video": 1.0, "music": 1.0}, "ramp_ms": 600}


def test_video_ducks_music():
    events = []
    s = AudioSession(emit=events.append)
    s.set_playing("video", True)
    assert s.gains == {"video": 1.0, "music": 0.3}
    s.set_playing("video", False)
    assert s.gains == {"video": 1.0, "music": 1.0} and events[-1]["ramp_ms"] == 600


def test_duck_pct_setting_and_stop():
    events = []
    s = AudioSession(duck_pct=50, emit=events.append)
    s.set_voice_state("speaking")
    assert s.gains["music"] == 0.5
    s.set_duck_pct(10)
    assert s.gains["music"] == 0.1
    s.stop_all()
    assert events[-1] == {"type": "media_command", "player": "all", "cmd": "pause"}
