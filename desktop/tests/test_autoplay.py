"""«Включи музыку» (music.autoplay) на подставном слое: приложение, SMTC и кнопки окна — фейки."""
import asyncio

import pytest

from desktop.core.media import autoplay as AP


class Fake:
    def __init__(self, running=True, with_flag=True, status="paused", smtc_ok=True, ui_ok=True, ui_plays=True,
                 token=True, window=True, plays_after=0.0):
        self.t = 0.0
        self.running, self.with_flag = running, with_flag
        self._status = status if running else None
        self.smtc_ok, self.ui_ok, self.ui_plays = smtc_ok, ui_ok, ui_plays
        self.token, self.window = token, window
        self.calls = []
        self.play_at = None
        self.plays_after = plays_after

    # приложение
    def app_state(self):
        return {"running": self.running, "with_flag": self.with_flag}

    def launch(self):
        self.calls.append("launch")
        self.running, self.with_flag, self._status = True, True, None
        return {"ok": True, "status": "done", "detail": "открыла"}

    def restart(self):
        self.calls.append("restart")
        self.with_flag = True
        return {"ok": True, "status": "done", "detail": "перезапустила"}

    # SMTC
    async def status(self):
        if self.play_at is not None and self.t >= self.play_at:
            return "playing"
        return self._status

    async def smtc_play(self):
        self.calls.append("smtc")
        if self.smtc_ok and self._status is not None:
            self.play_at = self.t + self.plays_after
            return True
        return False

    # UI Automation
    def play_bar(self):
        self.calls.append("play_bar")
        return self._ui()

    def open_link(self, name):
        self.calls.append(f"link:{name}")
        return self.ui_ok

    def play_main(self):
        self.calls.append("play_main")
        return self._ui()

    def _ui(self):
        if self.ui_ok and self.ui_plays:
            self.play_at = self.t + self.plays_after
        return self.ui_ok

    def deps(self):
        async def sleep(s):
            self.t += s
        return AP.Deps(status=self.status, smtc_play=self.smtc_play, app_state=self.app_state, launch=self.launch,
                       restart=self.restart, ui=self, has_token=lambda: self.token,
                       window_ready=lambda: self.window and self.running, sleep=sleep, clock=lambda: self.t)


def run(f, target="wave", ap=None):
    ap = ap or AP.Autoplay(f.deps())
    return asyncio.run(ap.run(target)), ap


def test_already_playing_noop():
    f = Fake(status="playing")
    out, _ = run(f)
    assert out["status"] == "noop" and out["detail"] == "уже играет" and f.calls == []


def test_not_running_launch_then_wave_via_ui():
    f = Fake(running=False)
    out, _ = run(f)
    assert out["ok"] is True and out["detail"] == "включила «Мою волну»"
    assert f.calls == ["launch", "link:Моя волна", "play_main"]


def test_running_without_flag_restarts_with_flag():
    f = Fake(with_flag=False)
    out, _ = run(f)
    assert out["ok"] is True and f.calls[0] == "restart"


def test_last_uses_smtc_first():
    f = Fake(status="paused")
    out, _ = run(f, "last")
    assert out["ok"] is True and f.calls == ["smtc"]


def test_last_smtc_fails_then_ui_bar():
    f = Fake(smtc_ok=False)
    out, _ = run(f, "last")
    assert out["ok"] is True and f.calls == ["smtc", "play_bar"]


def test_last_without_session_skips_smtc():
    f = Fake(status=None)
    out, _ = run(f, "last")
    assert out["ok"] is True and f.calls == ["play_bar"]


def test_ui_pressed_but_not_playing_within_5s_fails():
    f = Fake(ui_plays=False)
    out, _ = run(f)
    assert out["status"] == "failed" and out["detail"] == AP.FAIL_TEXT
    assert f.calls.count("play_main") == 2  # вторая попытка — окно могло дорисовываться


def test_plays_after_delay_within_5s_ok():
    f = Fake(plays_after=4.0)
    out, _ = run(f)
    assert out["ok"] is True


def test_window_never_appears_timeout():
    f = Fake(window=False)
    out, _ = run(f)
    assert out["status"] == "failed" and "15 с" in out["detail"]


def test_any_falls_back_to_wave():
    f = Fake(status=None)
    f.play_bar = lambda: (f.calls.append("play_bar"), False)[1]
    out, _ = run(f, "any")
    assert out["ok"] is True and "link:Моя волна" in f.calls


def test_repeat_within_10s_no_second_start():
    f = Fake()
    out, ap = run(f)
    f.play_at = None
    f._status = "paused"  # музыку остановили, но команда пришла повторно сразу
    n = len(f.calls)
    out2, _ = run(f, ap=ap)
    assert out2["status"] == "noop" and len(f.calls) == n
    f.t += 11
    out3, _ = run(f, ap=ap)
    assert out3["ok"] is True


@pytest.mark.parametrize("target", ["liked", "playlist_of_day"])
def test_token_targets(target):
    out, _ = run(Fake(token=False), target)
    assert out["status"] == "unsupported" and "YANDEX_MUSIC_TOKEN" in out["detail"]
    out, _ = run(Fake(token=True), target)
    if target == "liked":
        assert out["ok"] is True
    else:
        assert out["status"] == "unsupported"


def test_unknown_target():
    assert run(Fake(), "jazz")[0]["status"] == "failed"


def test_agent_routes_music_autoplay():
    import json
    from types import SimpleNamespace

    from desktop.core import agent as agent_mod
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(json.loads(raw))
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a._ws, a.bus, a.media, a.server_link = WS(), None, None, None
    got = []

    async def fake_run(target):
        got.append(target)
        return {"ok": True, "status": "done", "detail": "включила «Мою волну»"}
    a.autoplay = SimpleNamespace(run=fake_run)
    asyncio.run(a._run_command("music.autoplay", "c1", ""))
    assert got == ["wave"] and sent[-1]["ok"] is True
