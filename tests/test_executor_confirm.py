"""Тесты confirm-обработки в executor (этап 5, фикс данных confirm: true).

Run: python -m pytest tests/test_executor_confirm.py -q

Необратимое действие не исполняется молча: executor выставляет ожидание
подтверждения и возвращает вопрос; решение из диалога подтверждения
(confirmed=True) исполняется без повторного вопроса.
"""

import asyncio
import logging

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


def test_confirm_action_asks_instead_of_executing(caplog):
    ex, session, calls = _make_executor(True, "test.erase.ask")
    caplog.set_level(logging.INFO, logger="sakura.executor")
    result = _run(ex.execute("test.erase.ask", _ctx()))
    assert result == ("Стереть данные?", True)
    assert "[confirm] ожидание: action=test.erase.ask device=tg timeout=60с" in caplog.text
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


def test_coding_confirm_executes_only_after_router_accepts_yes(monkeypatch, caplog):
    import capabilities.coding as cap
    import sakura_core.bridge as bridge
    from sakura_core.registry import load
    from sakura_core.router import Router

    declarations = load()
    caplog.set_level(logging.INFO, logger="sakura.bridge")
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
        assert f"[v3] ожидает подтверждения: {action_id} ({requested.source})" in caplog.text
        assert len(calls) == call_count

        confirmed = await router.route("да")
        assert confirmed.action == action_id
        assert confirmed.source == "session"
        handled, result = await bridge.execute_decision(
            confirmed, device_ws=None, device_id="tg",
            register_command=None, text=text)
        assert handled is True
        assert result == ("изменение выполнено", True)
        assert f"[v3] исполнено: {action_id} (session)" in caplog.text

    async def _scenario():
        await _exercise("coding.create_module", "создай модуль тестовый")
        assert len(calls) == 1
        await _exercise("coding.fix", "исправь баг в коде тестовый")
        assert len(calls) == 2

    _run(_scenario())


def test_confirm_accepted_logs_phrase(monkeypatch, caplog):
    import sakura_core.bridge as bridge
    from sakura_core.router import Router

    router = Router(declarations=[], llm_classify=None)
    router.session.expect("confirm", action="system.shutdown", device="pc")
    monkeypatch.setattr(bridge, "_router", router)
    executed = []

    async def on_execute(action):
        executed.append(action)

    async def on_cancel():
        raise AssertionError("accepted confirmation must not cancel")

    caplog.set_level(logging.INFO, logger="sakura.bridge")
    handled = _run(bridge.handle_v3_confirm(
        "да", on_execute=on_execute, on_cancel=on_cancel))

    assert handled is True
    assert executed == ["system.shutdown"]
    assert "[confirm] принято: action=system.shutdown фраза='да'" in caplog.text


def test_confirm_declined_logs_phrase(monkeypatch, caplog):
    import sakura_core.bridge as bridge
    from sakura_core.router import Router

    router = Router(declarations=[], llm_classify=None)
    router.session.expect("confirm", action="system.shutdown", device="pc")
    monkeypatch.setattr(bridge, "_router", router)
    cancelled = []

    async def on_execute(action):
        raise AssertionError("declined confirmation must not execute")

    async def on_cancel():
        cancelled.append(True)

    caplog.set_level(logging.INFO, logger="sakura.bridge")
    handled = _run(bridge.handle_v3_confirm(
        "ну не знаю", on_execute=on_execute, on_cancel=on_cancel))

    assert handled is True
    assert cancelled == [True]
    assert "[confirm] отклонено: action=system.shutdown фраза='ну не знаю'" in caplog.text


def test_confirm_expiration_logs_action(caplog):
    session = Session()
    pending = session.expect("confirm", action="system.shutdown", device="pc")
    pending.until = 1.0

    caplog.set_level(logging.INFO, logger="sakura.session")
    assert session.pending is None
    assert "[confirm] истекло: action=system.shutdown" in caplog.text