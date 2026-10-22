"""Доступ по токену (yandex_api) на подставном клиенте: счётчики, ошибки 401/403 не роняют."""
import asyncio
from types import SimpleNamespace as NS

from desktop.core.media.yandex_api import YandexApi, _ThreadedClient


class Fake:
    def __init__(self, fail=None):
        self.me = NS(account=NS(uid=1))
        self.fail = fail or {}

    def _r(self, name, value):
        async def f(*a, **k):
            if name in self.fail:
                raise self.fail[name]
            return value
        return f

    def __getattr__(self, name):
        track = NS(id=5, title="Песня", artists=[NS(name="Кто")], albums=[NS(id=9, year=2020, genre="rock")])
        values = {
            "account_status": NS(plus=NS(has_plus=True)), "users_likes_tracks": NS(tracks=[1, 2, 3]),
            "users_dislikes_tracks": NS(tracks=[1]), "users_playlists_list": [NS(title="A"), NS(title="B")],
            "feed": NS(generated_playlists=[NS(type="playlistOfTheDay", data=NS(title="Плейлист дня", kind=7, uid=1))]),
            "music_history": NS(items=[1]), "rotor_stations_list": [1, 2], "search": NS(tracks=NS(results=[track])),
            "new_releases": NS(new_releases=[1]), "tracks_lyrics": NS(), "tracks_similar": NS(similar_tracks=[track]),
            "tracks": [track]}
        return self._r(name, values.get(name))


def api(fake):
    async def make():
        return fake
    return YandexApi(client_factory=make, token="t")


def test_inventory_counts_only():
    out = asyncio.run(api(Fake()).inventory())
    assert out["ok"] and out["plus"] is True
    assert out["items"]["лайки"] == {"ok": True, "count": 3}
    assert out["items"]["плейлисты"]["count"] == 2
    assert "Песня" not in repr(out) and "Кто" not in repr(out)  # наружу — только счётчики и статусы


def test_401_403_do_not_crash():
    out = asyncio.run(api(Fake(fail={"users_likes_tracks": Exception("Unauthorized 401"),
                                     "feed": Exception("Forbidden 403")})).inventory())
    assert out["ok"] is True
    assert "401" in out["items"]["лайки"]["error"] and "403" in out["items"]["ленточные плейлисты"]["error"]


def test_no_token():
    assert asyncio.run(YandexApi(token="").inventory()) == {"token": False}


def test_explicit_actions():
    a = api(Fake())
    assert asyncio.run(a.playlists())["playlists"] == ["A", "B"]
    assert asyncio.run(a.playlist_of_day())["title"] == "Плейлист дня"
    assert asyncio.run(a.similar("Песня", "Кто"))["tracks"] == ["Кто — Песня"]
    assert asyncio.run(a.enrich("Песня", "Кто"))["album_id"] == "9"


def test_threaded_client_adapter():
    sync = NS(me=NS(account=NS(uid=3)), feed=lambda: "лента", value=5)
    c = _ThreadedClient(sync)
    assert c.me.account.uid == 3 and asyncio.run(c.feed()) == "лента" and c.value == 5
