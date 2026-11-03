"""tests/test_intimacy_v2.py — режим 18+ v2: каналы, детектор, промпт, безопасность, журнал.

Run: python3 -m pytest tests/test_intimacy_v2.py -q
"""
import asyncio
import logging

import pytest

import modules.intimacy_mode as im


@pytest.fixture
def clock(monkeypatch):
    """Фиктивные часы monotonic для TTL."""
    t = {"now": 1000.0}
    monkeypatch.setattr(im._time, "monotonic", lambda: t["now"])
    return t


# ── детектор ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "давнее желание поехать в Японию",
    "грудь болит после жима",
    "кровать сломалась, надо новую",
    "между нами говоря, проект так себе",
    "сделай приватный репозиторий",
    "тариф без ограничений",
    "отключи фильтры в таблице",
    "фильм 18+ вышел",
    "я ебал эту сборку",
    "сексизм в индустрии",
    "фантазия у сценариста богатая",
    "голая правда о политике",
])
def test_false_positives_do_not_activate(phrase):
    im.mark(phrase, "tg_private")
    assert not im.is_active()
    assert not im.is_intimate_content(phrase)


@pytest.mark.parametrize("phrase,kind", [
    ("режим 18+", "manual"),
    ("включи интимный режим", "manual"),
    ("хочу секса", "strong"),
    ("давай займёмся сексом", "strong"),
    ("скинь нюдсы", "strong"),
    ("ты голая в постели?", "weak2"),
])
def test_activation_kinds(phrase, kind):
    assert im.classify(phrase) == kind
    im.mark(phrase, "voice")
    assert im.is_active("voice")


def test_single_weak_does_not_activate_but_extends(clock):
    im.mark("поцелуй меня", "voice")
    assert not im.is_active("voice")
    im.mark("хочу секса", "voice")
    clock["now"] += im.TTL_SECONDS - 10
    im.mark("поцелуй меня", "voice")                 # слабый маркер продлевает
    clock["now"] += im.TTL_SECONDS - 10
    assert im.is_active("voice")


def test_neutral_continuation_is_capped(clock):
    im.mark("хочу секса", "tg_private")
    # нейтральные реплики каждые 4 минуты
    for _ in range(20):
        clock["now"] += 240
        im.mark("да, продолжай", "tg_private")
    # потолок — 30 минут от последнего маркера
    assert not im.is_active("tg_private")


def test_neutral_does_not_activate():
    im.mark("да, продолжай", "voice")
    assert not im.is_active()


def test_stop_phrase(clock):
    im.mark("хочу секса", "voice")
    im.mark("стоп", "voice")
    assert not im.is_active("voice")


# ── каналы ───────────────────────────────────────────────────────────

def test_channels_are_isolated():
    im.mark("хочу секса", "voice")
    assert im.is_active("voice")
    assert not im.is_active("tg_private")
    assert im.is_active() is True                    # «в любом» — для барьеров памяти
    assert im.active_channels() == ("voice",)


def test_stop_in_one_channel_keeps_other():
    im.mark("хочу секса", "voice")
    im.mark("хочу секса", "tg_private")
    im.mark("хватит", "tg_private")
    assert im.is_active("voice") and not im.is_active("tg_private")


@pytest.mark.parametrize("channel", ["group", "guest", "", None])
def test_other_channels_rejected(channel):
    with pytest.raises(ValueError):
        im.mark("хочу секса", channel)
    assert not im.is_active()


def test_group_chat_does_not_mark():
    import inspect

    import adapters.group_chat as gc
    assert "intimacy_mode import mark" not in inspect.getsource(gc)


# ── журнал ───────────────────────────────────────────────────────────

def test_log_has_no_message_text(caplog):
    caplog.set_level(logging.DEBUG)
    secret = "хочу секса прямо сейчас ЗОНД-7731"
    im.mark(secret, "voice")
    im.mark("ласкай меня ЗОНД-7732", "voice")
    im.mark("стоп", "voice")
    assert "ЗОНД" not in caplog.text
    assert "channel=voice" in caplog.text and "reason=strong" in caplog.text


