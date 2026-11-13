"""Тесты для desktop.core.watch_along"""

import pytest
from desktop.core.watch_along import WatchAlongManager


def test_watch_along_lifecycle():
    comments = []
    manager = WatchAlongManager(on_comment=lambda c: comments.append(c), min_comment_gap=0.05)

    manager.start("Cyberpunk Edgerunners")
    assert manager.active is True
    assert len(comments) == 1

    manager.feed_speech("David: I'm not running away!")
    manager.feed_speech("Lucy: You idiot...")

    context = manager.memory.get_summary_context()
    assert "David" in context
    assert "Lucy" in context

    import time
    time.sleep(0.06)

    # Test comment generation
    c = manager.maybe_comment(prompt_generator=lambda ctx: "Люси права, Дэвид вечно лезет на рожон.")
    assert c is not None
    assert "Люси права" in c
    assert len(comments) == 2

    manager.stop()
    assert manager.active is False
