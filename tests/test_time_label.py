"""Метка времени около полуночи: модель не путает 23:58 с «часом ночи»."""

from datetime import datetime

import pytest

import modules.context as ctx


@pytest.mark.parametrize("hour,minute,label", [
    (23, 39, "поздний вечер"),
    (23, 40, "почти полночь"),
    (23, 58, "почти полночь"),
    (23, 59, "почти полночь"),
    (0, 0, "сразу после полуночи"),
    (0, 20, "сразу после полуночи"),
    (0, 21, "поздний вечер"),
    (1, 5, "поздний вечер"),
    (3, 0, "ночь"),
    (12, 0, "день"),
])
def test_time_of_day_near_midnight(hour, minute, label):
    assert ctx.get_time_of_day(hour, minute) == label


def test_time_of_day_hour_only_unchanged():
    """Вызов без минут (minute=0) вне окна полуночи — прежние метки."""
    assert ctx.get_time_of_day(23) == "поздний вечер"
    assert ctx.get_time_of_day(1) == "поздний вечер"
    assert ctx.get_time_of_day(12) == "день"


def _freeze(monkeypatch, tmp_path, when):
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ctx, "datetime", _Fixed)
    monkeypatch.setattr(ctx, "get_devices_snapshot", lambda: {})
    monkeypatch.setattr(ctx, "get_health_snapshot", lambda: {})
    monkeypatch.setattr(ctx, "get_sakura_mood", lambda: {})
    monkeypatch.setattr(ctx, "get_last_proactive", lambda: {})
    monkeypatch.setattr(ctx, "get_silence_minutes", lambda: 0)


def test_now_line_almost_midnight(monkeypatch, tmp_path):
    _freeze(monkeypatch, tmp_path, datetime(2026, 10, 8, 23, 58))   # чт
    first = ctx.build_context_block().splitlines()[0]
    assert first == "СЕЙЧАС: 23:58 (почти полночь), чт"


def test_now_line_after_midnight(monkeypatch, tmp_path):
    _freeze(monkeypatch, tmp_path, datetime(2026, 10, 9, 0, 7))     # пт
    first = ctx.build_context_block().splitlines()[0]
    assert first == "СЕЙЧАС: 00:07 (сразу после полуночи), пт"
