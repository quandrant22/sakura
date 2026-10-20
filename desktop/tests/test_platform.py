"""Платформенный слой: реализации совпадают с интерфейсом, заглушки честно отказывают."""
import inspect
import pathlib
import re
from unittest.mock import patch

import pytest

from desktop.core import platform as plat
from desktop.core.platform import base, linux, macos, windows

IMPLS = [windows.WindowsPlatform, linux.LinuxPlatform, macos.MacosPlatform]


@pytest.mark.parametrize("cls", IMPLS)
def test_impl_covers_interface(cls):
    assert not inspect.isabstract(cls)
    for m in base.interface_methods():
        assert callable(getattr(cls, m))
        sig_impl = inspect.signature(getattr(cls, m))
        sig_base = inspect.signature(getattr(base.Platform, m))
        # заглушки принимают *args; настоящие методы обязаны совпасть по параметрам
        varargs = any(p.kind is p.VAR_POSITIONAL for p in sig_impl.parameters.values())
        if not varargs:
            assert list(sig_impl.parameters) == list(sig_base.parameters), m


@pytest.mark.parametrize("cls", [linux.LinuxPlatform, macos.MacosPlatform])
def test_stubs_raise(cls):
    p = cls()
    for m in base.interface_methods():
        with pytest.raises(NotImplementedError):
            getattr(p, m)()


def test_get_platform_returns_platform():
    assert isinstance(plat.get_platform(), base.Platform)


def test_windows_idle_failure_returns_big_number():
    with patch.object(windows.sys, "platform", "win32"), \
         patch.object(windows, "_query_idle", side_effect=OSError):
        assert windows.WindowsPlatform().idle_seconds() >= 10 ** 9


def test_no_windll_outside_platform():
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for f in (root / "core").rglob("*.py"):
        if "platform" in f.relative_to(root / "core").parts[:1]:
            continue
        if re.search(r"\bwindll\b|\bwinreg\b", f.read_text(encoding="utf-8")):
            bad.append(str(f))
    assert bad == []


@pytest.mark.parametrize("action,flag", [("shutdown", "/s"), ("restart", "/r")])
def test_windows_shutdown_restart_now_t0(action, flag):
    # Подставной исполнитель: Popen не запускает ничего настоящего. По умолчанию — сразу (/t 0).
    from desktop.core import config
    assert config.SHUTDOWN_DELAY_S == 0
    with patch.object(windows.subprocess, "Popen") as popen:
        windows.WindowsPlatform().power(action)
    args = popen.call_args[0][0]
    assert args[:2] == ["shutdown", flag]
    assert args[args.index("/t") + 1] == "0"


def test_windows_shutdown_delay_from_setting(monkeypatch):
    from desktop.core import config
    monkeypatch.setattr(config, "SHUTDOWN_DELAY_S", 30)
    with patch.object(windows.subprocess, "Popen") as popen:
        windows.WindowsPlatform().power("shutdown")
    args = popen.call_args[0][0]
    assert args[args.index("/t") + 1] == "30"


def test_windows_shutdown_cancel():
    with patch.object(windows.subprocess, "Popen") as popen:
        windows.WindowsPlatform().power("shutdown_cancel")
    assert popen.call_args[0][0] == ["shutdown", "/a"]


def test_windows_sleep_via_api_not_rundll32():
    calls = []
    fake = type("W", (), {"powrprof": type("P", (), {"SetSuspendState": staticmethod(lambda *a: calls.append(a))})()})()
    with patch.object(windows.ctypes, "windll", fake, create=True), patch.object(windows.subprocess, "Popen") as popen:
        windows.WindowsPlatform().power("sleep")
    assert calls == [(False, True, False)]   # bHibernate=False — сон, а не гибернация
    popen.assert_not_called()


def test_windows_power_unknown_raises():
    with pytest.raises(ValueError):
        windows.WindowsPlatform().power("explode")


def test_hands_system_restart_now_supported():
    from desktop.core import hands
    with patch.object(windows.subprocess, "Popen") as popen:
        assert hands.execute_command("system:restart") == {"result": "перезагружаю"}
    assert "/r" in popen.call_args[0][0]


def test_windows_media_key_maps_to_vk():
    p = windows.WindowsPlatform()
    with patch.object(p, "press_virtual_key", return_value=True) as press:
        p.media_key("next")
    press.assert_called_once_with(0xB0)
    with pytest.raises(ValueError):
        p.media_key("nope")
