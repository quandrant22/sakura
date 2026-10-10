import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import idle


def test_idle_seconds_returns_query_value():
    with patch.object(idle.sys, "platform", "win32"), \
         patch.object(idle, "_query", return_value=12.5):
        assert idle.idle_seconds() == 12.5


def test_idle_seconds_failure_returns_big_number():
    def boom():
        raise OSError("nope")
    with patch.object(idle.sys, "platform", "win32"), \
         patch.object(idle, "_query", side_effect=boom):
        assert idle.idle_seconds() >= 10 ** 9


def test_idle_seconds_non_windows_big_number():
    with patch.object(idle.sys, "platform", "linux"):
        assert idle.idle_seconds() >= 10 ** 9


def test_idle_seconds_real_call_is_number():
    v = idle.idle_seconds()
    assert isinstance(v, float) and v >= 0
