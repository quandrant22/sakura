"""Тесты для desktop.core.care"""

import datetime
import pytest
from desktop.core.care import CareKind, CareManager


def test_care_manager_intervals():
    nudges = []
    manager = CareManager(on_care_nudge=lambda k, msg: nudges.append((k, msg)))

    # Уменьшим интервалы для теста
    manager.nudge_intervals[CareKind.WATER] = 10.0
    manager.last_nudge_time[CareKind.WATER] = 100.0

    # Проверка до истечения
    manager.check(now_time=105.0)
    assert len(nudges) == 0

    # Проверка после истечения
    trig = manager.check(now_time=111.0)
    assert CareKind.WATER in trig
    assert len(nudges) == 1
    assert "воды" in nudges[0][1]


def test_care_late_night():
    nudges = []
    manager = CareManager(on_care_nudge=lambda k, msg: nudges.append((k, msg)), bedtime_hour=1)
    manager.last_nudge_time[CareKind.LATE] = 0.0

    # Проверка в 02:30 ночи
    night_dt = datetime.datetime(2026, 11, 8, 2, 30)
    trig = manager.check(now_time=100000.0, current_dt=night_dt)

    assert CareKind.LATE in trig
    assert any("спать" in n[1] for n in nudges)
