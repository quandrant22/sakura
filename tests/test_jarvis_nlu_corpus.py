"""Золотой корпус NLU (этап 3): составные команды, ложные триггеры, вежливые
и косвенные просьбы, параметры времени и места, гибрид «команда + разговор».

Три слоя:
  1. локальный разбор роутера без LLM (быстрый путь);
  2. структурированный LLM-разбор и откат на локальный при сбое;
  3. исполнение плана и гибрида в мосте (v3_fast_path).

Без сети: LLM и исполнение подменены.
"""

import asyncio
import time

import pytest

import config
import sakura_core.bridge as br
import sakura_core.llm as llm
from sakura_core import action_note, registry
from sakura_core.nlu import IntentParse, LlmUnavailable, find_delay, split_units
from sakura_core.router import Decision, Router


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def installed_apps():
    """«Открой браузер» разрешается только при известном списке приложений."""
    registry.set_installed_apps(["браузер", "хром", "steam", "блокнот"])
    yield
    registry.set_installed_apps([])


@pytest.fixture
def make_router():
    def _make(parse=None, classify=None):
        calls: list = []

        async def _parse(text, catalog, context=None):
            calls.append((text, context))
            result = parse(text, catalog, context)
            if isinstance(result, Exception):
                raise result
            return result

        async def _classify(text, catalog):
            calls.append((text, None))
            return classify(text, catalog)

        router = Router(declarations=br._declarations,
                        llm_parse=_parse if parse is not None else None,
                        llm_classify=_classify if classify is not None else None)
        return router, calls
    return _make


def route(router, text, context=None, **kw):
    return _run(router.route(text, context, **kw))


# ══ 1. локальный разбор (без LLM) ═══════════════════════════════════════


# ── составные команды ──────────────────────────────────────────────────

@pytest.mark.parametrize("phrase,context,expected", [
    ("включи музыку и сделай погромче", None,
     [("open.app", None), ("music.volume_up", None)]),
    ("громкость на 30 и следующий трек", "playing:music",
     [("system.volume", "30"), ("music.next", None)]),
    ("поставь на паузу и скажи какая погода", "playing:music",
     [("music.play_pause", None), ("weather.now", None)]),
    ("поставь чайник, включи музыку и сделай погромче", None,
     [("kettle.boil", None), ("open.app", None), ("music.volume_up", None)]),
    ("следующий трек, а потом сделай потише", "playing:music",
     [("music.next", None), ("music.volume_down", None)]),
    ("поставь чайник затем включи музыку", None,
     [("kettle.boil", None), ("open.app", None)]),
])
def test_multi_command_plan_without_llm(make_router, phrase, context, expected):
    router, calls = make_router(parse=lambda *a: pytest.fail("LLM не нужен"))
    d = route(router, phrase, context)
    assert [(s.action, s.param) for s in d.steps] == expected
    assert d.kind == "plan" and d.source == "registry_plan"
    assert d.action == expected[0][0] and d.param == expected[0][1], "обратная совместимость"
    assert d.actions == tuple(a for a, _ in expected)
    assert d.chat_tail is None and calls == []


def test_open_browser_and_youtube_is_a_two_step_plan(make_router):
    """«открой браузер и включи ютуб»: обе части — действия, без LLM."""
    router, calls = make_router(parse=lambda *a: pytest.fail("LLM не нужен"))
    d = route(router, "открой браузер и включи ютуб")
    assert [(s.action, s.param) for s in d.steps] == [("app.switch_open", "браузер"),
                                                      ("youtube.open", None)]
    assert d.kind == "plan" and d.chat_tail is None and calls == []

    for phrase in ("открой ютуб", "сакура, включи ютуб пожалуйста", "зайди на ютуб"):
        assert route(router, phrase).action == "youtube.open", phrase

    # фраза, которую триггеры не покрывают, — обе части даёт LLM-разбор
    def parse(text, catalog, context):
        return IntentParse(actions=(("app.switch_open", "браузер"),
                                    ("youtube.open", None)), chat=False)
    router, _ = make_router(parse=parse)
    d = route(router, "в общем открой браузер и ютуб тоже")
    assert d.actions == ("app.switch_open", "youtube.open") and d.source == "llm"