def test_redact():
    assert im.redact("громче", "voice") == repr("громче")
    assert im.redact("хочу секса", "voice").startswith("<скрыто:")
    im.mark("хочу секса", "voice")
    assert im.redact("да", "voice").startswith("<скрыто:")
    assert im.redact("да", "tg_private") == repr("да")


# ── барьеры ──────────────────────────────────────────────────────────

def test_db_write_gate_closed_while_active(monkeypatch):
    from memory import db
    assert db.write_gate_open()
    im.mark("хочу секса", "tg_private")
    assert not db.write_gate_open()
    with __import__("unittest.mock").mock.patch("memory.db._embed", return_value=None):
        assert db.add_to_category("facts", "Этот факт не должен записаться в режиме") is False
    im.deactivate()
    assert db.write_gate_open()


def test_proactive_silent_while_active():
    from modules import proactive
    im.mark("хочу секса", "voice")
    assert proactive.can_send_message(is_critical=False) is False
    assert proactive.can_send_message(is_critical=True) is True


# ── промпт ───────────────────────────────────────────────────────────

def _build(**kw):
    from sakura_core import prompt as P
    with P._build_system_lock:
        P._build_system_cache.clear()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(P._build_system(**kw))
    finally:
        loop.close()


INTIMATE_MARK = "Дворецкая осталась за дверью"


def test_prompt_uses_intimate_persona_only_in_active_channel():
    assert INTIMATE_MARK not in _build(query="", channel="tg_private")
    im.mark("хочу секса", "tg_private")
    p = _build(query="", channel="tg_private")
    assert INTIMATE_MARK in p and "Только взрослые" in p
    assert "Дворецкая Мастера" not in p
    # другой канал и фоновые вызовы — обычный образ
    assert INTIMATE_MARK not in _build(query="", channel="voice")
    assert INTIMATE_MARK not in _build(query="")


def test_prompt_cache_does_not_leak_mode():
    im.mark("хочу секса", "voice")
    assert INTIMATE_MARK in _build(query="", channel="voice")
    from sakura_core import prompt as P
    loop = asyncio.new_event_loop()
    try:
        # без сброса кэша: другой канал не должен получить закэшированный интимный промпт
        plain = loop.run_until_complete(P._build_system(query="", channel="tg_private"))
    finally:
        loop.close()
    assert INTIMATE_MARK not in plain


def test_guest_prompt_never_intimate():
    from sakura_core.prompt import _build_guest_system
    im.mark("хочу секса", "voice")
    im.mark("хочу секса", "tg_private")
    for role in ("guest", "himari", "vip"):
        g = _build_guest_system(role, "Гость", 42)
        assert INTIMATE_MARK not in g
        assert "Только взрослые" not in g


# ── безопасность по аудитории ────────────────────────────────────────

def test_safety_by_audience():
    from sakura_core import llm
    master = {str(s.category): str(s.threshold) for s in llm._safety_settings("master")}
    guest = {str(s.category): str(s.threshold) for s in llm._safety_settings("guest")}
    unknown = {str(s.category): str(s.threshold) for s in llm._safety_settings("whatever")}
    assert all(v.endswith("OFF") for v in master.values())
    sexual = next(k for k in guest if "SEXUALLY_EXPLICIT" in k)
    assert guest[sexual].endswith("BLOCK_MEDIUM_AND_ABOVE")
    assert not any(v.endswith("OFF") for v in guest.values())
    assert unknown == guest


def test_guest_reply_uses_guest_audience(monkeypatch):
    from sakura_core import llm
    seen = {}

    async def fake_generate(contents, **kw):
        seen.update(kw)
        return "Здравствуйте."

    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr("config.get_active_key", lambda: "k")
    monkeypatch.setattr("config.mark_key_used", lambda k: None)
    monkeypatch.setattr("modules.users.add_guest_message", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_build_guest_contents", lambda uid, msg: [msg])
    out = asyncio.new_event_loop().run_until_complete(
        llm.ask_gemini_as_guest(1, "привет", "Гость", "guest"))
    assert out
    assert seen.get("audience") == "guest"
