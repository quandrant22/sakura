"""tests/test_ws_token_required.py — без WS_TOKEN агент не подключается,
если устройство не спарено; спаренному токен не нужен (вход по ключу Noise)."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core import agent as agent_module
from core import transport

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_secure_store import FakeSecureStore


class _Stop(BaseException):
    """Не Exception: цикл агента ловит Exception и переподключается."""


@pytest.mark.parametrize("token", ["", "   "])
def test_empty_token_no_connect_and_error(monkeypatch, caplog, token):
    monkeypatch.setattr(agent_module.config, "WS_TOKEN", token)
    monkeypatch.setattr(agent_module.config, "AGENT_SECURE", "prefer")
    monkeypatch.setattr(transport, "_default_store", lambda: FakeSecureStore())
    connect = MagicMock(side_effect=AssertionError("не должен подключаться"))
    monkeypatch.setattr(transport, "open_connection", connect)
    spawn = MagicMock()
    monkeypatch.setattr(agent_module, "spawn", spawn)

    async def wait_for_keys(*a, **k):
        raise _Stop          # агент ждёт спаривания, а не подключается по токену

    monkeypatch.setattr(transport, "wait_for_keys", wait_for_keys)

    a = agent_module.Agent.__new__(agent_module.Agent)
    a.hearing = MagicMock()
    a.bus = MagicMock()

    with caplog.at_level("ERROR", logger="sakura.agent"), pytest.raises(_Stop):
        asyncio.run(a.run())

    connect.assert_not_called()
    spawn.assert_not_called()
    a.hearing.start.assert_not_called()
    assert "WS_TOKEN не задан в .env" in caplog.text
    # оверлей получает причину и подсказку про спаривание из трея (ТЗ-4)
    a.bus.emit.assert_called_once_with(
        "agent_alert", text="Не задан WS_TOKEN (.env) — агент не подключается; "
                            "можно спарить: трей → «Спарить с сервером…»")


def _run_until_connect(monkeypatch, tmp_path, store, mode):
    """run() до первой попытки подключения; вернуть (режим, ошибка токена?)."""
    from core import presence
    monkeypatch.setattr(agent_module.config, "WS_TOKEN", "")
    monkeypatch.setattr(agent_module.config, "AGENT_SECURE", mode)
    monkeypatch.setattr(transport, "_default_store", lambda: store)
    monkeypatch.setattr(agent_module, "spawn", lambda coro, name=None: coro.close())
    monkeypatch.setattr(agent_module, "_EXTENSION_SERVER", str(tmp_path / "missing.py"))
    monkeypatch.setattr(agent_module, "init_index", lambda: None)
    monkeypatch.setattr(presence, "prime_system_info", lambda: None)
    seen = []

    async def open_connection(url, m):
        seen.append(m)
        raise _Stop

    monkeypatch.setattr(transport, "open_connection", open_connection)
    a = agent_module.Agent.__new__(agent_module.Agent)
    a.hearing, a.bus = MagicMock(), MagicMock()
    with pytest.raises(_Stop):
        asyncio.run(a.run())
    return seen, a


def test_paired_device_connects_without_token(monkeypatch, tmp_path):
    store = FakeSecureStore.paired("laptop", b"\x01" * 32, b"\x02" * 32, b"\x03" * 32)
    seen, a = _run_until_connect(monkeypatch, tmp_path, store, "prefer")
    assert seen == ["prefer"]
    assert all(c.args[0] != "agent_alert" for c in a.bus.emit.call_args_list)


def test_required_without_keys_needs_no_token(monkeypatch, tmp_path):
    seen, _ = _run_until_connect(monkeypatch, tmp_path, FakeSecureStore(), "required")
    assert seen == ["required"]      # дальше transport скажет NotPaired


def test_agent_has_no_token_literals():
    """Токен добавляет только Conn.send_json (и только на старом ws)."""
    src = (Path(__file__).resolve().parents[1] / "core" / "agent.py").read_text(encoding="utf-8")
    assert '"token"' not in src
    assert ".send(json.dumps" not in src


def test_send_json_token_only_on_ws():
    class WS:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            self.sent.append(json.loads(text))

    ws, ch = WS(), WS()
    plain = transport.Conn(ws, transport="ws", token="t")
    noise = transport.Conn(object(), transport="noise", channel=ch)
    asyncio.run(plain.send_json({"type": "ping"}))
    asyncio.run(noise.send_json({"type": "ping", "token": "t"}))
    assert ws.sent == [{"type": "ping", "token": "t"}]
    assert ch.sent == [{"type": "ping"}]
    assert (plain.secure, noise.secure) == (False, True)


def test_config_has_no_default_token(monkeypatch):
    """В config.py нет значения токена по умолчанию (только из .env)."""
    import dotenv
    monkeypatch.delenv("WS_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_SECURE", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)  # без .env
    spec = importlib.util.spec_from_file_location(
        "_config_no_env", Path(__file__).resolve().parents[1] / "config.py")
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    assert cfg.WS_TOKEN == ""
    assert cfg.AGENT_SECURE == "prefer"


@pytest.mark.parametrize("raw, mode", [("off", "off"), ("REQUIRED", "required"),
                                       ("что-то", "prefer"), ("", "prefer")])
def test_agent_secure_mode_parsing(monkeypatch, raw, mode):
    import dotenv
    monkeypatch.setenv("AGENT_SECURE", raw)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    spec = importlib.util.spec_from_file_location(
        "_config_mode", Path(__file__).resolve().parents[1] / "config.py")
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    assert cfg.AGENT_SECURE == mode
