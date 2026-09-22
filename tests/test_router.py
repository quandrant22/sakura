"""Тесты роутера и сессии v3 (этап 2).

Run: python -m pytest tests/test_router.py -q

Критерии этапа: реестр разрешает без обращения к LLM (мок-счётчик), wake-слово
срезается до реестра, context разводит «перемотай вперёд», активное pending
перехватывает «да» до реестра и LLM, все 70 действий покрыты триггером.
"""

import asyncio

import pytest

from sakura_core.registry import build_index, load
from sakura_core.router import Decision, Router
from sakura_core.session import Session


@pytest.fixture(scope="module")
def registry():
    return load()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)




@pytest.fixture()
def make_router(registry):
    def _make(llm=None):
        calls: list = []
        base = llm if llm is not None else (lambda text, catalog: None)

        async def classifier(text, catalog):
            calls.append(text)  # счётчик оборачивает любой классификатор
            result = base(text, catalog)
            if hasattr(result, "__await__"):
                return await result
            return result

        router = Router(declarations=registry, llm_classify=classifier)
        return router, calls

    return _make


# ── порядок разрешения: LLM последний ─────────────────────────────────────


def test_registry_exact_no_llm(make_router):
    router, calls = make_router()
    d = _run(router.route("следующий трек", "playing:music"))
    assert d.action == "music.next"
    assert d.source == "registry_exact"
    assert calls == []  # LLM не вызван ни разу


def test_wake_word_stripped_no_llm(make_router):
    router, calls = make_router()
    d = _run(router.route("сакура следующий трек", "playing:music"))
    assert d.action == "music.next"
    # после среза wake-слова фраза стала точным совпадением
    assert d.source == "registry_exact"
    assert calls == []


def test_wake_word_with_punctuation(make_router):
    router, _ = make_router()
    d = _run(router.route("Сакура, стоп"))
    assert d.action == "music.play_pause"


def test_context_disambiguates_seek(make_router):
    router, _ = make_router()
    assert _run(router.route("перемотай вперёд", {"playing": "music"})).action == "music.seek_forward"
    assert _run(router.route("перемотай вперёд", {"window": "youtube"})).action == "youtube.forward"
    # без контекста — не разрешается ни в music.seek_forward, ни в youtube.forward
    assert _run(router.route("перемотай вперёд")).action is None


def test_exact_beats_fuzzy(make_router):
    router, _ = make_router()
    d = _run(router.route("НЕ НАРВИТСЯ ТРЕК" if False else "не нравится трек"))
    assert d.action == "music.dislike"
    assert d.source == "registry_exact"


# ── сессия: pending перехватывает короткий ответ ──────────────────────────


def test_pending_yes_goes_to_session_not_registry_llm(make_router):
    router, calls = make_router()
    router.session.expect("confirm", action="vps.status")
    d = _run(router.route("да"))
    assert d.source == "session"
    assert d.verdict == "confirm"
    assert d.action == "vps.status"
    assert calls == []  # ни в реестр, ни в LLM


def test_pending_deny(make_router):
    router, _ = make_router()
    router.session.expect("confirm", action="vps.status")
    d = _run(router.route("нет, не надо"))
    assert d.source == "session"
    assert d.verdict == "deny"
    assert d.action is None


def test_pending_expired_falls_through(make_router):
    router, calls = make_router()
    router.session.expect("confirm", action="vps.status", ttl=-1.0)
    d = _run(router.route("да", "playing:music"))
    # «да» не матчит триггеров → разговор через LLM-стаб
    assert d.action is None
    assert d.source == "conversation"
    assert calls == ["да"]


def test_pending_unrelated_phrase_cancels_confirmation(make_router):
    router, _ = make_router()
    router.session.expect("confirm", action="vps.status", ttl=60.0)
    decision = _run(router.route("какая погода"))
    assert decision.source == "session"
    assert decision.verdict == "deny"
    assert router.session.pending is None


def test_confirmation_priority_of_denial():
    from sakura_core.session import check_confirmation
    assert check_confirmation("да") == "confirm"
    assert check_confirmation("не подтверждаю") == "deny"
    assert check_confirmation("нет, давай") == "deny"  # отрицание приоритетно
    assert check_confirmation("какая погода") is None


# ── LLM-шаг: последний и валидируемый ─────────────────────────────────────