def test_free_text_argument_is_not_split(make_router):
    """Союз внутри аргумента — не граница команд."""
    router, _ = make_router()
    for phrase, action in [("добавь задачу купить хлеб и молоко", "task.add"),
                           ("напомни через 20 минут полить цветы и покормить кота",
                            "reminder.add")]:
        d = route(router, phrase)
        assert (d.action, d.steps, d.chat_tail) == (action, (), None), phrase


# ── ложные триггеры в разговоре ────────────────────────────────────────

FALSE_TRIGGERS = [
    ("погода сегодня отвратительная, настроение на нуле", None),
    ("погода в последнее время ужасная", None),
    ("ну и погода", None),
    ("спасибо, дальше я сам", "playing:music"),
    ("а что было дальше", None),
    ("а что было дальше", "playing:music"),
    ("скинь следующий трек другу", "playing:music"),
    ("я вчера случайно выключил компьютер", None),
    ("он мне вчера сказал открой браузер и посмотри", None),
    ("не надо выключать компьютер", None),
    ("я забыл про расписание на сегодня", None),
    ("помнишь я говорил про следующий трек", "playing:music"),
]


@pytest.mark.parametrize("phrase,context", FALSE_TRIGGERS)
def test_trigger_inside_talk_is_not_a_command(make_router, phrase, context):
    router, _ = make_router()
    d = route(router, phrase, context)
    assert d.action is None and d.steps == (), (phrase, d)
    assert d.source == "conversation" and d.kind == "conversation"


@pytest.mark.parametrize("phrase,context", FALSE_TRIGGERS)
def test_talk_goes_to_llm_parse_not_to_trigger(make_router, phrase, context):
    """Спорная фраза доходит до LLM-разбора: решает модель, а не подстрока."""
    router, calls = make_router(parse=lambda *a: IntentParse(actions=(), chat=True))
    d = route(router, phrase, context)
    assert d.action is None and len(calls) == 1


# ── короткие триггеры как явные команды ────────────────────────────────

@pytest.mark.parametrize("phrase,context,action", [
    ("дальше", "playing:music", "music.next"),
    ("сакура, дальше", "playing:music", "music.next"),
    ("ну давай дальше", "playing:music", "music.next"),
    ("дальше, пожалуйста", "playing:music", "music.next"),
    ("погода", None, "weather.now"),
    ("погода сегодня", None, "weather.now"),
    ("какая погода", None, "weather.now"),
    ("сакура, стоп", None, "music.play_pause"),
    ("пауза", "playing:music", "music.play_pause"),
    ("следующий трек, пожалуйста", "playing:music", "music.next"),
    ("я выполнил задачу 5", None, "task.done"),
])
def test_short_trigger_as_explicit_command(make_router, phrase, context, action):
    router, calls = make_router(parse=lambda *a: pytest.fail("LLM не нужен"))
    d = route(router, phrase, context)
    assert d.action == action and d.chat_tail is None, (phrase, d)


# ── вежливые и длинные команды ─────────────────────────────────────────

@pytest.mark.parametrize("phrase,context,action", [
    ("пожалуйста сделай музыку немного потише если тебе не сложно", "playing:music",
     "music.volume_down"),
    ("сакура будь добра сделай пожалуйста чуть-чуть погромче если можно", "playing:music",
     "music.volume_up"),
    ("не могла бы ты пожалуйста поставить музыку на паузу", "playing:music",
     "music.play_pause"),
    ("слушай сакура ну давай пожалуйста уже следующий трек", "playing:music", "music.next"),
    ("будь добра поставь чайник пожалуйста если тебе не сложно", None, "kettle.boil"),
    ("пожалуйста закрой браузер", None, "close_window.браузер"),
])
def test_polite_long_command(make_router, phrase, context, action):
    router, _ = make_router()
    d = route(router, phrase, context)
    assert len(phrase.split()) > 2
    assert d.action == action, (phrase, d)


# ── косвенные просьбы ──────────────────────────────────────────────────

def test_indirect_kettle_with_temperature(make_router):
    router, _ = make_router()
    d = route(router, "что-то прохладно, поставь чайник на 85")
    assert (d.action, d.param) == ("kettle.heat", "85")
    assert d.kind == "hybrid" and d.chat_tail == "что-то прохладно"


