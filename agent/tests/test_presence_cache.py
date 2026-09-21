"""Sensor cache tests without Windows hardware or the agent import root."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call


def test_sensor_snapshot_cache_and_cpu_warmup(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "presence_under_test", Path(__file__).resolve().parents[1] / "core/presence.py")
    presence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(presence)
    clock = Mock(return_value=10.0)
    monkeypatch.setattr(presence, "time", SimpleNamespace(monotonic=clock))
    psutil = SimpleNamespace(
        cpu_percent=Mock(side_effect=[0.0, 42.0, 55.0]),
        virtual_memory=Mock(return_value=SimpleNamespace(percent=25)),
        sensors_battery=Mock(return_value=None),
        disk_usage=Mock(return_value=SimpleNamespace(free=10 * 1024 ** 3)),
        sensors_temperatures=Mock(return_value={}),
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", psutil)
    presence.prime_system_info()
    first = presence.get_extended_system_info()
    assert first["cpu"] == 42.0
    first["cpu"] = -1
    clock.return_value = 11.99
    assert presence.get_extended_system_info()["cpu"] == 42.0
    psutil.sensors_battery.assert_called_once()
    psutil.disk_usage.assert_called_once()
    clock.return_value = 12.0
    assert presence.get_extended_system_info()["cpu"] == 55.0
    assert psutil.sensors_battery.call_count == 2
    assert psutil.cpu_percent.call_args_list == [call(interval=None)] * 3
