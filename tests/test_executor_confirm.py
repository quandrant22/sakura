"""Тесты confirm-обработки в executor (этап 5, фикс данных confirm: true).

Run: python -m pytest tests/test_executor_confirm.py -q

Необратимое действие не исполняется молча: executor выставляет ожидание
подтверждения и возвращает вопрос; решение из диалога подтверждения
(confirmed=True) исполняется без повторного вопроса.
"""

import asyncio

from sakura_core.executor import ExecutionContext, Executor, register_table
from sakura_core.registry import Declaration
from sakura_core.session import Session


def _decl(confirm: bool, action_id: str) -> Declaration:
    return Declaration(
        id=action_id, desc="Стереть данные", executor="vps",
        reversible=False, confirm=confirm, triggers=("сотри данные",),
    )


def _make_executor(confirm: bool, action_id: str):
    # свой id на тест: _HANDLERS глобален и живёт между тестами,
    # повторная регистрация одного id бросает RuntimeError
    session = Session()
    calls = []
    register_table(
        {action_id: lambda ctx: calls.append(ctx) or ("стёрла", True)})
    return Executor(session=session, declarations=[_decl(confirm, action_id)]), \
        session, calls


def _ctx(confirmed: bool = False) -> ExecutionContext:
    return ExecutionContext(device_id="tg", extra={"confirmed": confirmed})


def _run(coro):
    """Паттерн репозитория: asyncio.run() снимает глобальный цикл и ломает
    легаси-тесты (см. tests/test_music_domain.py)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_confirm_action_asks_instead_of_executing():
    ex, session, calls = _make_executor(True, "test.erase.ask")
    result = _run(ex.execute("test.erase.ask", _ctx()))
    assert result == ("Стереть данные? Подтверди, пожалуйста.", True)
    assert calls == []  # хендлер не звался — исполнение остановлено
    assert session.pending is not None
    assert session.pending.action == "test.erase.ask"


def test_confirmed_executes_without_asking():
    ex, session, calls = _make_executor(True, "test.erase.confirmed")
    result = _run(ex.execute("test.erase.confirmed", _ctx(confirmed=True)))
    assert result == ("стёрла", True)
    assert len(calls) == 1
    assert session.pending is None


def test_non_confirm_action_executes_immediately():
    ex, session, calls = _make_executor(False, "test.erase.plain")
    result = _run(ex.execute("test.erase.plain", _ctx()))
    assert result == ("стёрла", True)
    assert len(calls) == 1
    assert session.pending is None