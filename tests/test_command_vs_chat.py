"""Golden-набор «Команда vs Разговор» и юнит-тесты Волны 2 (NLU, контекст, parse_intent, early_gate)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import config
import sakura_core.bridge as bridge
import sakura_core.early_gate as early_gate
import sakura_core.llm as llm
from sakura_core import registry
from sakura_core.nlu import IntentParse
from sakura_core.router import Decision, Router


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# (phrase, context, expected_actions_tuple_or_None_for_chat, note)
# expected_actions = () → строго РАЗГОВОР (не команда)
# expected_actions = ("id", ...) → ожидаемая команда или план команд
GOLDEN_CHAT_TRAPS: tuple[tuple[str, str | None, tuple[str, ...], str], ...] = (
    # Обязательные кейсы из аудита:
    ("не выключай музыку", "playing:music", (), "отрицание не должно триггерить system.shutdown_cancel"),
    ("гугл хром опять завис", None, (), "жалоба на браузер без глагола закрытия"),
    ("что в очереди за хлебом?", None, (), "бытовой вопрос с хвостом вне музыки"),
    ("что в очереди за хлебом?", "playing:music", (), "хвост 'за хлебом' даже при playing:music"),
    ("всё с начала пошло наперекосяк", "playing:music", (), "идиома со 'с начала' + посторонний хвост"),
    ("я играю в настолку с друзьями", None, (), "констатация факта, не game_mode.on"),
    ("не нравится эта погода", "playing:music", (), "жалоба на погоду при играющей музыке"),
    ("не нравится эта погода", None, (), "жалоба на погоду без музыки"),
    ("что нового у тебя?", None, (), "приветственный вопрос, не briefing.now"),
    ("что произошло вчера?", None, (), "вопрос о прошлом, не briefing.now"),
    ("где выход из метро?", None, (), "бытовой вопрос, не scrap_mechanic.where_elevator"),
    ("завтра поставлю чайник", None, (), "будущее время + глагол 1-го лица"),
    ("я вчера закрыл браузер", None, (), "прошедшее время / рассказ"),
    ("а ты умеешь ставить таймер?", None, (), "мета-вопрос о возможностях"),
    ("если я сейчас закрою браузер, вкладки сохранятся?", None, (), "условный вопрос"),
    ("он попросил поставить чайник", None, (), "пересказ чужой просьбы"),
    ("просто шучу, не надо ничего закрывать", None, (), "шутка + отрицание"),
    ("с начала", None, (), "пауза / нет playing:music — не restart_playing"),

    # Дополнительные отрицания и отказы:
    ("не надо открывать браузер", None, (), "фраза отказа 'не надо'"),
    ("не стоит включать музыку сейчас", None, (), "отказ 'не стоит'"),
    ("лучше не выключай компьютер", None, (), "отказ 'лучше не'"),
    ("ни за что не ставь лайк", "playing:music", (), "отказ 'ни за что'"),
    ("перестань включать таймер", None, (), "запрет 'перестань'"),

    # Будущее время, планы и 1-е лицо:
    ("потом включу музыку", None, (), "план 'потом включу'"),
    ("собираюсь закрыть браузер после работы", None, (), "намерение о себе"),
    ("надо будет поставить чайник попозже", None, (), "план 'надо будет'"),
    ("послезавтра включу режим игры", None, (), "будущее время для не-временного домена"),
    ("вечером поставлю чайник себе", None, (), "вечером + поставлю + чужой хвост"),

    # Прошедшее время и пересказ сквозь союзы:
    ("вчера я включил музыку и пошёл спать", None, (), "прошедшее время + союз 'и'"),
    ("прикинь, он сказал поставь чайник", None, (), "пересказ с 'прикинь' не режется"),
    ("она попросила сделать погромче", "playing:music", (), "пересказ с 'попросила'"),
    ("помнишь как я ставил чайник и забыл про него", None, (), "воспоминание с 'помнишь как'"),

    # Мета-вопросы, гипотезы и общеязыковые слова:
    ("как работает поиск?", None, (), "мета-вопрос 'как работает'"),
    ("зачем нужен скриншот?", None, (), "мета-вопрос 'зачем нужен'"),
    ("что делает эта кнопка?", None, (), "мета-вопрос 'что делает'"),
    ("расскажи про игровой режим", None, (), "мета-вопрос 'расскажи про'"),
    ("допустим я выключу компьютер, данные останутся?", None, (), "гипотеза 'допустим'"),
    ("тишина в комнате такая приятная", None, (), "бытовая фраза, не music.mute"),
    ("продолжай, мне очень интересно", None, (), "реплика в диалоге, не music.play_pause"),
    ("мне понравилось как ты объяснила", None, (), "благодарность, не music.like"),
    ("сделай повтор домашней работы", None, (), "обычное 'повтор', не music.repeat"),
    ("где вещи в шкафу лежат?", None, (), "бытовой вопрос, не scrap_mechanic.where_bag"),
)

GOLDEN_COMMANDS: tuple[tuple[str, str | None, tuple[str, ...], str], ...] = (
    # Базовые команды без контекста и с контекстом None:
    ("включи музыку", None, ("open.app",), "прямой запуск музыки"),
    ("поставь чайник", None, ("kettle.boil",), "чайник без параметров"),
    ("поставь чайник на кухне", None, ("kettle.boil",), "чайник со слотом места"),
    ("поставь чайник на 85", None, ("kettle.heat",), "чайник с температурой"),
    ("какая погода", None, ("weather.now",), "текущая погода"),
    ("какая погода завтра в Питере", None, ("weather.now",), "погода с временным и гео-слотом"),
    ("закрой браузер", None, ("close_window.браузер",), "императивное закрытие браузера"),
    ("закрой гугл хром", None, ("close_window.браузер",), "уточнённый триггер закрытия Chrome"),
    ("отмени выключение", None, ("system.shutdown_cancel",), "явная отмена выключения"),
    ("выключи компьютер", None, ("system.shutdown",), "выключение ПК"),
    ("открой браузер", None, ("app.switch_open",), "открытие установленного приложения"),
    ("открой ютуб", None, ("youtube.open",), "открытие YouTube"),
    ("сделай брифинг", None, ("briefing.now",), "явный запрос брифинга"),
    ("включи игровой режим", None, ("game_mode.on",), "явное включение игрового режима"),
    ("добавь задачу купить хлеб и молоко", None, ("task.add",), "параметрическая задача со свободным хвостом"),
    ("напомни завтра позвонить врачу", None, ("task.add",), "задача с будущим временем"),
    ("сакура, стоп", None, ("music.play_pause",), "стоп с wake-словом"),

    # Команды в контекстах playing:music, window:youtube, window:browser:
    ("сделай погромче", "playing:music", ("music.volume_up",), "громкость музыки в playing:music"),
    ("дальше", "playing:music", ("music.next",), "следующий трек"),
    ("дальше, пожалуйста", "playing:music", ("music.next",), "короткий триггер с вежливым хвостом"),
    ("перемотай вперёд", "playing:music", ("music.seek_forward",), "перемотка музыки"),
    ("перемотай вперёд", "window:youtube", ("youtube.forward",), "перемотка YouTube при паузе/вне музыки"),
    ("назад в браузере", "window:browser", ("browser.back",), "навигация в браузере"),
    ("что в очереди", "playing:music", ("music.queue_show",), "очередь при играющей музыке"),
    ("не нравится трек", "playing:music", ("music.dislike",), "дизлайк при играющей музыке"),
    ("с начала", "playing:music", ("music.restart_playing",), "перезапуск играющего трека"),
    ("где мой рюкзак", None, ("scrap_mechanic.where_bag",), "команда Scrap Mechanic"),

    # Составные планы и гибрид «команда + разговор»:
    ("включи музыку и сделай погромче", None, ("open.app", "music.volume_up"), "двухшаговый план с implied context"),
    ("громкость на 30 и следующий трек", "playing:music", ("system.volume", "music.next"), "план с числовым параметром"),
    ("кстати поставь чайник, а я пока расскажу как прошёл день", None, ("kettle.boil",), "гибрид команда + разговор"),
)

GOLDEN_COMMAND_VS_CHAT = GOLDEN_CHAT_TRAPS + GOLDEN_COMMANDS


@pytest.fixture(autouse=True)
def _installed_apps_fixture():
    registry.set_installed_apps(["браузер", "хром", "steam", "блокнот"])
    yield
    registry.set_installed_apps([])


def test_golden_corpus_minimum_sizes():
    assert len(GOLDEN_CHAT_TRAPS) >= 35
    assert len(GOLDEN_COMMANDS) >= 25
    assert len(GOLDEN_COMMAND_VS_CHAT) >= 60


@pytest.mark.parametrize("phrase,ctx,expected,note", GOLDEN_CHAT_TRAPS)
def test_golden_chat_traps_stay_conversation(phrase, ctx, expected, note):
    router = Router(declarations=bridge._declarations, llm_parse=None)
    d = _run(router.route(phrase, ctx))
    assert d.action is None and d.steps == (), f"{note}: {phrase!r} -> {d}"
    assert d.source == "conversation"


@pytest.mark.parametrize("phrase,ctx,expected,note", GOLDEN_COMMANDS)
def test_golden_commands_route_correctly(phrase, ctx, expected, note):
    router = Router(declarations=bridge._declarations, llm_parse=None)
    d = _run(router.route(phrase, ctx))
    assert d.actions == expected, f"{note}: {phrase!r} (ctx={ctx}) -> {d}"


# ── Специфические юнит-тесты Волны 2 ──────────────────────────────────────


def test_paused_music_does_not_yield_playing_music_context():
    paused = {"artist": "Artist", "title": "Song", "status": "пауза"}
    stopped = {"artist": "Artist", "title": "Song", "status": "stopped"}
    playing = {"artist": "Artist", "title": "Song", "status": "играет"}

    assert bridge.resolve_context("YouTube — клип", paused) == "window:youtube"
    assert bridge.resolve_context("Google Chrome", paused) == "window:browser"
    assert bridge.resolve_context("Проводник", stopped) is None
    assert bridge.resolve_context("YouTube — клип", playing) == "playing:music"

    # «с начала» при паузе НЕ уходит в music.restart_playing
    ctx = bridge.resolve_context("Google Chrome", paused)
    router = Router(declarations=bridge._declarations, llm_parse=None)
    d = _run(router.route("с начала", ctx))
    assert d.action is None and d.source == "conversation"


def test_low_confidence_parse_resets_to_conversation():
    async def low_conf(text, catalog, context=None):
        return IntentParse(actions=(("kettle.boil", None),), chat=False, confidence=0.45)

    router = Router(declarations=bridge._declarations, llm_parse=low_conf)
    d = _run(router.route("может быть потом чаю"))
    assert d.action is None and d.source == "conversation"

    async def high_conf(text, catalog, context=None):
        return IntentParse(actions=(("kettle.boil", None),), chat=False, confidence=0.92)

    router2 = Router(declarations=bridge._declarations, llm_parse=high_conf)
    d2 = _run(router2.route("хотелось бы горячего чаю сейчас"))
    assert d2.action == "kettle.boil" and d2.source == "llm"


def test_generate_and_parse_intent_pass_response_schema(monkeypatch):
    seen_cfg = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            seen_cfg["model"] = model
            seen_cfg["mime"] = getattr(config, "response_mime_type", None)
            seen_cfg["schema"] = getattr(config, "response_schema", None)
            return SimpleNamespace(
                text='{"actions":[{"id":"music.next","param":null}],"chat":false,"confidence":0.91}'
            )

    monkeypatch.setattr(config, "INTENT_MODEL_CHAIN", ("gemma-4-26b-a4b-it",))
    monkeypatch.setattr(config, "get_active_key", lambda: "test-key")
    monkeypatch.setattr(llm, "get_client", lambda k: SimpleNamespace(models=_FakeModels()))

    parsed = _run(llm.parse_intent("следующий давай", "- music.next: дальше"))
    assert parsed == IntentParse(actions=(("music.next", None),), chat=False, confidence=0.91)
    assert seen_cfg["model"] == "gemma-4-26b-a4b-it"
    assert seen_cfg["mime"] == "application/json"
    assert seen_cfg["schema"] is not None

    # Произвольный текст (не JSON и не валидный domain.verb) никогда не даёт chat=False
    prose = llm._parse_intent_response("Извините, я не уверена что вы хотите сделать")
    assert prose == IntentParse(actions=(), chat=True, confidence=1.0)
    ascii_word = llm._parse_intent_response("hello")
    assert ascii_word == IntentParse(actions=(), chat=True, confidence=1.0)


def test_dialog_context_includes_pending_and_telegram_active_window(tmp_path, monkeypatch):
    import json
    import adapters.telegram as tg
    import modules.device_manager as dm
    import modules.state as st
    from datetime import datetime

    # 1. _dialog_context включает pending из session
    router = Router(declarations=bridge._declarations, llm_parse=None)
    router.session.expect("confirm", action="memory.forget", device="tg", payload={"param": "секрет"})
    monkeypatch.setattr(bridge, "_router", router)
    ctx = bridge._dialog_context({"active_window": "Chrome"}, "pc", source="telegram")
    assert ctx["pending"] == "confirm: memory.forget: секрет"

    # 2. Telegram подставляет свежее active_window подключённого ПК
    dev_file = tmp_path / "devices.json"
    dev_file.write_text(json.dumps({
        "active_device": "pc",
        "devices": {
            "pc": {
                "online": True,
                "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "active_window": "YouTube — Chrome",
            }
        }
    }), encoding="utf-8")
    monkeypatch.setattr(dm, "DEVICES_FILE", str(dev_file))
    monkeypatch.setitem(st.connected_devices, "pc", object())
    try:
        assert tg._active_device_window("pc") == "YouTube — Chrome"
    finally:
        st.connected_devices.pop("pc", None)


@pytest.mark.parametrize("phrase", [
    "какая погода?",
    "что сейчас играет?",
    "сколько времени?",
    "который час?",
    "что в календаре?",
    "что на экране?",
    "что на странице?",
])
def test_early_gate_skips_tool_questions(phrase):
    assert not early_gate.opens_early(phrase)
    assert early_gate.opens_early("Как дела?")
    assert early_gate.opens_early("почему небо голубое")
