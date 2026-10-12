"""perf/voice-2: хронометраж [turn], предсинтез с удержанием звука, ранний
шлюз, параллельная отправка, предел длины ответа, лёгкий профиль промпта.

Голосовой ход — настоящий (voice_turns → handle_voice_command →
stream_llm_to_tts), подменены сеть LLM/TTS и роутер с заданными задержками.

Run: python -m pytest tests/test_voice_perf.py -q
"""

import asyncio
import logging
import time

import pytest

import adapters.voice as voice_mod
import adapters.ws as wh
import config
import modules.tts_server as tts
import sakura_core.bridge as br
import sakura_core.llm as llm
from sakura_core import early_gate, turn_timing, voice_turns
from sakura_core.router import Decision
from tests.test_turn_end import FakeWS, _data, _mk_ctx, _setup

DEV = "laptop"


class Env:
    """Задержки (с): вердикт роутера, первое предложение LLM, конец стрима,
    первый пакет TTS от старта стадии."""

    def __init__(self, verdict=0.3, first=0.1, done=0.15, tts_lat=0.1,
                 sentences=("Привет, рада слышать.", "Всё хорошо, спасибо."),
                 decision=None):
        self.verdict, self.first, self.done, self.tts_lat = verdict, first, done, tts_lat
        self.sentences = sentences
        self.decision = decision or Decision(None, "conversation")
        self.t0 = 0.0
        self.synth: list[tuple[float, str]] = []
        self.sent: list[float] = []

    def rel(self, t):
        return t - self.t0


@pytest.fixture
def env(monkeypatch):
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(turn_timing, "_samples", [])
    monkeypatch.setattr(config, "VOICE_PRESYNTH", True)
    monkeypatch.setattr(config, "VOICE_EARLY_GATE", True)
    monkeypatch.setattr(config, "VOICE_GATE_WAIT_S", 5.0)
    e = Env()

    class Router:
        class session:
            pending = None

        async def route(self, text, context=None, *, source=None, on_llm=None):
            if on_llm is not None:
                on_llm()
            await asyncio.sleep(max(0.0, e.verdict - (time.monotonic() - e.t0)))
            return e.decision
    monkeypatch.setattr(br, "get_router", lambda: Router())

    async def _tokens(contents, **kw):
        await asyncio.sleep(max(0.0, e.first - (time.monotonic() - e.t0)))
        yield e.sentences[0] + " "
        for s in e.sentences[1:]:
            gap = (e.done - e.first) / max(1, len(e.sentences) - 1)
            await asyncio.sleep(gap)
            yield s + " "
    monkeypatch.setattr(llm, "stream_tokens", _tokens)

    async def _live(text, emotion, on_packet, label=""):
        e.synth.append((time.monotonic(), text))
        await asyncio.sleep(e.tts_lat)
        await on_packet(b"PCM")
        return 1
    monkeypatch.setattr(voice_mod, "_live_synthesize", _live)

    async def _preferred(text, emotion, on_packet, label="", synth=None):
        return await (synth or _live)(text, emotion, on_packet, label=label)
    monkeypatch.setattr(voice_mod, "_live_synthesize_preferred", _preferred)

    def _sender(websocket, device_id):
        real = tts._make_audio_sender(websocket, device_id)

        async def send(data):
            e.sent.append(time.monotonic())
            await real(data)
        return send
    monkeypatch.setattr(voice_mod, "_make_audio_sender", _sender)

    async def ask_voice(**kw):
        return await voice_mod.stream_llm_to_tts(
            contents="тест", system="", websocket=kw.get("websocket"),
            device_id=kw.get("device_id") or DEV, max_tokens=60, timeout=6.0,
            gate=kw.get("gate"), received_at=kw.get("received_at"))
    e.ctx = _mk_ctx(ask_voice)
    e.ws = ws
    return e


def _turn(e, text):
    async def _go():
        e.t0 = time.monotonic()
        t = voice_turns.start(DEV, e.ws, lambda: wh.handle_voice_command(None, _data(text), e.ctx))
        await asyncio.wait_for(t.task, 10)
        await asyncio.sleep(0.01)
        return t
    return asyncio.run(_go())


# ── хронометраж ────────────────────────────────────────────────────

