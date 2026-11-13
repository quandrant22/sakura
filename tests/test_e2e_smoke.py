"""Сквозной smoke: старт приложения и путь фразы через мост/роутер.

Без сети: LLM подменён на уровне sakura_core.llm.generate, исполнение —
на уровне bridge.execute_decision. Проверяются стыки модулей, а не домены:
  реестр ↔ исполнитель, llm.classify ↔ router ↔ bridge, acks ↔ ws_protocol,
  сборка системного промпта при недоступных подмодулях.
"""

import asyncio
import inspect

import pytest

import modules.acks as acks
import sakura_core.bridge as br
import sakura_core.llm as llm
from sakura_core import registry
from sakura_core.executor import get_handler


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pipeline(monkeypatch):
    """Боевой роутер моста с подменённым LLM; исполнение перехвачено."""
    answers = {"raw": "null"}
    llm_calls: list[str] = []

    async def fake_generate(contents, **kw):
        llm_calls.append(contents)
        return answers["raw"]

    executed: list = []

    async def fake_execute(decision, **kw):
        executed.append(decision)
        if not decision.action:
            return False, None
        return True, "cmd-1"

    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(br, "_router", None)
    monkeypatch.setattr(br, "_executor", None)
    monkeypatch.setattr(br, "execute_decision", fake_execute)
    return answers, llm_calls, executed


def _fast_path(text, **kw):
    return _run(br.v3_fast_path(
        text, data={}, device_ws=None, device_id="laptop",
        register_command=lambda *a, **k: None, **kw))


# ── инициализация ───────────────────────────────────────────────────────


def test_registry_loads_and_every_declaration_has_handler():
    decls = registry.load()
    assert decls, "реестр пуст"
    registry.validate(decls, require_handlers=True)
    missing = [d.id for d in br._declarations if get_handler(d.id) is None]
    assert not missing, f"декларации без хендлера: {missing}"
    catalog = registry.build_llm_catalog(br._declarations)
    for d in br._declarations:
        if d.param is not None:
            assert f"- {d.id} (param: {d.param.name})" in catalog


def test_router_and_executor_build(pipeline):
    router = br.get_router()
    assert br.get_executor()._session is router.session


def test_build_system_survives_broken_submodules(monkeypatch):
    """Память, граф, контекст, календарь падают — промпт всё равно собирается."""
    import memory.db as db
    import modules.calendar_module as cal
    import modules.context as context
    import modules.graph as graph
    import sakura_core.prompt as prompt

    def boom(*a, **k):
        raise RuntimeError("подмодуль недоступен")

    for mod, name in ((db, "get_memory_context"), (db, "get_self_context"),
                      (db, "get_identity_model"), (graph, "get_graph_context"),
                      (context, "get_full_context"), (context, "build_context_block"),
                      (cal, "get_upcoming_events")):
        monkeypatch.setattr(mod, name, boom)
    monkeypatch.setattr(prompt, "_build_system_cache", {}, raising=False)

    system = _run(prompt._build_system(include_calendar=True, query="что у меня завтра"))
    assert isinstance(system, str) and len(system) > 200


# ── путь фразы ──────────────────────────────────────────────────────────


def test_conversation_phrase_goes_to_chat(pipeline):
    answers, llm_calls, executed = pipeline
    assert _fast_path("мне сегодня приснился странный сон про море") is False
    assert llm_calls, "классификатор должен был быть спрошен"
    assert all(d.action is None for d in executed)


def test_exact_registry_command_skips_llm(pipeline):
    answers, llm_calls, executed = pipeline
    on_command = []

    async def _on_command():
        on_command.append(True)

    assert _fast_path("следующий трек", on_command=_on_command) is True
    assert llm_calls == []
    (d,) = executed
    assert d.action == "music.next" and d.source.startswith("registry")
    assert on_command == [True], "prefetch должен сниматься до исполнения"


def test_indirect_command_with_param_via_llm(pipeline):
    answers, llm_calls, executed = pipeline
    answers["raw"] = "kettle.heat | 85"
    agent_cmds = []

    async def _on_agent(decision, cmd_id):
        agent_cmds.append((decision.action, cmd_id))

    assert _fast_path("сделай водичку градусов восемьдесят пять",
                      on_agent_command=_on_agent) is True
    assert len(llm_calls) == 1
    (d,) = executed
    assert (d.action, d.source, d.param) == ("kettle.heat", "llm", "85")
    assert agent_cmds == [("kettle.heat", "cmd-1")]


def test_llm_unknown_id_is_conversation(pipeline):
    answers, llm_calls, executed = pipeline
    answers["raw"] = "no.such_action | 1"
    assert _fast_path("сделай что-нибудь невообразимое прямо сейчас") is False


def test_informational_reply_is_delivered_when_stylize_fails(pipeline, monkeypatch):
    """LLM-стилизация вернула мусор/упала — Мастер слышит исходный текст."""
    async def fake_execute(decision, **kw):
        return True, ("Сейчас +5, облачно.", True)
    monkeypatch.setattr(br, "execute_decision", fake_execute)

    async def broken_generate(contents, **kw):
        return object()          # не строка
    monkeypatch.setattr(llm, "generate", broken_generate)

    spoken = []

    async def speak(text, listen=None):
        spoken.append(text)

    assert _fast_path("какая погода", speak=speak) is True
    assert spoken == ["Сейчас +5, облачно."]


# ── подтверждения ───────────────────────────────────────────────────────


def test_acks_contract_used_by_ws_protocol_and_adapters():
    for name in ("choose", "arm", "on_result", "is_armed", "closes_turn",
                 "error_phrase", "status_phrase", "detail_is_error",
                 "fixed_phrases", "category_for"):
        assert callable(getattr(acks, name)), name
    assert inspect.iscoroutinefunction(acks.on_result)
    assert acks.RESULT_STATUSES
    assert set(acks.CATEGORY.values()) | {"default", "music", "open_app"} <= set(acks.PHRASES)

    assert "70" in "".join(acks.choose("system.volume", "smoke", "70") for _ in range(40))
    for action, param in (("music.next", None), ("open.app", "Steam"),
                          ("music.volume_up", "10"), ("browser.back", None)):
        for _ in range(30):
            phrase = acks.choose(action, "smoke", param)
            assert phrase and "{" not in phrase, (action, phrase)
    assert all("{" not in p for p in acks.fixed_phrases())
    assert acks.error_phrase("плеер не отвечает") == "Не получилось: плеер не отвечает."
