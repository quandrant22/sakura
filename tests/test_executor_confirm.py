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
    return asyncio.run(coro)


def test_confirm_action_asks_instead_of_executing():
    ex, session, calls = _make_executor(True, "test.erase.ask")
    result = _run(ex.execute("test.erase.ask", _ctx()))
    assert result == ("Стереть данные?", True)
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


def test_coding_confirm_executes_only_after_router_accepts_yes(monkeypatch):
    import capabilities.coding as cap
    import sakura_core.bridge as bridge
    from sakura_core.registry import load
    from sakura_core.router import Router

    declarations = load()
    calls = []

    async def _fake_mimo(prompt):
        calls.append(prompt)
        return {"ok": True, "output": "изменение выполнено", "error": ""}

    monkeypatch.setattr(cap, "mimo_fix", _fake_mimo)
    by_id = {decl.id: decl for decl in declarations}

    async def _exercise(action_id, text):
        call_count = len(calls)
        router = Router(declarations=declarations, llm_classify=None)
        executor = Executor(session=router.session, declarations=declarations)
        monkeypatch.setattr(bridge, "_router", router)
        monkeypatch.setattr(bridge, "_executor", executor)

        requested = await router.route(text)
        assert requested.action == action_id
        handled, result = await bridge.execute_decision(
            requested, device_ws=None, device_id="tg",
            register_command=None, text=text)
        assert handled is True
        assert result[0] == by_id[action_id].confirm_prompt
        assert len(calls) == call_count

        confirmed = await router.route("да")
        assert confirmed.action == action_id
        assert confirmed.source == "session"
        handled, result = await bridge.execute_decision(
            confirmed, device_ws=None, device_id="tg",
            register_command=None, text=text)
        assert handled is True
        assert result == ("изменение выполнено", True)

    async def _scenario():
        await _exercise("coding.create_module", "создай модуль тестовый")
        assert len(calls) == 1
        await _exercise("coding.fix", "исправь баг в коде тестовый")
        assert len(calls) == 2

    _run(_scenario())