@pytest.mark.parametrize("phrase,action,param", [
    # «на» + число или слово-число — нагрев до температуры
    ("поставь чайник на 85", "kettle.heat", "85"),
    ("поставь чайник на 85 градусов", "kettle.heat", "85"),
    ("включи чайник на восемьдесят", "kettle.heat", "80"),
    ("поставь чайник до 70", "kettle.heat", "70"),
    # «на» + место — обычное кипячение, без вопроса о температуре
    ("поставь чайник на кухне", "kettle.boil", None),
    ("включи чайник на работе", "kettle.boil", None),
    ("сакура, поставь чайник на плиту пожалуйста", "kettle.boil", None),
])
def test_kettle_heat_only_with_degrees(make_router, phrase, action, param):
    router, calls = make_router(parse=lambda *a: pytest.fail("LLM не нужен"))
    d = route(router, phrase)
    assert (d.action, d.param) == (action, param), (phrase, d)
    assert router.session.pending is None, "вопроса о температуре быть не должно"


def test_kettle_temperature_word_without_number_asks(make_router):
    """«на температуру» без числа — это нагрев: спрашиваем, до скольких."""
    router, _ = make_router()
    d = route(router, "поставь чайник на температуру")
    assert d.action is None and d.source == "registry_clarify"
    assert d.reply == "До какой температуры нагреть?"
    assert router.session.pending.action == "kettle.heat"


@pytest.mark.parametrize("phrase", ["что там на улице?", "что за окном", "как там на улице"])
def test_indirect_weather_question(make_router, phrase):
    router, _ = make_router()
    assert route(router, phrase).action == "weather.now"


def test_indirect_request_resolved_by_llm_with_context(make_router):
    """«тут слишком громко» триггером не ловится — решает разбор с контекстом."""
    seen = {}

    def parse(text, catalog, context):
        seen.update(context or {})
        return IntentParse(actions=(("music.volume_down", None),), chat=False)

    router, calls = make_router(parse=parse)
    d = route(router, "что-то тут слишком громко", "playing:music",
              dialog={"window": "Яндекс Музыка", "track": "Nirvana — Lithium",
                      "recent": ["Мастер: включи нирвану"]})
    assert (d.action, d.source) == ("music.volume_down", "llm")
    assert seen["context"] == "playing:music" and seen["track"] == "Nirvana — Lithium"
    assert seen["recent"] == ["Мастер: включи нирвану"]


# ── параметры времени и места ──────────────────────────────────────────

def test_weather_keeps_city_and_day(make_router, monkeypatch):
    import modules.voice_info as vi
    import modules.weather as weather

    router, _ = make_router()
    phrase = "какая погода будет завтра в Питере"
    d = route(router, phrase)
    assert d.action == "weather.now"
    assert weather.parse_weather_query(phrase) == ("питере", 1)
    assert weather.parse_weather_query("погода в Казани послезавтра") == ("казани", 2)
    assert weather.parse_weather_query("какая погода в выходные") == (None, 0)
    assert weather.parse_weather_query("что с погодой", "Самара завтра") == ("самара", 1)
    assert weather._city_candidates("питере") == ["Санкт-Петербург"]
    assert "казань" in weather._city_candidates("казани")
    assert "москва" in weather._city_candidates("москве") or \
        weather._city_candidates("москве") == ["Москва"]

    asked = {}

    async def fake_geocode(city):
        asked["city"] = city
        return (59.94, 30.31, "Санкт-Петербург")

    async def fake_weather(lat=None, lon=None):
        asked["coords"] = (lat, lon)
        return {"temp": 3.0, "desc": "облачно", "wind": 4.0, "daily": [
            {"t_min": 1.0, "t_max": 4.0, "weather": "cloudy", "pop": 10},
            {"t_min": 2.0, "t_max": 6.0, "weather": "rain", "pop": 80},
            {"t_min": 0.0, "t_max": 3.0, "weather": "snow", "pop": 40}]}

    monkeypatch.setattr(weather, "geocode", fake_geocode)
    monkeypatch.setattr(weather, "get_weather", fake_weather)
    text, ok = _run(vi.handle("weather:now", "", phrase))
    assert ok and asked == {"city": "питере", "coords": (59.94, 30.31)}
    assert text == "Завтра — Санкт-Петербург: от 2.0 до 6.0°C, дождь. вероятность осадков 80%."

    text, ok = _run(vi.handle("weather:now", "", "какая погода"))
    assert ok and text.startswith("Сейчас 3.0°C") and asked["coords"] == (None, None)

    async def no_city(city):
        return None
    monkeypatch.setattr(weather, "geocode", no_city)
    text, ok = _run(vi.handle("weather:now", "", "погода в Зюзюкинске"))
    assert ok is False and "Не нашла город" in text


