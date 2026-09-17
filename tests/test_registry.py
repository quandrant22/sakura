"""Тесты реестра способностей v3 (этап 1).

Run: python -m pytest tests/test_registry.py -q

Покрывают: загрузку (67 деклараций), валидацию (негативные тесты — каждый
случай бросает RegistryError), контракт матчинга (границы слов, самый длинный
триггер, context) и каталог для LLM.
"""

import pytest

from sakura_core.registry import (
    RegistryError,
    build_index,
    build_llm_catalog,
    declaration_from_dict,
    load,
    validate,
)

BASE = {
    "id": "test.action",
    "desc": "тестовое действие",
    "executor": "vps",
    "reversible": True,
    "confirm": False,
    "triggers": ["тестовая фраза"],
}


def _decl(**over):
    raw = dict(BASE)
    raw.update(over)
    return declaration_from_dict(raw)


@pytest.fixture(scope="module")
def registry():
    return load()


@pytest.fixture(scope="module")
def index(registry):
    return build_index(registry)


# --- загрузка и валидация -------------------------------------------------


def test_load_returns_85_declarations(registry):
    assert len(registry) == 85


def test_validate_passes_on_real_registry(registry):
    validate(registry)  # не бросает


def test_duplicate_id_raises():
    with pytest.raises(RegistryError):
        validate([_decl(triggers=["фраза один"]), _decl(triggers=["фраза два"])])


def test_trigger_collision_without_context_raises():
    a = _decl(id="a.one", triggers=["общая фраза"])
    b = _decl(id="b.two", triggers=["общая фраза"])
    with pytest.raises(RegistryError):
        validate([a, b])


def test_trigger_collision_with_context_is_legal():
    a = _decl(id="a.one", triggers=["общая фраза"], context="playing:music")
    b = _decl(id="b.two", triggers=["общая фраза"], context="window:youtube")
    validate([a, b])  # не бросает: разводятся контекстом


def test_empty_triggers_raises():
    with pytest.raises(RegistryError):
        validate([_decl(triggers=[])])


def test_unknown_executor_raises():
    with pytest.raises(RegistryError):
        validate([_decl(executor="magic")])


def test_unknown_context_raises():
    with pytest.raises(RegistryError):
        validate([_decl(context="window:steam")])


# --- матчинг: границы слов, самый длинный триггер, context -----------------


def test_substring_inside_word_is_not_a_match(index):
    # 'лайк' не должен срабатывать внутри 'дизлайк'/'дизлайкни'/'мои лайки'
    assert index.match("дизлайк")[1].id == "music.dislike"  # свой триггер, не music.like
    assert index.match("дизлайкни")[1].id == "music.dislike"
    assert index.match("мои лайки")[1].id == "music.liked_tracks"  # не music.like


def test_longest_trigger_wins_dislike_vs_like(index):
    # 'нравится' ⊂ 'не нравится' ⊂ 'не нравится трек' — побеждает самый длинный
    assert index.match("не нравится трек")[1].id == "music.dislike"  # не like
    assert index.match("не нравится")[1].id == "music.dislike"
    assert index.match("нравится трек")[1].id == "music.like"


def test_longest_wins_cross_domain(index):
    # 'следующий' ⊂ 'следующий таб' — побеждает browser.tab_next, не music.next
    assert index.match("следующий таб")[1].id == "browser.tab_next"


def test_context_selects_declaration(index):
    # 'перемотай вперёд' делят music.seek_forward и youtube.forward
    assert index.match("перемотай вперёд", "playing:music")[1].id == "music.seek_forward"
    assert index.match("перемотай вперёд", "window:youtube")[1].id == "youtube.forward"
    assert index.match("перемотай вперёд") is None  # без контекста не разрешается


def test_context_free_trigger_matches_with_any_context(index):
    assert index.match("следующий трек", "playing:music")[1].id == "music.next"
    assert index.match("следующий трек", "window:youtube")[1].id == "music.next"


def test_no_match_for_unknown_phrase(index):
    assert index.match("расскажи как дела") is None


# --- каталог для LLM -------------------------------------------------------


def test_catalog_contains_all_ids(registry):
    catalog = build_llm_catalog(registry)
    for d in registry:
        assert d.id in catalog
    # каталог — строки '- id: desc'
    assert catalog.splitlines()[0].startswith("- ")


# --- param tie-breaking: при равной длине триггера побеждает param ----------


def test_kipiti_bare_goes_to_boil(index):
    """'кипяти' (без температуры) → kettle.boil, param=None."""
    result = index.match("кипяти")
    assert result is not None
    decl, param = result[1], result[2]
    assert decl.id == "kettle.boil"
    assert param is None


