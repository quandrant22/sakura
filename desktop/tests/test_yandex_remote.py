"""Пульт приложения Яндекс.Музыки (п. 6) на фейковом SMTC и фейковой громкости сессии."""
import asyncio

from desktop.core.media.yandex_remote import TOKEN_HINT, YandexRemote


class FakeSMTC:
    def __init__(self, info=None, shuffle=False, repeat="none", supports=True):
        self.info = info
        self.modes = {"shuffle": shuffle, "repeat": repeat}
        self.supports = supports
        self.calls = []

    async def _smtc_get_info(self):
        self.calls.append("read")
        # Режимы приходят в том же чтении (music._modes_of).
        return {**self.info, **self.modes} if self.info else self.info

    async def smtc_modes(self):
        return dict(self.modes)

    async def smtc_cover(self):
        return b"\x89PNG\r\n\x1a\nxx"

    async def _smtc_control(self, op):
        self.calls.append(op)
        return self.info is not None

    async def smart_prev(self):
        self.calls.append("smart_prev")
        return {"ok": True, "status": "done", "detail": "предыдущий трек"}

    async def restart_track(self):
        self.calls.append("restart")
        return {"ok": True, "status": "done", "detail": "трек сначала"}

    async def smtc_set_position(self, s):
        self.calls.append(("seek", s))
        return self.supports

    async def smtc_set_shuffle(self, on):
        self.calls.append(("shuffle", on))
        return self.supports

    async def smtc_set_repeat(self, mode):
        self.calls.append(("repeat", mode))
        return self.supports


class FakePlatform:
    def __init__(self, volume=40):
        self.volume = volume
        self.gets = 0

    def app_volume_get(self, names):
        assert "yandex" in names
        self.gets += 1
        return self.volume

    def app_volume_set(self, names, percent):
        if self.volume is None:
            return None
        self.volume = max(0, min(100, percent))
        return self.volume


class FakeButtons:
    """Кнопки окна Яндекс.Музыки (UI Automation)."""
    def __init__(self, press="no_a11y", state=None):
        self.result, self.st, self.pressed = press, state or {}, []

    def press(self, kind):
        self.pressed.append(kind)
        return self.result

    def state(self, kind):
        return self.st.get(kind)


class FakeLikes:
    def __init__(self, liked=False):
        self.is_liked, self.calls = liked, []

    def liked(self, title, artist):
        return self.is_liked

    def toggle_like(self, title, artist):
        self.calls.append(("like", title, artist))
        self.is_liked = not self.is_liked
        return {"ok": True, "status": "done", "detail": "поставила лайк" if self.is_liked else "убрала лайк",
                "liked": self.is_liked}

    def dislike(self, title, artist):
        self.calls.append(("dislike", title, artist))
        return {"ok": True, "status": "done", "detail": "дизлайк"}

    def lyrics(self, title, artist):
        return {"ok": True, "status": "done", "detail": "текст песни", "lyrics": "ла-ла"}


INFO = {"title": "Песня", "artist": "Певица", "album": "Альбом", "playing": True,
        "position_s": 12.0, "duration_s": 200.0, "updated_age_s": 0.5}


def run(c):
    return asyncio.run(c)


def remote(info=INFO, available=True, running=True, token="", volume=40, buttons=None, likes=None, watch=None,
           clock=None, **kw):
    """watch=None — без наблюдателя SMTC (одно чтение); с FakeWatch — снимок наблюдателя."""
    extra = {"clock": clock} if clock else {}
    return YandexRemote(smtc=FakeSMTC(info, **kw), platform=FakePlatform(volume), available=lambda: available,
                        running=lambda: running, token=token, open_link=lambda url: url == "yandexmusic://",
                        buttons=buttons or FakeButtons(), likes=likes or FakeLikes(), watch=watch, **extra)


class FakeWatch:
    def __init__(self, snap):
        self.snap = snap

    def snapshot(self):
        return dict(self.snap) if self.snap else self.snap