@pytest.mark.parametrize("phrase,delay", [
    ("выключи компьютер через час", "через час"),
    ("выключи компьютер через 30 минут", "через 30 минут"),
    ("перезагрузи компьютер в 23:00", "в 23:00"),
    ("усыпи компьютер через полчаса", "через полчаса"),
    ("выключи компьютер вечером", "вечером"),
    ("сакура, выключи пк через пару минут пожалуйста", "через пару минут"),
])
def test_delayed_power_command_is_never_immediate(make_router, phrase, delay):
    router, _ = make_router()
    d = route(router, phrase)
    assert d.action is None and d.steps == (), "немедленное выключение запрещено"
    assert d.source == "registry_deferred"
    assert isinstance(d.reply, str) and delay in d.reply
    assert find_delay(phrase) == delay
    assert router.session.pending is None, "вопрос «выключить?» задаваться не должен"


def test_delayed_power_command_blocked_on_llm_path_too(make_router):
    """Даже если модель вернула system.shutdown — «через час» его останавливает."""
    router, _ = make_router(
        parse=lambda *a: IntentParse(actions=(("system.shutdown", None),), chat=False))
    d = route(router, "в общем погаси машину через час, выключи её")
    assert d.action is None and d.source == "registry_deferred"


def test_immediate_power_command_still_works(make_router):
    router, _ = make_router()
    d = route(router, "выключи компьютер")
    assert (d.action, d.source) == ("system.shutdown", "registry_exact")
    d = route(router, "сакура, перезагрузи компьютер пожалуйста")
    assert d.action == "system.restart"


# ── гибрид «команда + разговор» ────────────────────────────────────────

def test_hybrid_command_plus_talk(make_router):
    router, calls = make_router(parse=lambda *a: pytest.fail("LLM не нужен"))
    d = route(router, "кстати поставь чайник, а я пока расскажу как прошёл день")
    assert d.action == "kettle.boil" and d.kind == "hybrid"
    assert [s.action for s in d.steps] == ["kettle.boil"]
    assert d.chat_tail == "я пока расскажу как прошёл день"
    assert calls == []


# ── разбиение фразы ────────────────────────────────────────────────────

def test_split_units():
    parts = lambda s: [u for u, _ in split_units(s)]  # noqa: E731
    assert parts("включи музыку и сделай погромче") == ["включи музыку", "сделай погромче"]
    assert parts("поставь чайник, а потом включи музыку") == ["поставь чайник", "включи музыку"]
    assert parts("пауза затем следующий плюс погромче") == ["пауза", "следующий", "погромче"]
    assert parts("следующий трек") == ["следующий трек"]
    assert parts("следующий трек, пожалуйста") == ["следующий трек, пожалуйста"]
    assert parts("ну и погода") == ["ну и погода"]
    assert parts("раз, два, три, четыре, пять, шесть") == ["раз, два, три, четыре, пять, шесть"]


# ══ 2. LLM-разбор и откат ═══════════════════════════════════════════════


def test_parse_intent_response_formats():
    p = llm._parse_intent_response
    assert p('{"actions":[{"id":"music.next","param":null},{"id":"kettle.heat","param":85}],'
             '"chat":true}') == IntentParse(
        actions=(("music.next", None), ("kettle.heat", "85")), chat=True)
    assert p('```json\n{"actions":[],"chat":true}\n```') == IntentParse((), True)
    assert p('{"actions":[{"id":"weather.now","param":"Санкт-Петербург завтра"}],"chat":false}') \
        == IntentParse((("weather.now", "Санкт-Петербург завтра"),), False)
    # прежние формы классификатора остаются понятны
    assert p("music.next") == IntentParse((("music.next", None),), False)
    assert p("kettle.heat | 85") == IntentParse((("kettle.heat", "85"),), False)
    assert p("null") == IntentParse((), True)
    assert p('{"id": "kettle.heat", "param": "85"}') == IntentParse((("kettle.heat", "85"),), False)
    for broken in ("", "   ", None, object()):
        with pytest.raises(LlmUnavailable):
            p(broken)


