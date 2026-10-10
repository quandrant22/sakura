"""Тесты, перенесённые из agent/tests: изоляция кэшей приложений, индекса файлов и ключа чайника."""
import pytest

from desktop.core import hands as _hands
from desktop.core import kettle as _kettle


@pytest.fixture(autouse=True)
def isolate_agent_state(monkeypatch, tmp_path):
    monkeypatch.setattr(_hands, "_APPS_CACHE_FILE", str(tmp_path / "apps_cache.json"))
    monkeypatch.setattr(_hands, "_app_cache", {})
    monkeypatch.setattr(_hands.file_index, "_cache_path", str(tmp_path / "file_index.json"))
    monkeypatch.setattr(_hands.file_index, "_entries", [])
    monkeypatch.setattr(_hands.file_index, "_built_at", 0.0)
    monkeypatch.setattr(_kettle, "KEY_FILE", str(tmp_path / "memory" / "kettle_key.json"))