def test_kipiti_with_temp_goes_to_boil_heat(index):
    """'кипяти 70 градусов' → kettle.boil_heat, param='70'."""
    result = index.match("кипяти 70 градусов")
    assert result is not None
    decl, param = result[1], result[2]
    assert decl.id == "kettle.boil_heat"
    assert param == "70"


def test_vskipiti_bare_goes_to_boil(index):
    """'вскипяти' (без температуры) → kettle.boil, param=None."""
    result = index.match("вскипяти")
    assert result is not None
    decl, param = result[1], result[2]
    assert decl.id == "kettle.boil"
    assert param is None


def test_vskipiti_with_temp_goes_to_boil_heat(index):
    """'вскипяти 80 градусов' → kettle.boil_heat, param='80'."""
    result = index.match("вскипяти 80 градусов")
    assert result is not None
    decl, param = result[1], result[2]
    assert decl.id == "kettle.boil_heat"
    assert param == "80"


def test_param_tiebreaking_independent_of_yaml_order():
    """Перестановка деклараций в списке не меняет результат матчинга."""
    from sakura_core.registry import Declaration, Param, TriggerIndex

    decl_a = Declaration(
        id="a.with_param", desc="A", executor="vps",
        reversible=True, confirm=False,
        triggers=["общая фраза"],
        param=Param(name="x", pattern=r"(\d+)", required=True),
    )
    decl_b = Declaration(
        id="b.no_param", desc="B", executor="vps",
        reversible=True, confirm=False,
        triggers=["общая фраза"],
    )

    # Порядок 1: A первый
    idx1 = TriggerIndex([decl_a, decl_b])
    r1 = idx1.match("общая фраза 42")
    assert r1 is not None
    assert r1[1].id == "a.with_param"
    assert r1[2] == "42"

    # Порядок 2: B первый
    idx2 = TriggerIndex([decl_b, decl_a])
    r2 = idx2.match("общая фраза 42")
    assert r2 is not None
    assert r2[1].id == "a.with_param"
    assert r2[2] == "42"

    # Без числа — param не извлекается, побеждает тот, у кого нет required param
    r3 = idx1.match("общая фраза")
    assert r3 is not None
    assert r3[1].id == "b.no_param"  # param.required=True, extract=None → skip → B
    r4 = idx2.match("общая фраза")
    assert r4 is not None
    assert r4[1].id == "b.no_param"  # B идёт первый, A пропущена (required param missing)


def test_unresolvable_ambiguity_raises():
    """Два действия с одинаковым триггером, без context и без param — ошибка."""
    a = _decl(id="a.one", triggers=["конфликт"])
    b = _decl(id="b.two", triggers=["конфликт"])
    with pytest.raises(RegistryError, match="неразрешимая неоднозначность"):
        validate([a, b])


def test_shared_trigger_with_param_is_legal():
    """Два действия с одинаковым триггером, у одного param — допустимо."""
    a = _decl(id="a.with_param", triggers=["конфликт"],
              param={"name": "x", "pattern": r"(\d+)", "required": True})
    b = _decl(id="b.no_param", triggers=["конфликт"])
    validate([a, b])  # не бросает: param разрешает ничью на runtime


# ── required: ask ────────────────────────────────────────────────────────

def test_ask_returns_needs_clarify():
    """required: ask + param отсутствует → needs_clarify=True."""
    from sakura_core.registry import TriggerIndex
    d = _decl(id="a.ask", triggers=["найди файл"],
              param={"name": "query", "pattern": r"файл\s+(.+)", "required": "ask"})
    idx = TriggerIndex([d])
    r = idx.match("найди файл")
    assert r is not None
    assert r[1].id == "a.ask"
    assert r[2] is None  # param_value
    assert r[3] is True  # needs_clarify


def test_ask_with_param_extracts_normally():
    """required: ask + param присутствует → needs_clarify=False, param извлечён."""
    from sakura_core.registry import TriggerIndex
    d = _decl(id="a.ask", triggers=["найди файл"],
              param={"name": "query", "pattern": r"файл\s+(.+)", "required": "ask"})
    idx = TriggerIndex([d])
    r = idx.match("найди файл README.md")
    assert r is not None
    assert r[1].id == "a.ask"
    assert r[2] == "README.md"
    assert r[3] is False  # needs_clarify


def test_ask_vs_true_skip():
    """required: true без param → skip. required: ask без param → clarify."""
    from sakura_core.registry import TriggerIndex
    decl_true = _decl(id="a.true", triggers=["тест"],
                      param={"name": "x", "pattern": r"(\d+)", "required": "true"})
    decl_ask = _decl(id="a.ask", triggers=["тест"],
                     param={"name": "x", "pattern": r"(\d+)", "required": "ask"})
    # true → skip
    idx1 = TriggerIndex([decl_true])
    r1 = idx1.match("тест без числа")
    assert r1 is None  # required=true, param=None → пропуск
    # ask → clarify
    idx2 = TriggerIndex([decl_ask])
    r2 = idx2.match("тест без числа")
    assert r2 is not None
    assert r2[3] is True  # needs_clarify