def test_parse_intent_passes_context_and_separates_failure(monkeypatch):
    seen = {}

    async def fake_generate(contents, **kw):
        seen.update(kw, contents=contents)
        return '{"actions":[{"id":"music.volume_down","param":null}],"chat":false}'

    monkeypatch.setattr(llm, "generate", fake_generate)
    res = _run(llm.parse_intent("тут слишком громко", "- music.volume_down: тише",
                                context={"context": "playing:music", "window": "Chrome",
                                         "track": "A — B", "recent": ["Мастер: включи музыку"]}))
    assert res.actions == (("music.volume_down", None),)
    system = seen["system"]
    assert "Каталог действий:" in system and "playing:music" in system
    assert "сейчас играет: A — B" in system and "Мастер: включи музыку" in system

    async def boom(contents, **kw):
        raise RuntimeError("сеть лежит")
    monkeypatch.setattr(llm, "generate", boom)
    with pytest.raises(LlmUnavailable):
        _run(llm.parse_intent("тут слишком громко", "каталог"))

    async def hang(contents, **kw):
        await asyncio.sleep(5)
    monkeypatch.setattr(llm, "generate", hang)
    t0 = time.monotonic()
    with pytest.raises(LlmUnavailable):
        _run(llm.parse_intent("тут слишком громко", "каталог", timeout=0.1))
    assert time.monotonic() - t0 < 2.0


def test_llm_plan_and_hybrid(make_router):
    def parse(text, catalog, context):
        return IntentParse(actions=(("music.volume_down", None), ("kettle.heat", "85"),
                                    ("no.such_action", None)), chat=True)
    router, _ = make_router(parse=parse)
    phrase = "приглуши там всё и чаю бы градусов на 85, а я пока расскажу про день"
    d = route(router, phrase)
    assert [(s.action, s.param) for s in d.steps] == [("music.volume_down", None),
                                                      ("kettle.heat", "85")]
    assert d.source == "llm" and d.chat_tail == phrase


def test_llm_param_validated_by_registry_schema(make_router):
    # числовой параметр без цифр отбрасывается и берётся из фразы
    router, _ = make_router(parse=lambda *a: IntentParse((("kettle.heat", "погорячее"),), False))
    d = route(router, "в общем согрей водички градусов до 70")
    assert (d.action, d.param) == ("kettle.heat", "70")
    # нет значения у обязательного параметра → уточняющий вопрос
    router, _ = make_router(parse=lambda *a: IntentParse((("kettle.heat", None),), False))
    d = route(router, "в общем согрей водички")
    assert d.action is None and d.source == "registry_clarify"
    assert d.reply == "До какой температуры нагреть?"
    assert router.session.pending.action == "kettle.heat"


def test_llm_failure_falls_back_to_local_parse(make_router):
    """Сбой LLM — не вердикт «разговор»: вероятная команда исполняется локально."""
    router, calls = make_router(parse=lambda *a: LlmUnavailable("таймаут"))
    d = route(router, "в общем включи музыку какую-нибудь")
    assert len(calls) == 1
    assert (d.action, d.source) == ("open.app", "registry_fallback")

    d = route(router, "в общем включи музыку и в общем поставь чайник")
    assert d.actions == ("open.app", "kettle.boil") and d.source == "registry_fallback"

    # разговор и отрицание остаются разговором и при сбое
    for phrase in ("погода сегодня отвратительная, настроение на нуле",
                   "он вчера сказал включи музыку", "только не включи музыку случайно"):
        d = route(router, phrase)
        assert d.action is None and d.source == "conversation", phrase


def test_llm_says_talk_means_talk(make_router):
    """Вердикт модели «разговор» локальным разбором не оспаривается."""
    router, calls = make_router(parse=lambda *a: IntentParse(actions=(), chat=True))
    d = route(router, "в общем включи музыку какую-нибудь")
    assert d.action is None and d.source == "conversation" and len(calls) == 1


