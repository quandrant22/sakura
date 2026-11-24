"""Тесты сбора GPU-телеметрии на ПК (gpu_stats, presence, eyes, platform guard)."""
from unittest.mock import patch

from desktop.core import eyes, gpu_stats, presence


def test_gpu_stats_returns_valid_shape_and_values():
    gpu_stats._cache_until = 0.0
    data = gpu_stats.get_gpu_stats(use_cache=False)
    assert isinstance(data, dict)
    if data.get("gpu") is not None:
        assert 0 <= data["gpu"] <= 100
    if data.get("vram") is not None:
        assert 0 <= data["vram"] <= 100


def test_presence_and_eyes_include_gpu_metrics():
    fake = {"gpu": 47, "gpu_temp": 58.0, "vram": 41.2, "gpu_name": "NVIDIA GeForce RTX 4060"}
    with patch("desktop.core.gpu_stats.get_gpu_stats", return_value=fake):
        ext = presence._collect_system_info()
        basic = eyes.get_system_info()
    assert ext["gpu"] == 47
    assert ext["gpu_temp"] == 58.0
    assert ext["vram"] == 41.2
    assert ext["gpu_name"] == "NVIDIA GeForce RTX 4060"
    assert basic["gpu"] == 47
    assert basic["gpu_temp"] == 58.0
