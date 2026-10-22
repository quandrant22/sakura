"""Порт agent/tests/test_idle.py: простой пользователя теперь в platform.windows."""
from unittest.mock import patch

from desktop.core.platform import windows


def _idle():
    return windows.WindowsPlatform().idle_seconds()


def test_idle_seconds_returns_query_value():
    with patch.object(windows.sys, "platform", "win32"), \
         patch.object(windows, "_query_idle", return_value=12.5):
        assert _idle() == 12.5


def test_idle_seconds_failure_returns_big_number():
    with patch.object(windows.sys, "platform", "win32"), \
         patch.object(windows, "_query_idle", side_effect=OSError("nope")):
        assert _idle() >= 10 ** 9


def test_idle_seconds_non_windows_big_number():
    with patch.object(windows.sys, "platform", "linux"):
        assert _idle() >= 10 ** 9


def test_idle_seconds_real_call_is_number():
    v = _idle()
    assert isinstance(v, float) and v >= 0