def test_legacy_classifier_contract_still_supported(make_router):
    router, _ = make_router(classify=lambda text, catalog: ("music.play_track", "nirvana"))
    d = route(router, "вруби мне что-нибудь из нирваны фоном")
    assert (d.action, d.source, d.param) == ("music.play_track", "llm", "nirvana")
    router, _ = make_router(classify=lambda text, catalog: None)
    assert route(router, "расскажи анекдот про кота").source == "conversation"


def test_decision_backward_compatible_fields():
    d = Decision("music.next", "registry_exact", trigger="следующий трек")
    assert (d.action, d.param, d.steps, d.chat_tail, d.kind) == ("music.next", None, (), None,
                                                                 "command")
    assert d.actions == ("music.next",) and len(d.plan) == 1 and not d.is_plan
    assert Decision(None, "conversation").kind == "conversation"
    assert Decision(None, "conversation").plan == ()
    assert d == Decision("music.next", "registry_exact", trigger="следующий трек")


# ══ 3. мост: исполнение плана и гибрида ═════════════════════════════════


@pytest.fixture
def bridge(monkeypatch):
    """Боевой роутер моста без LLM; исполнение перехвачено."""
    results: dict = {}
    executed: list = []

    async def fake_execute(decision, *, text="", **kw):
        if not decision.action:
            return False, None
        executed.append((decision.action, decision.param, text))
        if decision.action in results:
            return True, results[decision.action]
        return True, f"cmd-{len(executed)}"

    async def no_llm(contents, **kw):
        raise RuntimeError("LLM в этом тесте недоступен")

    monkeypatch.setattr(llm, "generate", no_llm)
    monkeypatch.setattr(br, "_router", None)
    monkeypatch.setattr(br, "_executor", None)
    monkeypatch.setattr(br, "execute_decision", fake_execute)
    return results, executed


def _fast(text, data=None, **kw):
    return _run(br.v3_fast_path(text, data=data or {}, device_ws=None, device_id="pc",
                                register_command=lambda *a, **k: None, **kw))


def test_bridge_runs_plan_in_order_with_single_ack(bridge):
    results, executed = bridge
    armed, spoken, verdicts = [], [], []

    async def on_agent(decision, cmd_id):
        armed.append((decision.action, cmd_id))

    async def speak(text, listen=None):
        spoken.append(text)

    async def on_command():
        verdicts.append(len(executed))

    assert _fast("включи музыку и сделай погромче", speak=speak,
                 on_agent_command=on_agent, on_command=on_command) is True
    assert [(a, p) for a, p, _ in executed] == [("open.app", None), ("music.volume_up", None)]
    assert [t for _, _, t in executed] == ["включи музыку", "сделай погромче"]
    assert armed == [("music.volume_up", "cmd-2")], "одно подтверждение — по последней команде"
    assert spoken == [] and verdicts == [0], "prefetch снимается до исполнения"


def test_bridge_plan_merges_text_results_into_one_reply(bridge):
    results, executed = bridge
    results["weather.now"] = ("Сейчас +5, облачно.", False)
    results["schedule.today"] = ("Сегодня две пары.", False)
    spoken, armed = [], []

    async def speak(text, listen=None):
        spoken.append(text)

    async def on_agent(decision, cmd_id):
        armed.append(cmd_id)

    assert _fast("какая погода и расписание на сегодня", speak=speak,
                 on_agent_command=on_agent) is True
    assert [a for a, _, _ in executed] == ["weather.now", "schedule.today"]
    assert spoken == ["Сейчас +5, облачно. Сегодня две пары."]
    assert armed == []


def test_bridge_plan_in_telegram_answers_once(bridge):
    results, executed = bridge
    answers = []

    async def ack(text):
        answers.append(text)

    assert _fast("поставь чайник и включи музыку", ack=ack) is True
    assert [a for a, _, _ in executed] == ["kettle.boil", "open.app"]
    assert answers == ["Готово."]