def test_state_ok_modes_volume_without_cover():
    st = run(remote(shuffle=True, repeat="list").state())
    assert st["status"] == "ok" and st["title"] == "Песня" and st["playing"] is True
    assert st["shuffle"] is True and st["repeat"] == "list" and st["volume"] == 40
    assert "cover" not in st  # обложка — только событием music_cover
    assert st["can_like"] is False and st["like_hint"] == TOKEN_HINT


def test_state_is_watch_snapshot_with_seq_no_smtc_read():
    snap = {**INFO, "status": "ok", "seq": 9, "track_seq": 7, "shuffle": False, "repeat": "none"}
    r = remote(watch=FakeWatch(snap))
    st = run(r.state())
    assert st["seq"] == 9 and st["track_seq"] == 7 and st["title"] == "Песня"
    assert r.smtc.calls == []  # SMTC заново не читается
    assert run(remote(watch=FakeWatch({"status": "starting", "seq": 3})).state())["status"] == "starting"
    assert run(remote(watch=FakeWatch(None)).state())["status"] == "starting"  # первое чтение ещё не прошло


def test_volume_in_thread_cached_two_seconds():
    import threading
    t = [0.0]
    r = remote(watch=FakeWatch({**INFO, "status": "ok", "seq": 1}), clock=lambda: t[0])
    main = threading.get_ident()
    seen = []
    orig = r.platform.app_volume_get
    r.platform.app_volume_get = lambda names: seen.append(threading.get_ident()) or orig(names)
    run(r.state())
    run(r.state())
    assert r.platform.gets == 1
    t[0] = 2.1
    run(r.state())
    assert r.platform.gets == 2
    assert seen and all(x != main for x in seen)  # COM громкости — не в потоке цикла


def test_states_idle_not_running_no_smtc():
    assert run(remote(info=None, running=True).state())["status"] == "idle"
    assert run(remote(info=None, running=False).state())["status"] == "not_running"
    assert run(remote(available=False).state())["status"] == "no_smtc"


def test_shuffle_toggles_and_repeat_cycles():
    r = remote(shuffle=False, repeat="none")
    assert run(r.control("shuffle"))["ok"] is True
    assert run(r.control("repeat"))["detail"] == "повтор: list"
    assert r.smtc.calls == [("shuffle", True), ("repeat", "list")]


def test_unsupported_by_app_is_honest():
    r = remote(supports=False)
    for op in ("shuffle", "repeat", "seek"):
        out = run(r.control(op, 10 if op == "seek" else None))
        assert out["ok"] is False and out["status"] == "unsupported"


def test_prev_restart_seek_route_to_smtc():
    r = remote()
    run(r.control("prev"))
    run(r.control("restart"))
    run(r.control("seek", 42))
    assert r.smtc.calls == ["smart_prev", "restart", ("seek", 42.0)]


def test_session_volume_and_mute():
    r = remote(volume=40)
    assert run(r.control("volume_by", 10))["detail"] == "громкость Яндекс.Музыки 50%"
    assert run(r.control("mute"))["detail"] == "звук Яндекс.Музыки выключен"
    out = run(remote(volume=None).control("volume", 30))
    assert out["status"] == "noop" and out["retry_ms"] == 2000 and "повторю через 2 с" in out["detail"]


def test_like_without_token_disabled():
    for op in ("like", "dislike", "lyrics"):
        out = run(remote(token="").control(op))
        assert out == {"ok": False, "status": "unsupported", "detail": TOKEN_HINT, "help": "token"}
    assert "YANDEX_MUSIC_TOKEN" in TOKEN_HINT and r"C:\sakura-git\agent\.env" in TOKEN_HINT


def test_no_player_is_noop_and_open_app():
    r = remote(info=None)
    assert run(r.control("next"))["status"] == "noop"
    assert run(r.control("open_app"))["ok"] is True


