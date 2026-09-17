"""VPS dispatch preserves arguments at the actual voice_info boundary."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from sakura_core.bridge import _load_capabilities
from sakura_core.executor import ExecutionContext, get_handler
from sakura_core.router import Router


@pytest.mark.parametrize("phrase, action, arg", [
    ("какие ачивки вчера", "steam:achievements", "вчера"),
    ("достижения в Remnant за месяц", "steam:achievements:game", "remnant"),
    ("добавь задачу купить хлеб", "task:add", "купить хлеб"),
    ("выполнил задачу 5", "task:done", "5"),
    ("забудь про старый ник", "memory:forget", "старый ник"),
])
def test_vps_handler_passes_arguments(monkeypatch, phrase, action, arg):
    _load_capabilities()
    decision = Router().route(phrase)
    answer = AsyncMock(return_value=("Ответ", True))
    monkeypatch.setattr("modules.voice_info.handle", answer)
    result = asyncio.get_event_loop().run_until_complete(
        get_handler(decision.action)(ExecutionContext(
            param=decision.param, extra={"text": phrase})))
    assert result == ("Ответ", True)
    answer.assert_awaited_once_with(action, arg, phrase)
