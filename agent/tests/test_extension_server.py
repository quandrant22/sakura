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


def test_start_binds_next_port_when_first_busy(caplog):
    """Занятый 8766 (VS Code) → сервер поднимается на 8767 и здоровается."""
    mod = load_ext_server()

    # Если 8766 ещё свободен — занимаем его сами (аналог VS Code).
    # В среде разработки он бывает занят постоянно — тоже годится.
    blocker = None
    try:
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 8766))
        blocker.listen(1)
    except OSError:
        if blocker is not None:
            blocker.close()
        blocker = None  # 8766 уже держит кто-то другой — тот же сценарий

    try:
        async def scenario():
            task = asyncio.create_task(mod.start())
            await asyncio.sleep(1.5)  # дать перебрать порты и привязаться
            assert mod.EXTENSION_PORT == 8767, mod.EXTENSION_PORT
            # Проверка рукопожатия: агент первым шлёт sakura_hello
            import websockets
            async with websockets.connect(
                    "ws://127.0.0.1:8767", open_timeout=3) as ws:
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
        assert "ws://127.0.0.1:8767" in text  # выбранный порт — в лог
        assert "8766" in text and "занят" in text.lower()  # причина понятна
    finally:
        if blocker is not None:
            blocker.close()