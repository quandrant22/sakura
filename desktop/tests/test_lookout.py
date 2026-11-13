"""Тесты для desktop.core.lookout"""

import time
import pytest
from desktop.core.lookout import LookoutEngine


def test_lookout_add_list_remove():
    alerts = []
    engine = LookoutEngine(on_alert=lambda msg: alerts.append(msg), poll_interval=0.1)

    id1 = engine.add_watch("100% завершено")
    id2 = engine.add_watch("босс повержен", repeat=True)

    lst = engine.list_watches()
    assert len(lst) == 2
    assert lst[0]["text"] == "100% завершено"
    assert lst[1]["repeat"] is True

    removed = engine.remove_watch("100%")
    assert len(removed) == 1
    assert engine.list_watches()[0]["id"] == id2

    engine.stop()


def test_lookout_matching():
    alerts = []
    current_screen = "Downloading game... 45%"

    engine = LookoutEngine(
        capture_func=lambda: current_screen,
        on_alert=lambda msg: alerts.append(msg),
        poll_interval=0.05,
    )

    engine.add_watch("100%")
    time.sleep(0.1)
    assert len(alerts) == 0

    # Screen updates to 100%
    current_screen = "Downloading game... 100% complete!"
    time.sleep(0.15)

    assert len(alerts) == 1
    assert "100%" in alerts[0]
    # One-shot should have been removed
    assert len(engine.list_watches()) == 0

    engine.stop()
