"""Музыка: API Яндекс.Музыки (фейковый клиент), music_command поверх SMTC (подменён),
deep link приложения Яндекс.Музыки."""
import asyncio
from types import SimpleNamespace

import pytest

from desktop.core import music, yamusic_app


class FakeYM:
    def __init__(self, found=True, accept=True):
        self.found, self.accept, self.calls = found, accept, []
        self.me = SimpleNamespace(account=SimpleNamespace(uid=7))

    def search(self, q, type_):
        self.calls.append(("search", q))
        if not self.found:
            return SimpleNamespace(tracks=SimpleNamespace(results=[]))
        t = SimpleNamespace(id=123, title="Song", artists=[SimpleNamespace(name="Artist")])
        return SimpleNamespace(tracks=SimpleNamespace(results=[t]))

    def users_likes_tracks_add(self, tid, user_id):
        self.calls.append(("like", tid, user_id))
        return self.accept

    def users_dislikes_tracks_add(self, tid, user_id):
        self.calls.append(("dislike", tid, user_id))
        return self.accept


def run(c):
    return asyncio.run(c)


@pytest.fixture
def ym(monkeypatch):
    client = FakeYM()
    monkeypatch.setattr(music, "_get_ym_client", lambda: client)
    return client


def test_like_and_dislike_via_api(ym):
    assert music._ym_like_current("Song", "Artist") == {"ok": True, "result": "Лайк: Artist — Song"}
    assert music._ym_dislike_current("Song", "Artist")["ok"] is True
    assert ("like", "123", 7) in ym.calls and ("dislike", "123", 7) in ym.calls


def test_like_not_found_and_rejected(monkeypatch):
    monkeypatch.setattr(music, "_get_ym_client", lambda: FakeYM(found=False))
    assert music._ym_like_current("x", "y")["ok"] is False
    monkeypatch.setattr(music, "_get_ym_client", lambda: FakeYM(accept=False))
    assert "не приняла" in music._ym_like_current("x", "y")["result"]


def test_like_without_token(monkeypatch):
    monkeypatch.setattr(music, "_ym_client", None)
    monkeypatch.setattr(music, "_ym_token", lambda: "")
    r = music._ym_like_current("x", "y")
    assert r["ok"] is False and "недоступен" in r["result"]


def _smtc(monkeypatch, info, control_ok=True):
    async def get_info():
        return info

    async def control(cmd):
        return control_ok
    monkeypatch.setattr(music, "_smtc_get_info", get_info)
    monkeypatch.setattr(music, "_smtc_control", control)


def test_music_info_formats_track(monkeypatch):
    _smtc(monkeypatch, {"title": "Song", "artist": "Artist", "status": "пауза",
                        "duration": "3:10", "position": "0:42"})
    monkeypatch.setattr(music, "_enrich_with_ym", lambda a, t: None)
    r = run(music.music_command("music_info"))
    assert r["ok"] and r["result"] == "Artist — Song (пауза) [0:42 / 3:10]"


def test_music_info_nothing_playing(monkeypatch):
    _smtc(monkeypatch, None)
    assert run(music.music_command("music_info")) == {"ok": False, "result": "Ничего не играет"}


@pytest.mark.parametrize("action,label", [("music_play_pause", "play/pause"), ("music_next", "следующий"),
                                          ("music_prev", "предыдущий")])
def test_smtc_controls(monkeypatch, action, label):
    _smtc(monkeypatch, None, control_ok=True)
    assert run(music.music_command(action)) == {"ok": True, "result": label}
    _smtc(monkeypatch, None, control_ok=False)
    assert run(music.music_command(action))["result"] == "Нет активного плеера"


def test_music_like_uses_current_track(monkeypatch, ym):
    _smtc(monkeypatch, {"title": "Song", "artist": "Artist"})
    assert run(music.music_command("music_like"))["ok"] is True


def test_yamusic_wave_deep_link(monkeypatch):
    opened = []
    monkeypatch.setattr(yamusic_app.os, "startfile", opened.append, raising=False)
    assert yamusic_app.open_wave() is True
    assert opened and opened[0].endswith("radio/user/onyourwave")


def test_yamusic_deep_link_failure(monkeypatch):
    def boom(url):
        raise OSError("нет приложения")
    monkeypatch.setattr(yamusic_app.os, "startfile", boom, raising=False)
    assert yamusic_app.open_playlist("p1") is False
