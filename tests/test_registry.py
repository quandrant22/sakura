"""Тесты реестра способностей v3 (этап 1).

Run: python -m pytest tests/test_registry.py -q

Покрывают: загрузку (87 деклараций), валидацию (негативные тесты — каждый
случай бросает RegistryError), контракт матчинга (границы слов, самый длинный
триггер, context, param.resolve: installed_apps) и каталог для LLM.
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
    "followup": "ack",
}


def _decl(**over):
    raw = dict(BASE)
    raw.update(over)
    return declaration_from_dict(raw)


@pytest.fixture(scope="module")
def registry():
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    return load()


@pytest.fixture(scope="module")
def index(registry):
    return build_index(registry)


# --- загрузка и валидация -------------------------------------------------


def test_load_returns_87_declarations(registry):
    assert len(registry) == 87


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


def test_missing_followup_raises():
    raw = dict(BASE)
    del raw["followup"]
    with pytest.raises(RegistryError):
        declaration_from_dict(raw)


def test_unknown_followup_raises():
    with pytest.raises(RegistryError):
        validate([_decl(followup="shout")])


def test_followup_index_maps_wire_names():
    from sakura_core.registry import followup_for
    decls = [_decl(id="music.next", legacy=["music:next", "music_next"],
                   triggers=["t1"], followup="ack"),
             _decl(id="music.now_playing",
                   legacy=["music:now_playing", "music_info"],
                   triggers=["t2"], followup="llm")]
    assert followup_for("music.next", decls) == "ack"
    assert followup_for("music_next", decls) == "ack"
    assert followup_for("music:now_playing", decls) == "llm"
    assert followup_for("music_info", decls) == "llm"
    assert followup_for("unknown_action_xyz", decls) == "ack"
    assert followup_for("", decls) == "ack"


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

# Список «намеренно без хендлера» живёт в бою, а не только в pytest:
# sakura_core/registry.py:KNOWN_UNREACHABLE, и его же проверяет load()
# (require_handlers=True) на старте бота. Тест читает тот же объект, чтобы
# список не разошёлся между тестами и стартом.
from sakura_core.registry import KNOWN_UNREACHABLE, unreachable  # noqa: E402


def test_unreachable_ids_are_exactly_the_known_ones():
    """Каждый id реестра либо исполняется, либо явно перечислен в KNOWN_UNREACHABLE.

    Находка этапа 6: 13 id были недостижимы молча — capabilities.
    calendar/coding/files/kettle не импортировались в _load_capabilities(),
    мост возвращал (False, None), и управление уходило в старый путь.
    Этап 7 развязал последние восемь (kettle подключили раньше): coding.*
    переехал на executor=vps с серверной реализацией, calendar.list — так же,
    files.open свёлся к существующему verb'у агента open_file. Поэтому
    KNOWN_UNREACHABLE пуст, а новый id без хендлера упадёт и этим тестом,
    и стартом (registry.load).

    Проверка идёт в отдельном интерпретаторе: в общем процессе pytest
    таблицы доменов регистрируют и сами тесты (test_music_domain.py
    импортирует capabilities.*), из-за чего достижимость в процессе завышена
    и ничего не доказывает.

    Отдельно сверяется, что количество хендлеров совпало с декларациями.
    """
    import json
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import json, sakura_core.bridge;"
        "from sakura_core.executor import get_handler, registered;"
        "from sakura_core.registry import load;"
        "decls = load();"
        "print(json.dumps({"
        "'decls': len(decls),"
        "'handlers': len(registered()),"
        "'missing': sorted(d.id for d in decls if get_handler(d.id) is None),"
        "}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=root,
        env={**os.environ, "PYTHONPATH": root},
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["handlers"] == data["decls"], (
        f"таблицы доменов загружены не полностью: хендлеров "
        f"{data['handlers']} из {data['decls']} деклараций — проверка "
        f"достижимости вхолостую"
    )
    missing = set(data["missing"])
    assert missing == set(KNOWN_UNREACHABLE), (
        f"достижимость реестра изменилась.\n"
        f"  стало недостижимо: {sorted(missing - set(KNOWN_UNREACHABLE))}\n"
        f"  стало достижимо:   {sorted(set(KNOWN_UNREACHABLE) - missing)}"
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

    from sakura_core import bridge
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


def test_app_switch_routes_with_app_param(index):
    """«переключись на дискорд» → app.switch, param='дискорд'."""
    result = index.match("переключись на дискорд")
    assert result is not None
    assert result[1].id == "app.switch"
    assert result[2] == "дискорд"


def test_app_switch_bare_verb_needs_clarify(index):
    """Голый «открой» → app.switch_open с needs_clarify (required: ask)."""
    from sakura_core.registry import set_installed_apps
    set_installed_apps({"Discord": "C:/Discord.exe"})
    try:
        result = index.match("открой")
        assert result is not None
        assert result[1].id == "app.switch_open"
        assert result[3] is True
    finally:
        set_installed_apps(None)


def test_app_switch_longer_trigger_wins(index):
    """«открой яндекс музыку» → open.app, а не app.switch по «открой»."""
    result = index.match("открой яндекс музыку")
    assert result is not None
    assert result[1].id == "open.app"


def test_app_switch_handler_bakes_app_into_wire():
    """app.switch подставляет param в провод (формат агента)."""
    import asyncio
    import json as _json

    from sakura_core import bridge
    from sakura_core.router import Decision

    class _FakeWS:
        sent = None

        async def send(self, payload):
            self.sent = payload

    ws = _FakeWS()
    decision = Decision("app.switch", "registry_fuzzy", param="дискорд")
    executed, _ = asyncio.get_event_loop().run_until_complete(
        bridge.execute_decision(
            decision, device_ws=ws, device_id="laptop",
            register_command=None, text="переключись на дискорд"))
    assert executed is True
    payload = _json.loads(ws.sent)
    assert payload["action"] == "switch_to_app"
    assert payload["arg"] == "дискорд"


# ─ param.resolve: installed_apps — «открой/покажи» только для приложений ────
# Однословные «открой/покажи» (app.switch_open) матчатся, только если параметр
# оказался в списке установленных приложений агента; иначе декларация
# пропускается и фраза уходит дальше по роутеру (LLM), как до app.switch.


_APP_SWITCH_IDS = ("app.switch", "app.switch_open")

_APPS = {"Discord": "C:/Discord/Discord.exe", "Steam": "C:/Steam/steam.exe"}
_ALIASES = {"дискорд": "Discord.exe", "стим": "Steam.exe"}  # apps_mapping keys


@pytest.fixture()
def installed_apps():
    """Ставит список приложений на время теста, снимает после (изоляция)."""
    from sakura_core.registry import set_installed_apps

    def _set(apps, extra=None):
        set_installed_apps(apps, extra=extra)

    yield _set
    set_installed_apps(None)


def test_param_resolve_rejects_unknown_source():
    """validate() отвергает недопустимое значение resolve."""
    with pytest.raises(RegistryError):
        _decl(param={"name": "app", "pattern": "(.+)x",
                     "resolve": "weather_api"})


def test_param_resolve_accepted_and_wired(registry):
    """app.switch_open несёт resolve: installed_apps; app.switch — нет."""
    by_id = {d.id: d for d in registry}
    assert by_id["app.switch_open"].param.resolve == "installed_apps"
    assert by_id["app.switch"].param.resolve is None
    # однозначные глаголы остались в app.switch без фильтра
    assert set(by_id["app.switch"].triggers) == {
        "переключись на", "перейди в", "разверни"}
    assert set(by_id["app.switch_open"].triggers) == {"открой", "покажи"}


def test_resolve_matches_installed_app(index, installed_apps):
    """«открой дискорд» (алиас из маппинга) → app.switch_open, 'дискорд'."""
    installed_apps(_APPS, extra=_ALIASES)
    result = index.match("открой дискорд")
    assert result is not None
    assert result[1].id == "app.switch_open"
    assert result[2] == "дискорд"


def test_resolve_matches_latin_name_case_insensitive(index, installed_apps):
    """Сравнение без учёта регистра: 'открой discord' по имени 'Discord'."""
    installed_apps(_APPS)
    result = index.match("открой discord")
    assert result is not None
    assert result[1].id == "app.switch_open"
    assert result[2] == "discord"


def test_resolve_skips_non_app(index, installed_apps):
    """«открой ютуб» — ютуба нет в списке → декларация не матчится."""
    installed_apps(_APPS, extra=_ALIASES)
    assert index.match("открой ютуб") is None


def test_resolve_muted_without_agent_list(index, installed_apps):
    """Агент не подключён (списка нет) — «открой/покажи» не матчатся вовсе."""
    installed_apps(None)
    assert index.match("открой дискорд") is None
    assert index.match("открой") is None


def test_resolve_muted_with_empty_list(index, installed_apps):
    """Пустой список от агента — тот же эффект: триггер молчит."""
    installed_apps({})
    assert index.match("открой дискорд") is None


def test_unambiguous_verbs_ignore_resolve(index, installed_apps):
    """«переключись на» — без resolve: матчится даже без списка приложений."""
    installed_apps(None)
    result = index.match("переключись на что угодно")
    assert result is not None
    assert result[1].id == "app.switch"
    assert result[2] == "что угодно"


def test_router_does_not_hijack_non_apps(installed_apps):
    """Однословные «открой/покажи» больше не перехватывают не-приложения."""
    import sakura_core.bridge  # noqa: F401  (регистрация хендлеров для load())
    from sakura_core.router import Router
    installed_apps(_APPS, extra=_ALIASES)
    router = Router()
    for phrase in ("покажи погоду", "открой ютуб", "открой github.com",
                   "открой сайт хабр", "покажи ачивки", "покажи задачи"):
        d = router.route(phrase)
        assert d.action not in _APP_SWITCH_IDS, (phrase, d.action)


def test_router_installed_app_routes_to_switch_family(installed_apps):
    """Установленное приложение → семейство app.switch при любом глаголе."""
    import sakura_core.bridge  # noqa: F401  (регистрация хендлеров для load())
    from sakura_core.router import Router
    installed_apps(_APPS, extra=_ALIASES)
    router = Router()
    d = router.route("открой дискорд")
    assert d.action == "app.switch_open" and d.param == "дискорд"
    d = router.route("покажи стим")
    assert d.action == "app.switch_open" and d.param == "стим"
    d = router.route("переключись на что угодно")
    assert d.action == "app.switch" and d.param == "что угодно"


def test_switch_open_handler_bakes_app_into_wire():
    """app.switch_open ведёт на тот же провод switch_to_app:<имя>."""
    from capabilities.system import SYSTEM_COMMANDS
    from sakura_core.executor import ExecutionContext

    cmd = SYSTEM_COMMANDS["app.switch_open"](ExecutionContext(param="стим"))
    assert cmd.action == "switch_to_app"
    assert cmd.arg == "стим"
# ─ развязка этапа 7: восемь id получили исполнение ─────────────────────────


def test_coding_and_calendar_are_executor_vps(registry):
    """coding.* и calendar.list серверные: MiMo и Google Calendar живут на VPS."""
    by_id = {d.id: d for d in registry}
    for aid in ("coding.create_module", "coding.fix", "coding.read_file",
                "coding.commit", "coding.build", "coding.git_status",
                "calendar.list"):
        assert by_id[aid].executor == "vps", aid
    # файлы — наоборот, только у устройства: индекс файлов и запуск в агенте
    assert by_id["files.open"].executor == "agent"


def test_load_refuses_declaration_without_handler():
    """Декларация без хендлера — отказ на старте, а не «не исполнено» в бою.

    Дыра этапа 6 жила именно так: id попадал в каталог LLM (классификатор
    мог вернуть coding.fix), а исполнять его было нечем — мост молча
    возвращал (False, None) и управление уходило в старый путь. Проверка
    живёт в load(), поэтому падает старт бота, а не отчёт после разбора.
    """
    import sakura_core.bridge  # noqa: F401  (таблицы доменов загружены)

    gap = _decl(id="test.gap_without_handler", triggers=["тестовая фраза"])
    with pytest.raises(RegistryError) as err:
        validate([gap], require_handlers=True)
    assert "test.gap_without_handler" in str(err.value)
    assert "KNOWN_UNREACHABLE" in str(err.value)
    # без require_handlers синтетические декларации не проверяются
    validate([gap])
    assert unreachable([gap]) == {"test.gap_without_handler"}


def test_known_unreachable_is_the_escape_hatch(monkeypatch):
    """Явно перечисленный id не роняет старт: исключение должно быть видимым."""
    import sakura_core.bridge  # noqa: F401
    import sakura_core.registry as reg

    monkeypatch.setattr(reg, "KNOWN_UNREACHABLE", frozenset({"test.allowed_gap"}))
    validate([_decl(id="test.allowed_gap", triggers=["тестовая фраза"])],
             require_handlers=True)  # не бросает


def test_calendar_trigger_backs_the_new_phrase(index):
    """«покажи ближайшие события» — естественная фраза, ведёт в calendar.list."""
    result = index.match("покажи ближайшие события")
    assert result is not None
    assert result[1].id == "calendar.list"


def test_coding_and_files_phrases_route_to_their_ids(index):
    """Фразы развязанных доменов доходят до своих id, а не в старый путь."""
    cases = {
        "найди файл отчёт": ("files.open", "отчёт"),
        "открой файл README.md": ("files.open", "README.md"),
        "создай модуль погоды": ("coding.create_module", "погоды"),
        "исправь баг в чайнике": ("coding.fix", "в чайнике"),
        "прочитай файл main.py": ("coding.read_file", "main.py"),
        "закоммить правки": ("coding.commit", "правки"),
        "собери апк": ("coding.build", None),
        "git status": ("coding.git_status", None),
        "покажи ближайшие события": ("calendar.list", None),
    }
    for phrase, (aid, param) in cases.items():
        result = index.match(phrase)
        assert result is not None, phrase
        assert result[1].id == aid, (phrase, result[1].id)
        assert result[2] == param, (phrase, result[2])