def test_llm_used_last_and_validated(make_router):
    router, calls = make_router(llm=lambda text, catalog: "music.next")
    d = _run(router.route("расскажи что-нибудь про космос", "playing:music"))
    assert d.source == "llm"
    assert d.action == "music.next"
    assert len(calls) == 1


def test_llm_unknown_action_is_conversation(make_router):
    router, calls = make_router(llm=lambda text, catalog: "no.such.action")
    d = _run(router.route("болтаем о разном"))
    assert d.source == "conversation"
    assert d.action is None


def test_llm_receives_catalog_with_all_ids(make_router):
    seen = {}

    def llm(text, catalog):
        seen["catalog"] = catalog
        return None

    router, _ = make_router(llm=llm)
    _run(router.route("болтаем"))
    for d in load():
        assert d.id in seen["catalog"]


# ── покрытие: каждое из 70 действий достигается триггером ─────────────────


def test_all_70_actions_covered_by_triggers(registry):
    router = Router(declarations=registry, llm_classify=None)
    # app.switch_open (param.resolve: installed_apps) матчится только при
    # наличии списка приложений агента — для покрытия ставим его на время.
    from sakura_core.registry import set_installed_apps
    set_installed_apps({"Discord": "C:/Discord/Discord.exe"})
    try:
        missed = []
        for decl in registry:
            hit = None
            for trigger in decl.triggers:
                decision = _run(router.route(trigger, decl.context))
                if decision.source.startswith("registry"):
                    # action == decl.id (normal) или None (clarify — param needed)
                    if decision.action == decl.id or decision.source == "registry_clarify":
                        hit = (trigger, decision.source)
                        break
            if hit is None:
                missed.append((decl.id, decl.triggers))
        assert not missed, f"действия без быстрого пути: {missed}"
    finally:
        set_installed_apps(None)


# ── required: ask — clarify flow ────────────────────────────────────────


def test_ask_without_param_returns_clarify():
    """required: ask, param отсутствует → pending_kind=clarify, action=None."""
    from sakura_core.registry import Declaration, Param, TriggerIndex

    decl = Declaration(
        id="test.ask", desc="Тест", executor="agent",
        reversible=True, confirm=False,
        triggers=["найди файл"],
        param=Param(name="query", pattern=r"файл\s+(.+)", required="ask"),
    )
    router = Router(declarations=[decl])
    d = _run(router.route("найди файл"))
    assert d.action is None
    assert d.source == "registry_clarify"
    assert d.pending_kind == "clarify"
    assert d.reply is not None
    assert router.session.pending is not None
    assert router.session.pending.kind == "clarify"
    assert router.session.pending.action == "test.ask"


def test_ask_with_param_executes_normally():
    """required: ask, param присутствует → обычное исполнение."""
    from sakura_core.registry import Declaration, Param, TriggerIndex

    decl = Declaration(
        id="test.ask", desc="Тест", executor="agent",
        reversible=True, confirm=False,
        triggers=["найди файл"],
        param=Param(name="query", pattern=r"файл\s+(.+)", required="ask"),
    )
    router = Router(declarations=[decl])
    d = _run(router.route("найди файл README.md"))
    assert d.action == "test.ask"
    assert d.param == "README.md"
    assert d.pending_kind is None


def test_clarify_response_resolves_to_action():
    """Ответ на clarify → session разрешается → action исполняется с param."""
    from sakura_core.registry import Declaration, Param

    decl = Declaration(
        id="test.ask", desc="Тест", executor="agent",
        reversible=True, confirm=False,
        triggers=["найди файл"],
        param=Param(name="query", pattern=r"файл\s+(.+)", required="ask"),
    )
    router = Router(declarations=[decl])
    # Шаг 1: clarify
    d1 = _run(router.route("найди файл"))
    assert d1.pending_kind == "clarify"
    # Шаг 2: ответ
    d2 = _run(router.route("main.py"))
    assert d2.action == "test.ask"
    assert d2.source == "session"
    assert d2.param == "main.py"
    assert d2.pending_kind == "clarify"


def test_llm_classification_does_not_block_event_loop():
    async def classify(text, catalog):
        await asyncio.sleep(0.02)
        return None

    async def probe():
        router = Router(declarations=[], llm_classify=classify)
        route_task = asyncio.create_task(router.route("разговор"))
        other_task = asyncio.create_task(asyncio.sleep(0.005, result=True))
        assert await other_task
        assert not route_task.done()
        decision = await route_task
        assert decision.source == "conversation"

    _run(probe())
