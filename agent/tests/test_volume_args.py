"""tests/test_volume_args.py — число громкости доходит до hands."""

import asyncio

import pytest

import config
from core import agent as agent_module


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


def make_agent():
    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = FakeWS()
    return a


@pytest.fixture
def calls(monkeypatch):
    rec = {"exec": [], "nudge": []}
    monkeypatch.setattr(agent_module, "execute_command",
                        lambda action: rec["exec"].append(action) or {"result": "ok"})
    monkeypatch.setattr(agent_module, "_nudge_volume",
                        lambda delta: rec["nudge"].append(delta) or "ok")
    return rec


def run(action, arg=""):
    asyncio.run(make_agent()._run_command(action, "id1", arg))


def test_volume_arg_joined(calls):
    run("volume", "70")
    assert calls["exec"] == ["volume:70"]


def test_volume_without_arg(calls):
    run("volume")
    assert calls["exec"] == ["volume"]


def test_action_with_colon_unchanged(calls):
    run("volume:30", "70")
    assert calls["exec"] == ["volume:30"]


def test_music_volume_up_by_number(calls):
    run("music.volume_up", "20")
    assert calls["nudge"] == [20]


def test_music_volume_up_default_step(calls, monkeypatch):
    monkeypatch.setattr(config, "VOLUME_STEP", 10)
    run("music.volume_up")
    assert calls["nudge"] == [10]


def test_music_volume_down_by_number(calls):
    run("music:volume_down", "5")
    assert calls["nudge"] == [-5]
