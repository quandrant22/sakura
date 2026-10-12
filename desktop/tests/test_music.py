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


@pytest.mark.parametrize("action,label", [("music_play_pause", "play/pause"), ("music_next", "следующий")])
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


# ── п. 7: «предыдущий трек» (умный двойной шаг) и «трек сначала» на фейковом SMTC ──

def _fake_smtc(position, ok=True):
    presses, sleeps = [], []

    async def get_position():
        return position

    async def press_prev():
        presses.append(1)
        return ok

    async def sleep(s):
        sleeps.append(s)
    return get_position, press_prev, sleep, presses, sleeps


@pytest.mark.parametrize("position,presses", [(10.0, 2), (1.0, 1), (3.0, 1), (None, 2)])
def test_smart_prev(position, presses):
    gp, pp, sl, pressed, slept = _fake_smtc(position)
    r = run(music.smart_prev(gp, pp, sl, threshold_s=3.0, gap_ms=250))
    assert r["ok"] is True and r["status"] == "done"
    assert len(pressed) == presses
    assert slept == ([0.25] if presses == 2 else [])


def test_smart_prev_no_player():
    gp, pp, sl, pressed, _ = _fake_smtc(10.0, ok=False)
    r = run(music.smart_prev(gp, pp, sl, threshold_s=3.0, gap_ms=250))
    assert r["status"] == "noop" and len(pressed) == 1


def test_restart_prefers_position_zero_then_single_press():
    calls = []

    async def set_pos(s):
        calls.append(("pos", s))
        return True

    async def press():
        calls.append("press")
        return True
    assert run(music.restart_track(set_pos, press))["ok"] is True
    assert calls == [("pos", 0)]

    async def no_pos(s):
        calls.append(("pos", s))
        return False
    calls.clear()
    assert run(music.restart_track(no_pos, press))["ok"] is True
    assert calls == [("pos", 0), "press"]  # ровно одно нажатие


def test_extrapolate_position():
    info = {"position_s": 10.0, "duration_s": 200.0, "playing": True, "updated_age_s": 2.5}
    assert music.extrapolate_position(info) == 12.5
    assert music.extrapolate_position({**info, "playing": False}) == 10.0
    assert music.extrapolate_position({**info, "updated_age_s": 500}) == 200.0
    assert music.extrapolate_position(None) is None
