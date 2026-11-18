"""Встроенная Яндекс.Музыка: голосовые команды, маршрутизация и поток через медиасервер."""
import asyncio
import io
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from desktop.core.media.media_server import MediaServer, ym_host_allowed
from desktop.core.media.providers import ProviderError
from desktop.core.media.providers.yandex import YandexProvider, best_match, parse_playlist_id
from desktop.core.media.router import YANDEX_VERBS, MediaRouter
from desktop.core.media.service import MediaService
from desktop.core.media.yandex_commands import VERBS, YandexCommands, parse_seek


def t(i, title="Song", artist="Artist"):
    return {"id": f"ym:{i}", "source": "yandex", "title": title, "artist": artist}


class FakeProvider:
    enabled = True

    def __init__(self):
        self.calls = []

    def search(self, q, limit=30):
        return [t(1, q)] if q != "пусто" else []

    def find_album(self, q):
        return {"id": "7", "title": q}

    def album_tracks(self, aid):
        return [t(2), t(3)]

    def find_artist(self, q):
        return {"id": "8", "name": q}

    def artist_tracks(self, aid, limit=50):
        return [t(4)]

    def find_playlist(self, q):
        return {"id": "ym:1:5", "name": q}

    def playlist_tracks(self, pid):
        return [t(5), t(6)]

    def playlists(self):
        return [{"id": "ym:1:5", "name": "Бег", "tracks": 2}, {"id": "ym:1:6", "name": "Бег вечером", "tracks": 1}]

    def station_tracks(self, station, after=None):
        return {"items": [t(9)], "batch_id": "b1"}

    def station_feedback(self, *a, **k):
        self.calls.append(("feedback", a))
        return True

    def stations(self):
        return [{"id": "genre:rock", "name": "Рок"}]

    def playlist_add(self, pid, tid):
        self.calls.append(("add", pid, tid))
        return True

    def playlist_delete(self, pid):
        self.calls.append(("delete", pid))
        return True

    def playlist_remove(self, pid, tid):
        return False

    def lyrics(self, tid):
        return "строка"


@pytest.fixture
def ym():
    events = []
    provider = FakeProvider()
    router = MediaRouter()
    router.yandex_on = True
    return YandexCommands(lambda: provider, events.append, router), events, provider, router


def run(cmds, verb, arg=""):
    async def go():
        res = await cmds.run(verb, arg)
        if cmds._background:
            await asyncio.gather(*cmds._background)
        return res
    return asyncio.run(go())


def playing(router, ym_id="ym:1"):
    router.update("music", status="playing", title="Song")
    router.players["music"].extra["ym_id"] = ym_id


def test_every_verb_has_a_handler_and_a_route():
    assert set(VERBS) == set(YANDEX_VERBS)
    assert all(hasattr(YandexCommands, f"_{v}") for v in VERBS)


def test_route_builtin_only_when_enabled():
    r = MediaRouter()
    assert r.plan("music.play_album", "x").target == "external"
    r.yandex_on = True
    route = r.plan("music.play_album", "x")
    assert (route.target, route.cmd, route.arg) == ("builtin", "ym", "play_album")
    assert r.plan("music.next").target == "external"     # плеер молчит — транспорт как раньше


def test_paused_builtin_stays_active_when_yandex_on():
    r = MediaRouter()
    r.yandex_on = True
    r.update("music", status="paused")
    r.players["music"].updated = -10_000
    assert r.plan("music.play_pause").target == "builtin"


def test_play_track_continues_as_radio(ym):
    cmds, events, *_ = ym
    assert run(cmds, "play_track", "nirvana") == (True, "Включила Artist — nirvana")
    arg = events[-1]["arg"]
    assert events[-1]["cmd"] == "ym_play" and arg["station"] == "track:1" and arg["tracks"][0]["id"] == "ym:1"


def test_play_track_not_found(ym):
    cmds, events, *_ = ym
    assert run(cmds, "play_track", "пусто") == (False, "Не нашла трек «пусто»")
    assert events == []


def test_album_shuffle_word_is_removed_from_query(ym):
    cmds, events, *_ = ym
    ok, text = run(cmds, "play_album", "Nevermind вперемешку")
    assert ok and "«Nevermind»" in text and events[-1]["arg"]["shuffle"] is True


