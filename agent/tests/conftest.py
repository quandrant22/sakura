import importlib.util
import os
import sys
from pathlib import Path

import pytest


AGENT_ROOT = Path(__file__).resolve().parents[1]
_agent_root_str = str(AGENT_ROOT)
_added_agent_root = _agent_root_str not in sys.path
if _added_agent_root:
    sys.path.insert(0, _agent_root_str)

# Токен в репозитории не хранится (config: WS_TOKEN только из .env) —
# тестам хватает заглушки.
os.environ.setdefault("WS_TOKEN", "test-token")

_config_spec = importlib.util.spec_from_file_location(
    "sakura_agent_test_config", AGENT_ROOT / "config.py",
)
_agent_config = importlib.util.module_from_spec(_config_spec)
_config_spec.loader.exec_module(_agent_config)
_root_config = sys.modules.get("config")
sys.modules["config"] = _agent_config
try:
    from core import hands as _hands
    from core import kettle as _kettle
finally:
    if _root_config is None:
        del sys.modules["config"]
    else:
        sys.modules["config"] = _root_config
    if _added_agent_root:
        sys.path.remove(_agent_root_str)


@pytest.fixture(autouse=True)
def use_agent_configuration(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(_agent_root_str)
    monkeypatch.setitem(sys.modules, "config", _agent_config)
    monkeypatch.setattr(_hands, "_APPS_CACHE_FILE", str(tmp_path / "apps_cache.json"))
    monkeypatch.setattr(_hands, "_app_cache", {})
    monkeypatch.setattr(_hands.file_index, "_cache_path", str(tmp_path / "file_index.json"))
    monkeypatch.setattr(_hands.file_index, "_entries", [])
    monkeypatch.setattr(_hands.file_index, "_built_at", 0.0)
    monkeypatch.setattr(_kettle, "KEY_FILE", str(tmp_path / "memory" / "kettle_key.json"))