# ─ достижимость: какие id реестра реально исполняются ────────────────────

# Домены, НАМЕРЕННО не подключённые в bridge._load_capabilities().
# Причина: их канонические id уходят агенту, а агент их не исполняет —
# agent._legacy_action не маппит coding./files./calendar., и в
# hands.execute_command нет таких verb. Кодинг реализован НА СЕРВЕРЕ
# (modules/coding.py, ветка modules/ws_handlers.py:311-355): подключив
# домен, мост перехватил бы рабочий путь реестром и сломал его.
# Развязка (перенос кодинга в реестр) — отдельная задача.
KNOWN_UNREACHABLE = {
    "calendar.list",
    "coding.build",
    "coding.commit",
    "coding.create_module",
    "coding.fix",
    "coding.git_status",
    "coding.read_file",
    "files.open",
}


def test_unreachable_ids_are_exactly_the_known_ones():
    """Каждый id реестра либо исполняется, либо явно перечислен ниже.

    Находка этапа 6: 13 id были недостижимы молча — capabilities.
    calendar/coding/files/kettle не импортировались в _load_capabilities(),
    мост возвращал (False, None) и управление уходило в старый путь.
    kettle подключён: его провод (kettle:boil, kettle:heat:60) совпадает с
    тем, что слал старый route_critical → execute_critical_action.
    Остальные 8 остаются перечисленными явно — молчаливое изменение
    достижимости (в любую сторону) упадёт этим тестом.

    Проверка идёт в отдельном интерпретаторе: в общем процессе pytest
    таблицы доменов регистрируют и сами тесты (test_music_domain.py
    импортирует capabilities.coding/files/calendar), из-за чего
    достижимость в процессе завышена и ничего не доказывает.
    """
    import json
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import json, sakura_core.bridge;"
        "from sakura_core.executor import get_handler;"
        "from sakura_core.registry import load;"
        "print(json.dumps(sorted(d.id for d in load()"
        " if get_handler(d.id) is None)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=root,
        env={**os.environ, "PYTHONPATH": root},
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    missing = set(json.loads(proc.stdout.strip().splitlines()[-1]))
    assert missing == KNOWN_UNREACHABLE, (
        f"достижимость реестра изменилась.\n"
        f"  стало недостижимо: {sorted(missing - KNOWN_UNREACHABLE)}\n"
        f"  стало достижимо:   {sorted(KNOWN_UNREACHABLE - missing)}"
    )


def test_kettle_domain_is_wired():
    """kettle.* исполняется реестром, а не старым route_critical."""
    import sakura_core.bridge  # noqa: F401
    from sakura_core.executor import get_handler
    for aid in ("kettle.boil", "kettle.off", "kettle.status",
                "kettle.heat", "kettle.boil_heat"):
        assert get_handler(aid) is not None, aid


def test_execute_decision_forwards_param():
    """Decision.param доезжает до хендлера, а не теряется в мосту.

    Регрессия (этап 6): execute_decision вызывал execute() без param, из-за
    чего kettle.heat/boil_heat (param: temp) падали ValueError в хендлере.
    """
    import asyncio

    import sakura_core.bridge as bridge
    from sakura_core.executor import AgentCommand, register_table
    from sakura_core.router import Decision

    seen = {}

    def _param_echo(ctx):
        seen["param"] = ctx.param
        return AgentCommand(f"test.param_echo:{ctx.param}")

    register_table({"test.param_echo": _param_echo})

    class _FakeWS:
        sent = None

        async def send(self, payload):
            self.sent = payload

    ws = _FakeWS()
    decision = Decision("test.param_echo", "registry_exact", param="42")
    # get_event_loop().run_until_complete — как в остальных тестах: asyncio.run()
    # закрыл бы общий loop и сломал легаси-хелперы других файлов (3.12).
    executed, _ = asyncio.get_event_loop().run_until_complete(
        bridge.execute_decision(
            decision, device_ws=ws, device_id="laptop",
            register_command=None, text="тест"))

    assert executed is True
    assert seen["param"] == "42"
    assert "test.param_echo:42" in (ws.sent or "")


def test_kettle_heat_bakes_temp_into_action():
    """kettle.heat подставляет param в action на проводе (формат агента)."""
    from capabilities.kettle import KETTLE_COMMANDS
    from sakura_core.executor import ExecutionContext

    cmd = KETTLE_COMMANDS["kettle.heat"](ExecutionContext(param="60"))
    assert cmd.action == "kettle:heat:60"