def test_wave_sends_station_and_feedback(ym):
    cmds, events, provider, _ = ym
    assert run(cmds, "wave")[0]
    assert events[-1]["arg"]["station"] == "user:onyourwave" and events[-1]["arg"]["batch_id"] == "b1"
    assert provider.calls and provider.calls[0][0] == "feedback"


def test_queue_add_understands_album_and_next(ym):
    cmds, events, *_ = ym
    assert run(cmds, "queue_add", "альбом Nevermind")[0]
    assert len(events[-1]["arg"]["tracks"]) == 2 and events[-1]["arg"]["next"] is False
    assert run(cmds, "play_next", "Smells")[0]
    assert events[-1]["arg"]["next"] is True


def test_queue_show_and_remove(ym):
    cmds, events, *_ = ym
    cmds.set_queue([t(1, "A"), t(2, "B"), t(3, "C")], 0)
    assert run(cmds, "queue_show")[1] == "Дальше: Artist — B; Artist — C"
    assert run(cmds, "queue_remove", "c")[0]
    assert events[-1] == {"type": "media_command", "player": "music", "cmd": "queue_remove", "arg": 2}
    assert run(cmds, "queue_remove", "1")[0] and events[-1]["arg"] == 1
    assert run(cmds, "queue_remove", "нет такого")[0] is False


def test_playlist_add_current_and_named_track(ym):
    cmds, _, provider, router = ym
    assert run(cmds, "playlist_add", "Бег")[0] is False      # ничего не играет
    playing(router)
    assert run(cmds, "playlist_add", "в плейлист Бег")[0]
    assert provider.calls[-1] == ("add", "ym:1:5", "ym:1")
    assert run(cmds, "playlist_add", "Smells в плейлист Бег")[0]
    assert run(cmds, "playlist_add", "Нет такого")[0] is False


def test_playlist_delete_needs_exact_name(ym):
    cmds, _, provider, _ = ym
    assert run(cmds, "playlist_delete", "бе")[0] is False
    assert provider.calls == []
    assert run(cmds, "playlist_delete", "бег")[0]
    assert provider.calls == [("delete", "ym:1:5")]


def test_lyrics_stay_in_window(ym):
    cmds, events, _, router = ym
    playing(router)
    ok, text = run(cmds, "lyrics")
    assert ok and "строка" not in text and events[-1]["arg"]["text"] == "строка"


def test_provider_error_falls_back_or_reports(ym):
    cmds, *_ = ym

    class Down(FakeProvider):
        def search(self, q, limit=30):
            raise ProviderError("Яндекс.Музыка: не удалось (поиск)")

        def find_album(self, q):
            raise ProviderError("Яндекс.Музыка: не удалось (поиск альбома)")
    down = YandexCommands(lambda: Down(), lambda e: None, MediaRouter())
    assert run(down, "play_track", "x") is None               # приложение сможет включить само
    assert run(down, "play_album", "x") == (False, "Яндекс.Музыка: не удалось (поиск альбома)")


@pytest.mark.parametrize("arg,want", [("1:30", ("seek", 90)), ("2 минуты", ("seek", 120)), ("45", ("seek", 45)),
                                      ("начало", ("seek", 0)), ("30 секунд вперёд", ("seekBy", 30)),
                                      ("минуту назад", ("seekBy", -60)), ("куда-то", None)])
def test_parse_seek(arg, want):
    assert parse_seek(arg) == want


def test_best_match_and_playlist_id():
    items = [{"name": "Бег вечером"}, {"name": "Бег"}]
    assert best_match(items, "бег", "name")["name"] == "Бег"
    assert best_match(items, "вечер", "name")["name"] == "Бег вечером"
    assert best_match(items, "сон", "name") is None
    assert parse_playlist_id("ym:12:3") == ("12", 3) and parse_playlist_id("ym:3") == (None, 3)


def test_station_tracks_continue_after_last_track():
    seen = {}

    class Client:
        def rotor_station_tracks(self, station, queue=None):
            seen.update(station=station, queue=queue)
            track = SimpleNamespace(id=2, title="T", artists=[], albums=[], duration_ms=0, cover_uri=None)
            return SimpleNamespace(sequence=[SimpleNamespace(track=track)], batch_id="b2")
    y = YandexProvider("tok", True, client_factory=lambda tok: Client())
    r = y.station_tracks("user:onyourwave", after="ym:1")
    assert seen == {"station": "user:onyourwave", "queue": "1"} and r["batch_id"] == "b2"


