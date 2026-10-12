"""tests/test_music_restart.py — music.restart и двойной шаг music.prev (SMTC).

SMTC-«назад» в середине трека начинает его сначала, поэтому:
  * music.restart — позиция в 0 (не умеет — одиночный «назад»);
  * music.prev    — трек уже играет (> 3 с) — два шага «назад», иначе один.
"""

import asyncio
import sys
import types

import pytest

from core import agent as agent_module
from core import music


class FakeSession:
    def __init__(self, position_s=30.0, can_seek=True):
        self.position_s = position_s
        self.can_seek = can_seek
        self.calls = []

    def get_timeline_properties(self):
        pos = types.SimpleNamespace(total_seconds=lambda: self.position_s)
        return types.SimpleNamespace(position=pos)

    async def try_skip_previous_async(self):
        self.calls.append("prev")
        self.position_s = 0.0
        return True

    async def try_change_playback_position_async(self, ticks):
        self.calls.append(("seek", ticks))
        return self.can_seek

    async def try_skip_next_async(self):
        self.calls.append("next")
        return True


@pytest.fixture
def session(monkeypatch):
    holder = {}

    class FakeManager:
        @staticmethod
        async def request_async():
            return types.SimpleNamespace(get_current_session=lambda: holder["s"])

    control = types.ModuleType("winsdk.windows.media.control")
    control.GlobalSystemMediaTransportControlsSessionManager = FakeManager
    for name in ("winsdk", "winsdk.windows", "winsdk.windows.media"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "winsdk.windows.media.control", control)
    monkeypatch.setattr(music, "_pick_yamusic_session", lambda mgr: None)
    monkeypatch.setattr(music, "PREV_SECOND_STEP_DELAY_S", 0.0)

    def make(**kw):
        holder["s"] = FakeSession(**kw)
        return holder["s"]
    return make


def test_restart_seeks_to_zero(session):
    s = session(position_s=95.0)
    assert asyncio.run(music._smtc_control("restart"))
    assert s.calls == [("seek", 0)]


def test_restart_falls_back_to_single_prev(session):
    s = session(position_s=95.0, can_seek=False)
    assert asyncio.run(music._smtc_control("restart"))
    assert s.calls == [("seek", 0), "prev"]


def test_prev_mid_track_double_step(session):
    s = session(position_s=40.0)
    assert asyncio.run(music._smtc_control("prev"))
    assert s.calls == ["prev", "prev"]


def test_prev_at_track_start_single_step(session):
    s = session(position_s=1.0)
    assert asyncio.run(music._smtc_control("prev"))
    assert s.calls == ["prev"]


def test_music_command_restart_label(session):
    session(position_s=10.0)
    r = asyncio.run(music.music_command("music_restart"))
    assert r == {"ok": True, "result": "сначала"}


@pytest.mark.parametrize("wire", ["music.restart", "music_restart", "music:restart"])
def test_canonical_restart_goes_to_smtc(wire):
    assert agent_module._music_canonical(wire) == ("smtc", "music.restart", "music_restart")
