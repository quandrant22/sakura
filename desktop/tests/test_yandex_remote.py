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
        return self.info

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

    def app_volume_get(self, names):
        assert "yandex" in names
        return self.volume

    def app_volume_set(self, names, percent):
        if self.volume is None:
            return None
        self.volume = max(0, min(100, percent))
        return self.volume


INFO = {"title": "Песня", "artist": "Певица", "album": "Альбом", "playing": True,
        "position_s": 12.0, "duration_s": 200.0, "updated_age_s": 0.5}


def run(c):
    return asyncio.run(c)


def remote(info=INFO, available=True, running=True, token="", volume=40, **kw):
    return YandexRemote(smtc=FakeSMTC(info, **kw), platform=FakePlatform(volume), available=lambda: available,
                        running=lambda: running, token=token, open_link=lambda url: url == "yandexmusic://")


def test_state_ok_with_cover_modes_volume():
    st = run(remote(shuffle=True, repeat="list").state())
    assert st["status"] == "ok" and st["title"] == "Песня" and st["playing"] is True
    assert st["shuffle"] is True and st["repeat"] == "list" and st["volume"] == 40
    assert st["cover"].startswith("data:image/png;base64,")
    assert st["can_like"] is False and st["like_hint"] == TOKEN_HINT


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
    assert run(remote(volume=None).control("volume", 30))["status"] == "noop"


def test_like_without_token_disabled():
    out = run(remote(token="").control("like"))
    assert out == {"ok": False, "status": "unsupported", "detail": TOKEN_HINT}


def test_no_player_is_noop_and_open_app():
    r = remote(info=None)
    assert run(r.control("next"))["status"] == "noop"
    assert run(r.control("open_app"))["ok"] is True
