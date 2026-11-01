"""feat/vision-intent: вопрос про игру во время игры сам идёт через зрение.

Случай 01.11: «А что сейчас по квесту сделать надо?» → классификатор →
task.list «Активных задач нет».
Run: python -m pytest tests/test_vision_intent.py -q
"""
import asyncio

import pytest

from sakura_core.vision import intent, seen


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    seen.reset()
    from modules import steam_integration
    monkeypatch.setattr(steam_integration, "_current_game", None, raising=False)
    yield
    seen.reset()


def playing(subject="Scrap Mechanic", at=1000.0):
    seen.record("pc", subject, "режим выживания", "ask", now=at, subject=subject)


@pytest.mark.parametrize("phrase", [
    "А что сейчас по квесту сделать надо?",
    "где найти бота-мастера",
    "как построить бота-мастера?",
    "куда идти дальше",
    "как убить этого босса",
    "что мне делать дальше",
    "подскажи рецепт верстака",
])
def test_game_questions_during_game(phrase):
    playing()
    assert intent.wants_screen(phrase, None, now=1100.0)


@pytest.mark.parametrize("phrase", [
    "что по квесту",                          # «квест» — явно про игру, вопрос
    "что делать в игре дальше?",
])
def test_explicit_game_words_without_game_signal(phrase):
    assert intent.wants_screen(phrase, None, now=1.0)


@pytest.mark.parametrize("phrase", [
    "где найти хорошую пиццу",                # без игры — не про экран
    "как сделать отчёт",
    "что мне делать завтра",
])
def test_no_game_no_screen(phrase):
    assert not intent.wants_screen(phrase, "Документ — Word", now=1.0)


@pytest.mark.parametrize("phrase", [
    "включи музыку в игре",                    # команда
    "напомни про квест через час",
    "квест",                                   # не вопрос
    "отличный уровень",
    "спасибо",
])
def test_commands_and_non_questions_not_intercepted(phrase):
    playing()
    assert not intent.wants_screen(phrase, None, now=1100.0)


def test_game_signals():
    assert not intent.game_on("Документ — Word", now=1.0)
    assert intent.game_on("Terraria", now=1.0)                       # окно игры
    playing(at=1000.0)
    assert intent.game_on(None, now=1000.0 + intent.RECENT_SEEN_S - 1)
    assert not intent.game_on(None, now=1000.0 + intent.RECENT_SEEN_S + 1)


def test_steam_game_counts(monkeypatch):
    from modules import steam_integration
    monkeypatch.setattr(steam_integration, "_current_game", {"name": "Scrap Mechanic"}, raising=False)
    assert intent.wants_screen("где найти бота-мастера", None, now=1.0)


# ── мост: правило срабатывает до классификатора ────────────────────

def test_bridge_routes_game_question_to_vision(monkeypatch):
    from sakura_core import bridge
    from sakura_core.router import Decision
    playing(at=__import__("time").monotonic())
    routed, executed = [], []

    class Router:
        class session:
            pending = None

        async def route(self, text, context, **kw):
            routed.append(text)
            return Decision(action="task.list", source="llm")

    async def execute(decision, **kw):
        executed.append(decision.action)
        return True, ("Нужно построить бота-мастера.", True)

    spoken = []

    async def speak(text, **kw):
        spoken.append(text)

    monkeypatch.setattr(bridge, "get_router", lambda: Router())
    monkeypatch.setattr(bridge, "execute_decision", execute)
    ok = asyncio.run(bridge.v3_fast_path("А что сейчас по квесту сделать надо?", data={}, device_ws=None,
                                         device_id="pc", register_command=None, speak=speak))
    assert ok and executed == ["vision.ask"] and routed == []
    assert spoken == ["Нужно построить бота-мастера."]


def test_bridge_pending_confirm_goes_to_router(monkeypatch):
    from sakura_core import bridge
    from sakura_core.router import Decision
    playing(at=__import__("time").monotonic())
    routed = []

    class Router:
        class session:
            pending = object()

        async def route(self, text, context, **kw):
            routed.append(text)
            return Decision(action=None, source="conversation")

    monkeypatch.setattr(bridge, "get_router", lambda: Router())
    asyncio.run(bridge.v3_fast_path("где найти бота-мастера?", data={}, device_ws=None,
                                    device_id="pc", register_command=None))
    assert routed == ["где найти бота-мастера?"]


def test_same_window_as_seen_long_ago_is_game():
    """Окно игры то же, что Сакура видела час назад: игра идёт (Scrap Mechanic нет
    в списке игр по заголовку)."""
    seen.record("pc", "Scrap Mechanic", "лес", "ask", now=1000.0, subject="Scrap Mechanic")
    later = 1000.0 + 3600
    assert intent.game_on("Scrap Mechanic", now=later)
    assert intent.wants_screen("Где взять хлопок в Скраэбмеханик?", "Scrap Mechanic", now=later)
    assert not intent.game_on("Telegram", now=later)
    assert not intent.game_on(None, now=later)


# ── страхи не перехватывают вопросы ────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "Где взять хлопок в Скраэбмеханик?",
    "как сделать хлопок",
    "почему ты боишься грома",
    "в игре был такой громкий взрыв что я подпрыгнул на стуле",
])
def test_fears_skip_questions_and_long_phrases(phrase):
    from conversation import fears
    assert fears.try_handle(phrase, {}) is None


@pytest.mark.parametrize("phrase", ["гроза за окном", "ой как громко", "хлопок!"])
def test_fears_still_react_to_short_exclamations(phrase):
    from conversation import fears
    assert fears.try_handle(phrase, {}) is not None
