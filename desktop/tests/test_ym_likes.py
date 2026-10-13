"""Лайк и дизлайк через API yandex-music — на фейковом клиенте."""
from types import SimpleNamespace as NS

from desktop.core.media.ym_likes import API_DOWN, NOT_FOUND, YmLikes


class FakeClient:
    def __init__(self, catalog=None, liked=()):
        self.catalog = catalog if catalog is not None else {"Певица Песня": "101"}
        self.liked = set(liked)
        self.searches = 0
        self.me = NS(account=NS(uid=7))
        self.disliked = []

    def search(self, q, type_):
        self.searches += 1
        tid = self.catalog.get(q)
        return NS(tracks=NS(results=[NS(id=tid)] if tid else []))

    def users_likes_tracks(self, user_id):
        return NS(tracks=[NS(id=f"{t}:555") for t in self.liked])

    def users_likes_tracks_add(self, tid, user_id):
        self.liked.add(tid)
        return True

    def users_likes_tracks_remove(self, tid, user_id):
        self.liked.discard(tid)
        return True

    def users_dislikes_tracks_add(self, tid, user_id):
        self.disliked.append(tid)
        self.liked.discard(tid)
        return True

    def tracks_lyrics(self, tid, format_):
        return NS(fetch_lyrics=lambda: "куплет")


def make(**kw):
    c = FakeClient(**kw)
    t = [0.0]
    return YmLikes(client_factory=lambda: c, clock=lambda: t[0]), c, t


def test_like_toggles_and_heart_state_updates():
    y, c, _ = make()
    assert y.liked("Песня", "Певица") is False
    assert y.toggle_like("Песня", "Певица")["liked"] is True
    assert y.liked("Песня", "Певица") is True
    out = y.toggle_like("Песня", "Певица")
    assert out["detail"] == "убрала лайк" and out["liked"] is False


def test_track_id_cached():
    y, c, _ = make()
    for _ in range(3):
        y.liked("Песня", "Певица")
    assert c.searches == 1


def test_liked_list_refreshed_by_ttl():
    y, c, t = make()
    assert y.liked("Песня", "Певица") is False
    c.liked.add("101")  # лайк поставлен в приложении
    assert y.liked("Песня", "Певица") is False  # кэш
    t[0] = 61
    assert y.liked("Песня", "Певица") is True


def test_dislike_and_lyrics():
    y, c, _ = make(liked={"101"})
    assert y.dislike("Песня", "Певица")["ok"] is True and c.disliked == ["101"]
    assert y.liked("Песня", "Певица") is False
    assert y.lyrics("Песня", "Певица")["lyrics"] == "куплет"


def test_not_found_and_api_down():
    y, _, _ = make(catalog={})
    assert y.toggle_like("Нет", "Никто") == {"ok": False, "status": "failed", "detail": NOT_FOUND}
    assert y.liked("Нет", "Никто") is None

    def boom():
        raise OSError("сеть")
    y = YmLikes(client_factory=boom)
    assert y.toggle_like("Песня", "Певица")["detail"] == API_DOWN
    assert y.dislike("Песня", "Певица")["detail"] == API_DOWN