def test_bridge_hybrid_executes_then_talks_with_action_context(bridge):
    results, executed = bridge
    chats, spoken, armed = [], [], []
    phrase = "кстати поставь чайник, а я пока расскажу как прошёл день"

    async def on_chat(text):
        # в этот момент разговорная модель видит, что уже сделано
        chats.append((text, list(executed), action_note.prompt_block()))

    async def speak(text, listen=None):
        spoken.append(text)

    async def on_agent(decision, cmd_id):
        armed.append(cmd_id)

    assert _fast(phrase, speak=speak, on_chat=on_chat, on_agent_command=on_agent) is True
    (chat_text, executed_before_chat, note), = chats
    assert chat_text == phrase
    assert [a for a, _, _ in executed_before_chat] == ["kettle.boil"], "сначала команда"
    assert "ТОЛЬКО ЧТО ВЫПОЛНЕНО" in note and "команда отправлена на устройство" in note
    assert "не выполняй и не обещай их заново" in note
    assert spoken == [] and armed == [], "подтверждение скажет разговорный ответ"
    assert action_note.current() is None, "заметка живёт только в пределах хода"


def test_bridge_hybrid_note_reaches_system_prompt(bridge):
    import sakura_core.prompt as prompt
    seen = {}

    async def on_chat(text):
        seen["system"] = await prompt._build_system(query=text)

    _fast("что-то прохладно, поставь чайник на 85", on_chat=on_chat)
    assert bridge[1][0][:2] == ("kettle.heat", "85")
    assert "ТОЛЬКО ЧТО ВЫПОЛНЕНО" in seen["system"]
    after = _run(prompt._build_system(query="как дела"))
    assert "ТОЛЬКО ЧТО ВЫПОЛНЕНО" not in after


def test_bridge_hybrid_without_chat_hook_still_executes(bridge):
    results, executed = bridge
    answers = []

    async def ack(text):
        answers.append(text)

    assert _fast("кстати поставь чайник, а я пока расскажу как прошёл день", ack=ack) is True
    assert [a for a, _, _ in executed] == ["kettle.boil"] and answers == ["Готово."]


def test_bridge_delayed_shutdown_executes_nothing(bridge):
    results, executed = bridge
    spoken = []

    async def speak(text, listen=None):
        spoken.append(text)

    assert _fast("выключи компьютер через час", speak=speak) is True
    assert executed == []
    assert len(spoken) == 1 and "через час" in spoken[0] and "не умею" in spoken[0]


def test_bridge_clarify_question_is_spoken(bridge):
    results, executed = bridge
    spoken = []

    async def speak(text, listen=None):
        spoken.append(text)

    assert _fast("нагрей воду", speak=speak) is True
    assert executed == [] and spoken == ["До какой температуры нагреть?"]


def test_bridge_falls_back_locally_when_llm_is_down(bridge):
    """LLM недоступен (generate падает) — вероятная команда всё равно исполняется."""
    results, executed = bridge
    assert _fast("в общем включи музыку какую-нибудь") is True
    assert [a for a, _, _ in executed] == ["open.app"]
    executed.clear()
    assert _fast("мне сегодня приснился странный сон про море") is False and executed == []


def test_bridge_false_trigger_reaches_conversation(bridge):
    results, executed = bridge
    for phrase in ("погода сегодня отвратительная, настроение на нуле",
                   "скинь следующий трек другу", "а что было дальше"):
        assert _fast(phrase) is False, phrase
    assert executed == []


# ══ задержки и окружение ════════════════════════════════════════════════


def test_voice_latency_budgets():
    assert config.STYLIZE_TIMEOUT_S <= 1.0
    assert config.INTENT_TIMEOUT_S < config.VOICE_GATE_WAIT_S <= 3.0
    assert config.ACK_PENDING_S <= 1.5


def test_stylize_never_blocks_longer_than_budget(monkeypatch):
    from sakura_core.stylize import humanize_command_reply

    async def slow(*a, **kw):
        await asyncio.sleep(5)
        return "красиво"

    monkeypatch.setattr(config, "STYLIZE_TIMEOUT_S", 0.2)
    t0 = time.monotonic()
    out = _run(humanize_command_reply("Сейчас +5.", action="weather.now", llm_generator=slow))
    assert out == "Сейчас +5." and time.monotonic() - t0 < 1.0

    async def never(*a, **kw):
        pytest.fail("при выключенной стилизации модель не вызывается")
    monkeypatch.setattr(config, "STYLIZE_TIMEOUT_S", 0)
    assert _run(humanize_command_reply("Сейчас +5.", action="weather.now",
                                       llm_generator=never)) == "Сейчас +5."


def test_sqlite_vec_extension_loads():
    import memory.db as db
    conn = db._conn()
    assert conn.execute("select vec_version()").fetchone()[0]
