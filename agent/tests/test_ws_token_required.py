"""tests/test_ws_token_required.py — без WS_TOKEN агент не подключается."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import agent as agent_module


@pytest.mark.parametrize("token", ["", "   "])
def test_empty_token_no_connect_and_error(monkeypatch, caplog, token):
    monkeypatch.setattr(agent_module.config, "WS_TOKEN", token)
    connect = MagicMock(side_effect=AssertionError("не должен подключаться"))
    monkeypatch.setattr(agent_module.websockets, "connect", connect)
    spawn = MagicMock()
    monkeypatch.setattr(agent_module, "spawn", spawn)

    a = agent_module.Agent.__new__(agent_module.Agent)
    a.hearing = MagicMock()
    a.bus = MagicMock()

    with caplog.at_level("ERROR", logger="sakura.agent"):
        asyncio.run(a.run())

    connect.assert_not_called()
    spawn.assert_not_called()
    a.hearing.start.assert_not_called()
    assert "WS_TOKEN не задан в .env" in caplog.text


def test_config_has_no_default_token(monkeypatch):
    """В config.py нет значения токена по умолчанию (только из .env)."""
    import dotenv
    monkeypatch.delenv("WS_TOKEN", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)  # без .env
    spec = importlib.util.spec_from_file_location(
        "_config_no_env", Path(__file__).resolve().parents[1] / "config.py")
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    assert cfg.WS_TOKEN == ""