def test_turn_line_has_all_stages(env, caplog):
    caplog.set_level(logging.INFO, logger="sakura.turn")
    t = _turn(env, "давно не виделись")
    for k in turn_timing.STAGES:
        assert k in t.marks, (k, t.marks)
    m = t.marks
    assert m["first_token"] <= m["llm_done"] <= m["first_audio"] <= m["tts_end"]
    assert m["verdict"] <= m["first_audio"]
    assert t.kind == "conversation"
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[turn] ")]
    assert len(lines) == 1 and t.turn_id in lines[0] and "kind=conversation" in lines[0]
    for k in turn_timing.STAGES:
        assert f" {k}=" in lines[0]


def test_summary_p50_p90():
    samples = [("conversation", {"first_audio": v, "verdict": v / 2}) for v in range(100, 1100, 100)]
    samples.append(("command", {"first_audio": 150.0}))
    out = turn_timing.summary(samples)
    assert out[0].startswith("command n=1 first_audio p50=150 p90=150")
    conv = out[1]
    assert conv.startswith("conversation n=10")
    assert "first_audio p50=550 p90=900" in conv and "verdict p50=275" in conv


def test_summary_loop_logs_hourly(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="sakura.turn")
    monkeypatch.setattr(config, "TURN_STATS_PERIOD_S", 0.05)
    monkeypatch.setattr(turn_timing, "_samples", [("conversation", {"first_audio": 1200.0})])

    async def _go():
        task = asyncio.create_task(turn_timing._summary_loop())
        await asyncio.sleep(0.08)
        task.cancel()
    asyncio.run(_go())
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("[turn] за ") and "first_audio p50=1200" in m for m in msgs), msgs
    assert turn_timing._samples == []


# ── предсинтез с удержанием звука ──────────────────────────────────

def test_presynth_starts_before_verdict_audio_after(env):
    env.verdict, env.first, env.done, env.tts_lat = 0.5, 0.1, 0.15, 0.2
    _turn(env, "давно не виделись")
    first_synth = env.rel(env.synth[0][0])
    first_sent = env.rel(env.sent[0])
    assert first_synth < 0.3, "синтез ждал вердикта"
    assert 0.5 - 0.02 <= first_sent < 0.5 + 0.1, \
        f"звук: {first_sent:.3f}с — должен уйти сразу по вердикту (0.5), а не после синтеза (0.7)"


def test_presynth_off_waits_for_verdict(env, monkeypatch):
    monkeypatch.setattr(config, "VOICE_PRESYNTH", False)
    env.verdict, env.first, env.done, env.tts_lat = 0.5, 0.1, 0.15, 0.2
    _turn(env, "давно не виделись")
    assert env.rel(env.synth[0][0]) >= 0.48
    assert env.rel(env.sent[0]) >= 0.68


def test_command_discards_held_audio(env):
    env.verdict, env.decision = 0.4, Decision("music.next", "llm")

    async def _exec(decision, **kw):
        return (True, None)
    br.execute_decision, saved = _exec, br.execute_decision
    try:
        t = _turn(env, "давно не виделись")
    finally:
        br.execute_decision = saved
    assert env.synth, "предсинтез стартовал"
    assert env.sent == [], "удержанный звук ушёл при команде"
    assert t.kind == "command"


# ── отправка параллельно стриму LLM ────────────────────────────────

def test_first_audio_does_not_wait_for_llm_stream_end(env, monkeypatch):
    monkeypatch.setattr(voice_mod, "SINGLE_MAX_SENTENCES", 0)
    monkeypatch.setattr(config, "VOICE_MAX_CHARS", 0)
    env.verdict, env.first, env.done, env.tts_lat = 0.05, 0.1, 1.0, 0.05
    env.sentences = tuple(f"Предложение номер {i} длинного ответа." for i in range(6))
    t = _turn(env, "давно не виделись")
    assert env.rel(env.sent[0]) < 0.4, "первый звук ждал конца стрима"
    assert t.marks["first_audio"] < t.marks["llm_done"]


# ── ранний шлюз ────────────────────────────────────────────────────

def test_early_gate_question_does_not_wait_for_verdict(env):
    env.verdict, env.first, env.done, env.tts_lat = 1.0, 0.1, 0.15, 0.1
    t = _turn(env, "Как дела?")
    assert env.rel(env.sent[0]) < 0.5, f"звук ждал вердикта: {env.rel(env.sent[0]):.2f}"
    assert "early_gate" in t.flags


