"""tests/test_vad_short.py — короткая фраза заканчивается по укороченной тишине."""

import pytest

import config
from core.hearing import _end_silence_for


@pytest.fixture(autouse=True)
def vad_cfg(monkeypatch):
    monkeypatch.setattr(config, "VAD_END_SILENCE", 1.0)
    monkeypatch.setattr(config, "VAD_END_SILENCE_SHORT", 0.7)
    monkeypatch.setattr(config, "VAD_SHORT_UTTER_SEC", 1.5)


@pytest.mark.parametrize("sec", [0.5, 1.4])
def test_short(sec):
    assert _end_silence_for(sec) == 0.7


@pytest.mark.parametrize("sec", [1.5, 1.6])
def test_normal(sec):
    assert _end_silence_for(sec) == 1.0
