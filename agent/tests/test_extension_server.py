"""Тесты extension-сервера: backoff-цикл и фолбэк порта.

Run: cd agent && python -m pytest tests/test_extension_server.py -q

Боевой инцидент: VS Code держал 8766; start() глотал ошибку привязки и
возвращался нормально, _run_ext_server держал паузу только в ветке except —
цикл перезапускался мгновенно (строка лога каждые ~10 мс), сжигая ядро CPU.
"""

import asyncio
import importlib.util
import json
import socket
import sys
import time
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]


def load_ext_server():
    """Загружает core/extension_server.py standalone (как agent.run)."""
    sys.path.insert(0, str(AGENT_DIR))
    spec = importlib.util.spec_from_file_location(
        "extension_server_under_test", AGENT_DIR / "core" / "extension_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StopLoop(Exception):
    """Сигнал остановки бесконечного цикла из fake-sleep."""


def test_load_builtin_commands_parses_string_without_tempfile(monkeypatch):
    import core.commands as commands

    class DummyToml:
        calls = []

        @staticmethod
        def loads(payload):
            DummyToml.calls.append(payload)
            return {"commands": []}

    monkeypatch.setattr(commands, "toml", DummyToml)
    registry = commands.CommandRegistry()

    commands.load_builtin_commands(registry)

    assert DummyToml.calls == [commands.BUILTIN_COMMANDS]
    assert registry._commands == []


def test_backoff_pauses_between_failed_binds():
    """Падение при привязке → пауза 5с до следующей попытки.

    Раньше пауза стояла только в ветке except, а start() возвращался
    нормально — попытки шли каждые ~10 мс. Контракт: между попытками
    минимум 5с, дальше нарастание 10/30.
    """
    mod = load_ext_server()
    attempts = []
    sleeps = []

    async def failing_start():
        attempts.append(len(attempts))
        raise RuntimeError("[Errno 13] error while attempting to bind: 10013")

    def fake_sleep(sec):
        sleeps.append(sec)
        if len(sleeps) >= 3:
            raise _StopLoop

    with pytest.raises(_StopLoop):
        mod.run_forever(start=failing_start, sleep=fake_sleep)

    assert sleeps == [5, 10, 30], sleeps
    assert len(attempts) == 3  # по одной попытке на паузу — без мгновенных
    assert all(d >= 5 for d in sleeps)  # за 5с — не больше одной попытки


def test_backoff_resets_after_stable_run():
    """Проработал дольше минуты — счётчик сброшен, пауза снова 5с."""
    mod = load_ext_server()
    clock = {"t": 0.0}
    sleeps = []

    async def dying_start():
        clock["t"] += mod.RESTART_STABLE_SEC + 1  # прожил минуту и упал

    def fake_sleep(sec):
        sleeps.append(sec)
        if len(sleeps) >= 2:
            raise _StopLoop

    real_monotonic = time.monotonic
    time.monotonic = lambda: clock["t"]
    try:
        with pytest.raises(_StopLoop):
            mod.run_forever(start=dying_start, sleep=fake_sleep)
    finally:
        time.monotonic = real_monotonic

    assert sleeps == [5, 5], sleeps  # без сброса было бы [60, 60]


def test_start_binds_next_port_when_first_busy(caplog, monkeypatch):
    """Порт из config.EXTENSION_PORTS может быть занят, следующий свободный — используется."""
    mod = load_ext_server()

    free_ports = []
    for _ in range(2):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        free_ports.append(s.getsockname()[1])
        s.close()

    first_port = free_ports[0]
    second_port = free_ports[1]
    monkeypatch.setattr(mod, "EXTENSION_PORT", None)
    monkeypatch.setattr(
        sys.modules.get("config"),
        "EXTENSION_PORTS",
        (first_port, second_port),
        raising=False,
    )

    blocker = socket.socket()
    blocker.bind(("127.0.0.1", first_port))
    blocker.listen(1)

    try:
        async def scenario():
            task = asyncio.create_task(mod.start())
            await asyncio.sleep(1.5)
            assert mod.EXTENSION_PORT == second_port, mod.EXTENSION_PORT
            import websockets
            async with websockets.connect(
                    f"ws://127.0.0.1:{second_port}", open_timeout=3,
                    origin="chrome-extension://test-extension") as ws:
                hello = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert hello["type"] == "sakura_hello"
                assert "version" in hello
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with caplog.at_level("INFO", logger="sakura.extension"):
            asyncio.run(scenario())

        text = caplog.text
        assert f"ws://127.0.0.1:{second_port}" in text
        assert str(first_port) in text and "недоступен" in text.lower()
    finally:
        blocker.close()


@pytest.mark.parametrize("origin", [None, "", "https://attacker.example"])
def test_handler_rejects_missing_or_foreign_origin(monkeypatch, origin):
    from types import SimpleNamespace

    mod = load_ext_server()
    monkeypatch.delenv("SAKURA_EXTENSION_ID", raising=False)

    class FakeWebSocket:
        request = SimpleNamespace(headers={"Origin": origin} if origin is not None else {})
        closed = None
        sent = False

        async def close(self, code, reason):
            self.closed = (code, reason)

        async def send(self, _payload):
            self.sent = True

    websocket = FakeWebSocket()
    asyncio.run(mod._handler(websocket))

    assert websocket.closed == (1008, "Origin not allowed")
    assert websocket.sent is False
    assert mod.is_connected() is False


def test_handler_requires_configured_extension_id(monkeypatch):
    from types import SimpleNamespace

    mod = load_ext_server()
    monkeypatch.setenv("SAKURA_EXTENSION_ID", "trusted-id")

    class FakeWebSocket:
        request = SimpleNamespace(headers={"Origin": "chrome-extension://other-id"})
        closed = None

        async def close(self, code, reason):
            self.closed = (code, reason)

    websocket = FakeWebSocket()
    asyncio.run(mod._handler(websocket))

    assert websocket.closed == (1008, "Origin not allowed")