@pytest.mark.parametrize("text", ["давно не виделись", "можешь включить свет?"])
def test_no_early_gate_without_question_or_with_command_verb(env, text):
    env.verdict, env.first, env.done, env.tts_lat = 0.6, 0.1, 0.15, 0.1
    t = _turn(env, text)
    assert env.rel(env.sent[0]) >= 0.58
    assert "early_gate" not in t.flags


def test_early_gate_command_verdict_before_audio_is_silent(env):
    """Вопрос, но классификатор сказал «команда» раньше первого звука —
    поток снят, ни одного пакета ответа."""
    env.verdict, env.first, env.tts_lat = 0.15, 0.1, 0.3
    env.decision = Decision("vps.feeling", "llm")

    async def _exec(decision, **kw):
        return (True, None)
    br.execute_decision, saved = _exec, br.execute_decision
    try:
        t = _turn(env, "как ты себя чувствуешь?")
    finally:
        br.execute_decision = saved
    assert env.sent == []
    assert "early_gate" in t.flags and "verdict_after_audio" not in t.flags


def test_early_gate_rules():
    assert early_gate.opens_early("Как дела?")
    assert early_gate.opens_early("почему небо голубое")
    assert early_gate.opens_early("сколько времени?")
    assert not early_gate.opens_early("расскажи анекдот")          # не вопрос
    assert not early_gate.opens_early("включи музыку?")            # глагол реестра
    assert not early_gate.opens_early("а можешь открыть браузер?")  # та же основа
    assert not early_gate.opens_early("не мог бы ты поставить таймер?")
    verbs = early_gate.command_verbs()
    assert {"включи", "открой", "поставь", "перемотай"} <= verbs
    assert not ({"какой", "чай", "громкость", "следующий"} & verbs)


# ── предел длины ответа ────────────────────────────────────────────

def test_voice_max_chars_stops_stream(env, monkeypatch):
    monkeypatch.setattr(config, "VOICE_MAX_CHARS", 120)
    env.sentences = tuple(f"Это предложение номер {i} очень длинного ответа." for i in range(10))
    env.verdict = 0.05

    async def _go():
        env.t0 = time.monotonic()
        return await voice_mod.stream_llm_to_tts(
            contents="x", websocket=env.ws, device_id=DEV, timeout=6.0)
    text, _ = asyncio.run(_go())
    assert len(text) <= 120 and text.endswith("ответа."), (len(text), text)
    assert len(text) > 120 - 50, "отброшено больше одного предложения"


def test_fit_to_limit():
    from adapters.voice import fit_to_limit
    assert fit_to_limit([], "Короткое.", 20) == "Короткое."
    assert fit_to_limit(["Первое."], "Второе.", 15) == "Второе."       # 7+1+7 = 15
    assert fit_to_limit(["Первое."], "Второе длинное.", 15) is None     # не влезло — конец
    cut = fit_to_limit([], "Одно очень длинное предложение без точки внутри", 20)
    assert cut.endswith("…") and len(cut) <= 20
    assert cut[:-1] in "Одно очень длинное предложение" and not cut[:-1].endswith(" ")
    assert cut == "Одно очень длинное…"                                # не посреди слова


# ── лёгкий профиль промпта ─────────────────────────────────────────

def test_light_profile_keeps_persona_drops_context_blocks(monkeypatch, caplog):
    import modules.graph as graph
    import modules.tasks as tasks_mod
    import modules.timeline as timeline
    import sakura_core.prompt as prompt
    called = []

    def _rec(name, size):
        def f(*a, **k):
            called.append(name)
            return f"[{name}] " + "x" * size
        return f
    monkeypatch.setattr(prompt, "get_system_prompt", lambda **k: "ПЕРСОНА САКУРЫ")
    monkeypatch.setattr(graph, "get_graph_context", _rec("graph", 500))
    monkeypatch.setattr(timeline, "get_timeline_context", _rec("timeline", 700))
    monkeypatch.setattr(tasks_mod, "get_tasks_context", _rec("tasks", 300))
    caplog.set_level(logging.INFO, logger="sakura.prompt")

    full = asyncio.run(prompt._build_system(query="как дела", profile="full"))
    assert set(called) == {"graph", "timeline", "tasks"}
    called.clear()
    light = asyncio.run(prompt._build_system(query="как дела", profile="light"))
    assert called == [], "выброшенные блоки не должны собираться"
    assert "ПЕРСОНА САКУРЫ" in light and "ПЕРСОНА САКУРЫ" in full
    assert len(full) - len(light) >= 1500
    sizes = [r.getMessage() for r in caplog.records if "[build_system] блоки:" in r.getMessage()]
    assert sizes and "identity=" in sizes[-1] and "graph=" not in sizes[-1]
    assert "ПЕРСОНА" not in sizes[-1], "в лог — только метки и размеры"