# ── сервис и агент целиком ───────────────────────────────────────────

class FakeSettings:
    def items(self):
        return {"music_folders": [], "video_folders": []}

    def set(self, k, v):
        pass


@pytest.fixture
def service(tmp_path):
    events = []
    ms = MediaService(events.append, FakeSettings(), data_dir=str(tmp_path), yandex=FakeProvider())
    yield ms, events
    ms.library.close()


def test_service_starts_music_while_player_is_silent(service):
    ms, events = service
    res = asyncio.run(ms.handle_command("music.play_album", "Nevermind"))
    assert res["status"] == "done" and events[-1]["cmd"] == "ym_play"


def test_service_track_named_error_is_still_done(service):
    ms, _ = service
    res = asyncio.run(ms.handle_command("music.play_track", "Ошибка"))
    assert res["ok"] is True and res["status"] == "done"


def test_service_open_app_shows_yandex_screen(service):
    ms, events = service
    assert asyncio.run(ms.handle_command("open_app:яндекс музыка")) == (True, "Открыла Яндекс Музыку")
    assert events[-1]["cmd"] == "ym_show"
    assert asyncio.run(ms.handle_command("open_app:блокнот")) is None


def test_service_autoplay(service):
    ms, events = service
    asyncio.run(ms.handle_command("music.autoplay", "wave"))
    assert events[-1]["arg"]["station"] == "user:onyourwave"
    asyncio.run(ms.cmd_state({"player": "music", "status": "playing", "title": "Song"}))
    assert asyncio.run(ms.handle_command("music.autoplay", "wave"))["status"] == "noop"


def test_service_remembers_current_track_and_queue(service):
    ms, _ = service
    asyncio.run(ms.cmd_state({"player": "music", "status": "playing", "title": "Song", "artist": "A",
                              "ym_id": "ym:5", "new_track": True}))
    asyncio.run(ms.cmd_queue({"index": 0, "items": [{"title": "Song", "artist": "A"}, {"title": "Next", "artist": "B"}]}))
    assert asyncio.run(ms.handle_command("music.history"))["detail"] == "Недавно: A — Song"
    assert asyncio.run(ms.handle_command("music.queue_show"))["detail"] == "Дальше: B — Next"
    assert asyncio.run(ms.handle_command("music.lyrics"))["status"] == "done"


def test_stream_goes_through_local_server(service):
    ms, _ = service
    ms.server.port = 5000
    assert asyncio.run(ms.cmd_yandex({"op": "stream", "id": "ym:42"}))["src"].startswith("http://127.0.0.1:5000/yandex/42?t=")


# ── вызовы совпадают с настоящей библиотекой yandex-music ────────────

class StrictProvider(YandexProvider):
    """Ошибка вызова (неверные аргументы) не прячется за ProviderError."""

    def _call(self, what, fn):
        return fn(self._get())


