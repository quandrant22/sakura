import sys
import threading
from types import SimpleNamespace

import pytest

from core.exception_hooks import install_exception_hooks
from core.hearing import Hearing


def test_threading_exception_hook_logs_traceback(caplog):
    original_thread_hook = threading.excepthook
    original_sys_hook = sys.excepthook
    try:
        install_exception_hooks(__import__("logging").getLogger("test.exception_hooks"))
        try:
            raise ValueError("background thread failed")
        except ValueError as exc:
            args = threading.ExceptHookArgs(
                (type(exc), exc, exc.__traceback__, SimpleNamespace(name="hearing-test"))
            )

        with caplog.at_level("CRITICAL", logger="test.exception_hooks"):
            threading.excepthook(args)

        assert "Uncaught exception in thread hearing-test" in caplog.text
        assert "ValueError: background thread failed" in caplog.text
    finally:
        threading.excepthook = original_thread_hook
        sys.excepthook = original_sys_hook


def test_hearing_exit_logs_and_emits_bus_event(caplog):
    events = []
    hearing = Hearing.__new__(Hearing)
    hearing.agent = SimpleNamespace(
        bus=SimpleNamespace(emit=lambda event, **data: events.append((event, data)))
    )
    hearing._run = lambda: None

    with caplog.at_level("ERROR", logger="sakura.hearing"):
        hearing.run()

    assert "[hearing] поток слуха остановлен" in caplog.text
    assert events == [("hearing_stopped", {})]


def test_hearing_exit_is_logged_when_worker_raises(caplog):
    hearing = Hearing.__new__(Hearing)
    hearing.agent = SimpleNamespace(bus=SimpleNamespace(emit=lambda *_args, **_kwargs: None))

    def fail_worker():
        raise RuntimeError("capture loop failed")

    hearing._run = fail_worker
    with caplog.at_level("ERROR", logger="sakura.hearing"):
        with pytest.raises(RuntimeError, match="capture loop failed"):
            hearing.run()

    assert "[hearing] поток слуха остановлен" in caplog.text