def test_voice_uses_configured_profile(monkeypatch):
    seen = {}

    async def _bs(query="", profile="full", **kw):
        seen["profile"] = profile
        raise RuntimeError("stop")
    monkeypatch.setattr(llm, "_build_system", _bs)
    monkeypatch.setattr(config, "get_active_key", lambda: "k")
    monkeypatch.setattr(config, "VOICE_PROMPT_PROFILE", "light")
    with pytest.raises(RuntimeError):
        asyncio.run(llm.ask_gemini_voice("привет"))
    assert seen["profile"] == "light"


# ── блоки лёгкого профиля по запросу ───────────────────────────────

@pytest.mark.parametrize("query,blocks", [
    ("Что у меня сегодня?", {"tasks"}),
    ("какие задачи на завтра", {"tasks"}),
    ("сколько у меня дел", {"tasks"}),
    ("Напомни про дедлайн", {"tasks"}),
    ("О чём мы говорили вчера?", {"summary"}),
    ("помнишь, на чем остановились?", {"summary"}),
    ("Какие достижения за неделю?", {"timeline", "achievements"}),
    ("подведи итог месяца", {"timeline", "achievements"}),
    ("Продолжим ту тему", {"threads"}),
    ("вернёмся к нашему разговору", {"threads"}),
    ("что у меня на экране", {"screen"}),
    ("Посмотри в окне браузера", {"screen"}),
    ("Как дела?", set()),
    ("расскажи анекдот", set()),
])
def test_light_blocks_on_demand(query, blocks):
    from sakura_core.prompt import light_blocks_for
    assert light_blocks_for(query) == frozenset(blocks), query


@pytest.mark.parametrize("query,label,want", [
    ("какие задачи на сегодня", "tasks", True),
    ("о чём мы говорили в прошлый раз", "summary", True),
    ("что было за неделю", "timeline", True),
    ("продолжим тему", "threads", True),
    ("что на мониторе", "screen", True),
    ("как дела", "tasks", False),
])
def test_light_profile_builds_block_on_demand(monkeypatch, query, label, want):
    import modules.context as context
    import modules.tasks as tasks_mod
    import modules.threads as threads
    import modules.timeline as timeline
    import sakura_core.prompt as prompt
    called = []

    def _rec(name):
        def f(*a, **k):
            called.append(name)
            return f"[{name}]"
        return f
    monkeypatch.setattr(prompt, "get_system_prompt", lambda **k: "ПЕРСОНА")
    monkeypatch.setattr(tasks_mod, "get_tasks_context", _rec("tasks"))
    monkeypatch.setattr(timeline, "get_timeline_context", _rec("timeline"))
    monkeypatch.setattr(threads, "get_threads_context", _rec("threads"))
    monkeypatch.setattr(context, "get_screen_context", _rec("screen"))
    import memory.memory as mem
    monkeypatch.setattr(mem, "load_session_summary", _rec("summary"))
    text = asyncio.run(prompt._build_system(query=query, profile="light"))
    assert (label in called) is want, (query, called)
    assert (f"[{label}]" in text) is want


def test_turn_line_marks_added_blocks(monkeypatch, caplog):
    import sakura_core.prompt as prompt
    monkeypatch.setattr(prompt, "get_system_prompt", lambda **k: "ПЕРСОНА")
    monkeypatch.setattr(voice_turns, "_last", {})
    caplog.set_level(logging.INFO, logger="sakura.turn")

    async def _turn():
        await prompt._build_system(query="какие у меня задачи сегодня", profile="light")
        await prompt._build_system(query="как дела", profile="light")

    async def _go():
        t = voice_turns.start(DEV, FakeWS(), _turn)
        await t.task
        return t
    t = asyncio.run(_go())
    assert t.flags == ["blocks+=tasks"]
    line = turn_timing.line(t)
    assert " blocks+=tasks " in line