def test_seek_by_relative_and_no_player():
    r = remote()
    r.smtc.smtc_position = _async_value(30.0)
    assert run(r.control("seek_by", 10))["ok"] is True
    assert r.smtc.calls[-1] == ("seek", 40.0)
    run(r.control("seek_by", -60))
    assert r.smtc.calls[-1] == ("seek", 0.0)  # не уходит в минус
    r.smtc.smtc_position = _async_value(None)
    assert run(r.control("seek_by", 10))["status"] == "noop"


def test_podcasts_need_uid(monkeypatch):
    from desktop.core import config
    monkeypatch.setattr(config, "YANDEX_UID", "", raising=False)
    assert run(remote().control("podcasts"))["status"] == "unsupported"
    monkeypatch.setattr(config, "YANDEX_UID", "123", raising=False)
    opened = []
    r = YandexRemote(smtc=FakeSMTC(INFO), platform=FakePlatform(), available=lambda: True, running=lambda: True,
                     token="", open_link=lambda url: opened.append(url) or True)
    assert run(r.control("podcasts"))["ok"] is True
    assert opened == ["https://music.yandex.ru/users/123/podcast-subscriptions"]


def _async_value(v):
    async def f():
        return v
    return f


# ── перемешивание и повтор: SMTC → кнопка окна → честный отказ ──
def test_modes_fall_back_to_window_buttons():
    b = FakeButtons(press="done")
    r = remote(supports=False, buttons=b)
    assert run(r.control("shuffle"))["ok"] is True and run(r.control("repeat"))["ok"] is True
    assert b.pressed == ["shuffle", "repeat"]


def test_modes_without_accessibility_explain_how():
    r = remote(supports=False, buttons=FakeButtons(press="no_a11y"))
    out = run(r.control("shuffle"))
    assert out["status"] == "unsupported" and out["help"] == "a11y"
    assert "Перезапустить с поддержкой кнопок" in out["detail"]
    out = run(remote(supports=False, buttons=FakeButtons(press="no_window")).control("repeat"))
    assert "окно Яндекс.Музыки не найдено" in out["detail"]


def test_state_reads_modes_from_window_when_smtc_has_none():
    r = remote(shuffle=None, repeat=None, buttons=FakeButtons(state={"shuffle": True, "repeat": False}))
    st = run(r.state())
    assert st["shuffle"] is True and st["repeat"] == "none"


# ── лайк, дизлайк, текст с токеном (фейковый API) ──
def test_like_toggle_dislike_lyrics_with_token():
    likes = FakeLikes(liked=False)
    r = remote(token="t", likes=likes)
    assert run(r.state())["liked"] is None             # лайк ещё не узнан (фон после смены трека)
    assert run(r.liked_for("Песня", "Певица")) is False  # фон: API в потоке, в кэш
    st = run(r.state())
    assert st["can_like"] is True and st["liked"] is False
    assert run(r.control("like"))["liked"] is True
    assert run(r.control("like"))["detail"] == "убрала лайк"
    assert run(r.control("dislike"))["ok"] is True
    assert run(r.control("lyrics"))["lyrics"] == "ла-ла"
    assert likes.calls[0] == ("like", "Песня", "Певица")


def test_like_without_player_is_noop():
    r = remote(token="t", info=None)
    assert run(r.control("like"))["status"] == "noop"


def test_smtc_modes_not_attempted_without_support(monkeypatch):
    """Живая проверка 15.10: приложение отвечает True на смену режима при is_*_enabled=False — ложный успех."""
    from types import SimpleNamespace as NS

    from desktop.core import music
    calls = []

    async def ok(*a):
        calls.append(a)
        return True
    sess = NS(get_playback_info=lambda: NS(controls=NS(is_shuffle_enabled=False, is_repeat_enabled=False)),
              try_change_shuffle_active_async=ok, try_change_auto_repeat_mode_async=ok)

    async def session():
        return sess
    monkeypatch.setattr(music, "_session", session)
    assert asyncio.run(music.smtc_set_shuffle(True)) is False
    assert asyncio.run(music.smtc_set_repeat("list")) is False
    assert calls == []
