"""MediaService: перехват music.*/youtube.* агентом, состояние плееров, медиатека через
API, ссылки, YouTube (разбор, вкладка браузера), Яндекс (фейковый клиент), heartbeat."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from desktop.core import agent as agent_module
from desktop.core.media.providers import ProviderError
from desktop.core.media.providers import video as vp
from desktop.core.media.providers.yandex import YandexProvider
from desktop.core.media.service import MediaService
from desktop.tests.media_fixtures import make_mp3


class FakeSettings:
    def __init__(self, **data):
        self.data = dict(data)

    def items(self):
        return dict(self.data)

    def set(self, k, v):
        self.data[k] = v


def run(c):
    return asyncio.run(c)


@pytest.fixture
def media(tmp_path):
    music = tmp_path / "music"
    make_mp3(music / "a.mp3", title="Song", artist="Artist", album="LP")
    events = []
    ms = MediaService(events.append, FakeSettings(music_folders=[str(music)], video_folders=[]),
                      data_dir=str(tmp_path / "data"),
                      yandex=YandexProvider("", False))
    ms.library.scan()
    ms.start()
    yield ms, events
    ms.server.stop()
    ms.library.close()


def test_command_external_when_idle_builtin_when_playing(media):
    ms, events = media
    assert run(ms.handle_command("music.next")) is None          # встроенный не активен → внешний путь
    run(ms.cmd_state({"player": "music", "status": "playing", "title": "Song", "artist": "Artist"}))
    assert run(ms.handle_command("music.next")) == (True, "music: next")
    assert events[-1] == {"type": "media_command", "player": "music", "cmd": "next", "arg": None}
    assert run(ms.handle_command("music.now_playing")) == (True, "Artist — Song")
    assert run(ms.handle_command("music.podcasts")) is None       # нет встроенного аналога
    assert run(ms.handle_command("browser.back")) is None


def test_state_updates_audio_session_and_history(media):
    ms, events = media
    tid = ms.library.tracks()[0]["id"]
    run(ms.cmd_state({"player": "video", "status": "playing", "source": "youtube", "title": "Клип"}))
    assert ms.audio.gains["music"] == 0.3
    assert ms.active_window_hint().endswith("YouTube — Sakura Player")
    run(ms.cmd_state({"player": "music", "status": "playing", "track_id": tid, "new_track": True,
                      "title": "Song", "artist": "Artist", "album": "LP", "position": 3, "duration": 60}))
    assert ms.library.history()[0]["id"] == tid
    assert ms.current_track()["status"] == "играет"
    assert any(e.get("type") == "now_playing" for e in events)
    with pytest.raises(ValueError):
        run(ms.cmd_state({"player": "tv"}))


def test_voice_state_ducks(media):
    ms, events = media
    ms.on_voice_state("listening")
    assert events[-1]["type"] == "audio_duck" and events[-1]["gains"]["music"] == 0.3


def test_library_and_urls(media):
    ms, _ = media
    r = run(ms.cmd_library({"view": "tracks"}))
    assert r["total"] == 1 and r["items"][0]["title"] == "Song"
    assert run(ms.cmd_library({"view": "tracks", "q": "song"}))["items"]
    assert run(ms.cmd_library({"view": "albums"}))["items"][0]["album"] == "LP"
    u = run(ms.cmd_urls({"track_id": r["items"][0]["id"]}))
    assert u["src"].startswith(f"http://127.0.0.1:{ms.server.port}/media/") and "t=" in u["src"]
    with pytest.raises(ValueError):
        run(ms.cmd_library({"view": "nope"}))


def test_like_local_goes_to_favorites(media):
    ms, _ = media
    tid = ms.library.tracks()[0]["id"]
    pid = run(ms.cmd_playlist({"op": "like", "track_id": tid}))["id"]
    run(ms.cmd_playlist({"op": "like", "track_id": tid}))
    assert [t["id"] for t in ms.library.playlist_tracks(pid)] == [tid]
    assert ms.library.playlists()[0]["name"] == "Любимое"


def test_settings_typed_and_folders_applied(media, tmp_path):
    ms, _ = media
    snap = ms.set("player_duck_pct", "45")
    assert snap["player_duck_pct"] == 45 and ms.audio.duck == 0.45
    ms.set("video_folders", [str(tmp_path / "v"), ""])
    assert ms.library.folders["video"] == [str((tmp_path / "v").resolve())]
    with pytest.raises(ValueError):
        ms.set("WS_TOKEN", "x")
    assert ms.snapshot()["yandex_note"] == "неофициальный доступ"


def test_level_clamped(media):
    ms, events = media
    run(ms.cmd_level({"bars": [2, -1, 0.5]}))
    assert events[-1] == {"type": "audio_level", "bars": [1.0, 0.0, 0.5], "source": "builtin"}


# ── видео: ссылки и вкладка браузера ─────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1m30s",
     {"kind": "youtube", "video_id": "dQw4w9WgXcQ", "start": 90}),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", {"kind": "youtube", "video_id": "dQw4w9WgXcQ", "start": 42}),
    ("https://www.youtube.com/shorts/abcdefghijk", {"kind": "youtube", "video_id": "abcdefghijk", "start": 0}),
    ("https://cdn.example/live/stream.m3u8", {"kind": "hls", "url": "https://cdn.example/live/stream.m3u8"}),
    ("https://cdn.example/a.mp4?x=1", {"kind": "file", "url": "https://cdn.example/a.mp4?x=1"}),
])
def test_classify_url(url, expected):
    assert vp.classify_url(url) == expected


@pytest.mark.parametrize("bad", ["file:///C:/a.mp4", "https://example.com/page", "https://youtube.com/watch?v=<x>"])
def test_classify_url_rejects(bad):
    with pytest.raises(ValueError):
        vp.classify_url(bad)


def test_open_url_youtube_gives_local_player(media):
    ms, _ = media
    r = run(ms.cmd_open_url({"url": "https://youtu.be/dQw4w9WgXcQ?t=5"}))
    assert r["player_url"].startswith(f"http://127.0.0.1:{ms.server.port}/youtube/player.html?v=dQw4w9WgXcQ&start=5")


def test_take_from_browser_pauses_tab(media, monkeypatch):
    ms, _ = media
    sent = []

    async def send(cmd, arg=""):
        sent.append(cmd)
        if cmd == "page_content_youtube":
            return {"ok": True, "result": {"video_id": "dQw4w9WgXcQ", "currentTime": 77.4, "paused": False,
                                           "title": "T", "channel": "C"}}
        return {"ok": True}
    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: True, send_command=send))
    r = run(ms.cmd_youtube_from_browser({}))
    assert (r["video_id"], r["start"]) == ("dQw4w9WgXcQ", 77)
    assert sent == ["page_content_youtube", "youtube_pause"]
    assert vp.browser_url("dQw4w9WgXcQ", 77.9) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=77s"


def test_take_from_browser_without_video():
    async def send(cmd, arg=""):
        return {"ok": False, "error": "нет открытого видео YouTube"}
    with pytest.raises(ValueError, match="нет открытого видео"):
        run(vp.take_from_browser(send))


def test_youtube_check_reports_per_host():
    class Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, req, timeout):
            if "ytimg" in req.full_url:
                raise OSError("blocked")
            return Resp()
    r = vp.check_youtube(opener=Opener())
    assert r["youtube.com"] == {"ok": True, "status": 204}
    assert r["i.ytimg.com"] == {"ok": False, "error": "OSError"}


# ── Яндекс.Музыка (фейковый клиент) ──────────────────────────────────

class FakeYM:
    def __init__(self):
        a = SimpleNamespace(name="Artist")
        alb = SimpleNamespace(title="LP", cover_uri="avatars.yandex.net/x/%%")
        self.t = SimpleNamespace(id=5, title="Song", artists=[a], albums=[alb], duration_ms=180000, cover_uri=None)

    def search(self, q, type_):
        return SimpleNamespace(tracks=SimpleNamespace(results=[self.t]))

    def tracks_download_info(self, tid, get_direct_links):
        return [SimpleNamespace(codec="aac", bitrate_in_kbps=256, direct_link="aac"),
                SimpleNamespace(codec="mp3", bitrate_in_kbps=128, direct_link="mp3-128"),
                SimpleNamespace(codec="mp3", bitrate_in_kbps=320, direct_link="mp3-320")]

    def rotor_station_tracks(self, station):
        assert station == "user:onyourwave"
        return SimpleNamespace(sequence=[SimpleNamespace(track=self.t)])

    def users_likes_tracks_add(self, tid):
        return True


def test_yandex_disabled_by_default():
    y = YandexProvider("secret-token", enabled=False)
    with pytest.raises(ProviderError, match="выключена"):
        y.search("x")


def test_yandex_provider_with_fake_client():
    y = YandexProvider("secret-token", enabled=True, client_factory=lambda tok: FakeYM())
    item = y.search("song")[0]
    assert item == {"id": "ym:5", "source": "yandex", "title": "Song", "artist": "Artist", "album": "LP",
                    "duration": 180.0, "cover": "https://avatars.yandex.net/x/200x200"}
    assert y.stream_url("ym:5") == "mp3-320"
    assert y.wave()[0]["title"] == "Song"
    assert y.like("ym:5") is True


def test_yandex_errors_hide_token():
    def boom(tok):
        raise RuntimeError(f"auth failed for {tok}")
    y = YandexProvider("secret-token", enabled=True, client_factory=boom)
    with pytest.raises(ProviderError) as e:
        y.liked()
    assert "secret-token" not in str(e.value)

    class Broken(FakeYM):
        def search(self, q, type_):
            raise ConnectionError("secret-token blocked")
    y2 = YandexProvider("secret-token", enabled=True, client_factory=lambda t: Broken())
    with pytest.raises(ProviderError) as e2:
        y2.search("x")
    assert "secret-token" not in str(e2.value) and "поиск" in str(e2.value)


def test_cmd_yandex_maps_errors(media):
    ms, _ = media
    from desktop.core.api.server import ApiError
    with pytest.raises(ApiError) as e:
        run(ms.cmd_yandex({"op": "search", "q": "x"}))
    assert e.value.code == "yandex_unavailable"


# ── агент: перехват команд и heartbeat ───────────────────────────────

class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, d):
        self.sent.append(json.loads(d))


def test_agent_routes_to_builtin_and_payload_uses_builtin_track(media, monkeypatch):
    ms, events = media
    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = FakeWS()
    a.bus = SimpleNamespace(emit=lambda *x, **k: None)
    a.media = ms
    called = []
    monkeypatch.setattr(agent_module, "execute_command", lambda s: called.append(s) or {"result": "ok"})
    run(ms.cmd_state({"player": "video", "status": "playing", "source": "youtube", "title": "Клип"}))
    run(a._run_command("youtube.forward", "c1", ""))
    assert a._ws.sent[-1]["ok"] is True and events[-1]["cmd"] == "seekBy" and called == []
    run(ms.cmd_state({"player": "music", "status": "playing", "title": "Song", "artist": "Artist",
                      "position": 1, "duration": 10}))
    a._current_track = {"title": "Внешний", "status": "играет"}
    a._last_window, a._window_since, a._activity_level = None, 0.0, 0.0
    monkeypatch.setattr(agent_module, "get_system_info", lambda: {})
    p = a._payload("ping")
    assert p["current_track"]["title"] == "Song"
    assert p["active_window"].endswith("YouTube — Sakura Player")


def test_open_external_only_library_files(media, monkeypatch):
    ms, _ = media
    from desktop.core.platform import windows
    opened = []
    monkeypatch.setattr(windows.os, "startfile", opened.append, raising=False)
    tid = ms.library.tracks()[0]["id"]
    assert run(ms.cmd_open_external({"track_id": tid})) == {"ok": True}
    assert opened and opened[0].endswith("a.mp3")
    with pytest.raises(ValueError):
        run(ms.cmd_open_external({"track_id": 9999}))