def test_provider_calls_match_real_library():
    yandex_music = pytest.importorskip("yandex_music")
    c = create_autospec(yandex_music.Client, instance=True)
    n = SimpleNamespace
    album = n(id=7, title="LP", artists=[], year=1991, track_count=1, cover_uri=None)
    track = n(id=5, title="T", artists=[n(id=8, name="A")], albums=[album], duration_ms=1000, cover_uri=None)
    pl = n(kind=3, title="Бег", track_count=1, revision=2, owner=n(uid=1), uid=1,
           tracks=[n(id="5:7", track=track)])
    block = lambda x: n(results=[x])  # noqa: E731
    c.search.return_value = n(tracks=block(track), albums=block(album), artists=block(n(id=8, name="A")), playlists=block(pl))
    c.users_playlists_list.return_value = [pl]
    c.users_playlists.return_value = pl
    c.users_playlists_create.return_value = pl
    c.artists_tracks.return_value = n(tracks=[track])
    c.albums_with_tracks.return_value = n(volumes=[[track]])
    c.tracks_similar.return_value = n(similar_tracks=[track])
    c.tracks_lyrics.return_value = n(fetch_lyrics=lambda: "текст")
    c.chart.return_value = n(chart=n(tracks=[n(track=track)]))
    c.new_releases.return_value = n(new_releases=[7])
    c.feed.return_value = n(generated_playlists=[n(type="playlistOfTheDay", data=pl)])
    c.rotor_stations_list.return_value = [n(station=n(id=n(type="genre", tag="rock"), name="Рок"))]
    c.rotor_station_tracks.return_value = n(sequence=[n(track=track)], batch_id="b")
    c.tracks.return_value = [track]
    c.tracks_download_info.return_value = [n(codec="mp3", bitrate_in_kbps=320, direct_link="https://s.yandex.net/x")]

    y = StrictProvider("tok", True, client_factory=lambda tok: c)
    assert y.search_all("q")["albums"][0]["title"] == "LP"
    assert y.find_artist("q") and y.find_album("q") and y.find_playlist("бег")
    assert y.artist_tracks(8) and y.album_tracks(7) and y.playlist_tracks("ym:1:3") and y.similar("ym:5")
    assert y.lyrics("ym:5") == "текст" and y.chart() and y.new_releases() and y.playlist_of_day()
    assert y.stations()[0]["id"] == "genre:rock" and y.station_tracks("genre:rock", after="ym:5")["batch_id"] == "b"
    for event in ("started", "trackStarted", "trackFinished", "skip"):
        y.station_feedback("genre:rock", event, "ym:5", 10.0, "b")
    assert y.stream_url("ym:5") == "https://s.yandex.net/x" and y.track_refs("ym:5")["album_id"] == "7"
    y.like("ym:5"), y.unlike("ym:5"), y.like_album("7"), y.like_artist("8")
    y.playlist_create("Новый"), y.playlist_add("ym:1:3", "ym:5"), y.playlist_delete("ym:1:3")
    y.playlist_remove("ym:1:3", "ym:5")
    c.users_playlists_delete_track.assert_called_once_with(3, 0, 1, revision=2)


# ── поток через медиасервер ──────────────────────────────────────────

class Upstream(io.BytesIO):
    status = 206
    headers = {"Content-Type": "audio/mpeg", "Content-Length": "4", "Content-Range": "bytes 0-3/10"}


@pytest.fixture
def server():
    s = MediaServer(library=None)
    s.start()
    yield s
    s.stop()


def fetch(url, **headers):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5)


def test_stream_proxy_passes_range_and_cors(server):
    seen = []
    server.yandex_link = lambda tid, fresh: f"https://s1.storage.yandex.net/{tid}"

    def opener(req):
        seen.append((req.full_url, req.get_header("Range")))
        return Upstream(b"data")
    server.yandex_open = opener
    r = fetch(server.url("/yandex/42"), Range="bytes=0-3")
    assert r.status == 206 and r.read() == b"data"
    assert r.headers["Access-Control-Allow-Origin"] == "*" and r.headers["Content-Range"] == "bytes 0-3/10"
    assert seen == [("https://s1.storage.yandex.net/42", "bytes=0-3")]


def test_stream_proxy_refreshes_expired_link(server):
    fresh_flags = []

    def link(tid, fresh):
        fresh_flags.append(fresh)
        return "https://s1.storage.yandex.net/x"
    server.yandex_link = link

    def opener(req):
        if len(fresh_flags) == 1:
            raise urllib.error.HTTPError(req.full_url, 410, "gone", {}, io.BytesIO())
        return Upstream(b"data")
    server.yandex_open = opener
    assert fetch(server.url("/yandex/42")).read() == b"data"
    assert fresh_flags == [False, True]


def test_stream_proxy_rejects_foreign_hosts_and_bad_ids(server):
    server.yandex_link = lambda tid, fresh: "https://evil.example/x"
    server.yandex_open = lambda req: pytest.fail("чужой хост не должен открываться")
    with pytest.raises(urllib.error.HTTPError) as e:
        fetch(server.url("/yandex/42"))
    assert e.value.code == 502
    with pytest.raises(urllib.error.HTTPError) as e2:
        fetch(server.url("/yandex/..%2f42"))
    assert e2.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e3:
        fetch(f"{server.origin}/yandex/42")
    assert e3.value.code == 401


@pytest.mark.parametrize("url,ok", [("https://s1.storage.yandex.net/a", True), ("http://s1.storage.yandex.net/a", False),
                                    ("https://yandex.net.evil.com/a", False), ("https://evilyandex.net/a", False)])
def test_host_allowlist(url, ok):
    assert ym_host_allowed(url) is ok
