"""feat/reply-kinds: reply для всех видов ответов.

{"type": "reply", "text", "kind": llm|ack|template|error|proactive,
 "turn_id", "ts"} — устройству-источнику, proactive — всем master-устройствам;
контракт результата команды {ok, status, detail}: «Готово» только при
status=done, иначе «Не получилось: <detail>» (kind=error); vision_request.

Run: python -m pytest tests/test_reply_kinds.py -q
"""

import asyncio
import base64
import logging
from functools import partial
from unittest.mock import AsyncMock

import pytest

import adapters.ws as wh
import config
import modules.acks as acks
import modules.state as st
import modules.tts_cache as tts_cache
import modules.tts_server as tts
import sakura_core.bridge as br
import sakura_core.ws_protocol as wp
from sakura_core import vision_request, voice_turns
from sakura_core.router import Decision
from tests.test_turn_end import FakeWS, _data, _mk_ctx, _setup

MASTER, MASTER2, GUEST = "laptop", "pc", "phone"     # conftest: MASTER_DEVICES=laptop,pc


def replies(ws):
    return [m for m in ws.sent if m.get("type") == "reply"]


def kinds(ws):
    return [m["kind"] for m in replies(ws)]


@pytest.fixture
def devices(monkeypatch):
    """Три подключённых устройства, синтез без звука, свежие ходы."""
    ws = {d: FakeWS() for d in (MASTER, MASTER2, GUEST)}
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    st.connected_devices.update(ws)
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})

    async def _synth(text, websocket, device_id, emotion="спокойная"):
        return 1
    monkeypatch.setattr(tts, "_synthesize_and_stream", _synth)
    yield ws
    st.connected_devices.clear()
    st.connected_devices.update(saved)


# ── форма и адресаты ───────────────────────────────────────────────

def test_spoken_template_reply_shape_and_order(devices):
    ws = devices[MASTER]
    asyncio.run(tts.stream_tts_to_device("[ТОН: тепло] Хорошо, отменила.", ws, MASTER, literal=True))
    (r,) = replies(ws)
    assert r["kind"] == "template" and r["text"] == "Хорошо, отменила."
    assert isinstance(r["ts"], float) and r["device_id"] == MASTER
    kinds_ = [m["type"] for m in ws.sent]
    assert kinds_.index("reply") < kinds_.index("tts_end")


def test_reply_kind_none_sends_no_reply(devices):
    asyncio.run(tts.stream_tts_to_device("Текст.", devices[MASTER], MASTER, reply_kind=None))
    assert replies(devices[MASTER]) == []


def test_turn_id_in_reply_inside_turn(devices):
    async def _go():
        t = voice_turns.start(MASTER, devices[MASTER], lambda: tts.stream_tts_to_device(
            "Готово.", devices[MASTER], MASTER, literal=True))
        await t.task
        return t
    t = asyncio.run(_go())
    (r,) = replies(devices[MASTER])
    assert r["turn_id"] == t.turn_id


def test_non_master_source_gets_no_reply(devices):
    asyncio.run(tts.stream_tts_to_device("Привет.", devices[GUEST], GUEST, literal=True))
    assert replies(devices[GUEST]) == []


def test_proactive_goes_to_all_masters_speech_to_source(devices):
    asyncio.run(tts.stream_tts_to_device("Через 10 минут созвон.", devices[MASTER], MASTER,
                                         literal=True, reply_kind="proactive"))
    for d in (MASTER, MASTER2):
        assert kinds(devices[d]) == ["proactive"], d
        assert replies(devices[d])[0]["text"] == "Через 10 минут созвон."
    assert replies(devices[GUEST]) == []
    assert [m["type"] for m in devices[MASTER2].sent] == ["reply"], "звук — только источнику"


def test_unknown_kind_falls_back_to_template(devices):
    asyncio.run(voice_turns.send_reply(devices[MASTER], MASTER, "x", kind="weird"))
    assert kinds(devices[MASTER]) == ["template"]


# ── голосовой ход: llm, template, ack ──────────────────────────────

def _voice_env(monkeypatch, ws, fast):
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    monkeypatch.setattr(br, "v3_fast_path", fast)


def test_registry_fast_path_reply_is_template(devices, monkeypatch):
    async def _fast(text, *, speak, **kw):
        await speak("Громкость 70 процентов.")
        return True
    _voice_env(monkeypatch, devices[MASTER], _fast)
    asyncio.run(wh.handle_voice_command(None, _data("громкость 70"), _mk_ctx(AsyncMock())))
    assert kinds(devices[MASTER]) == ["template"]


def test_resolve_reply_is_llm(devices, monkeypatch):
    async def _fast(text, *, resolve_reply, **kw):
        await resolve_reply(object())
        return True
    _voice_env(monkeypatch, devices[MASTER], _fast)

    async def _resolve(r, *, deliver, **kw):
        await deliver("Вы сегодня молодец.")
    monkeypatch.setattr(br, "resolve_conv_reply", _resolve)
    asyncio.run(wh.handle_voice_command(None, _data("похвали меня"), _mk_ctx(AsyncMock())))
    assert kinds(devices[MASTER]) == ["llm"]


def test_tg_voice_trigger_done_is_ack(devices, monkeypatch):
    async def _fast(text, **kw):
        return False
    _voice_env(monkeypatch, devices[MASTER], _fast)
    monkeypatch.setattr(wh, "_has_tg_trigger", lambda t: True)
    monkeypatch.setattr(wh, "_strip_payload_words", lambda t: "привет")
    monkeypatch.setattr(wh, "_voice_to_tg", AsyncMock())
    asyncio.run(wh.handle_voice_command(None, _data("отправь в телеграм привет"),
                                        _mk_ctx(AsyncMock())))
    assert [(r["kind"], r["text"]) for r in replies(devices[MASTER])] == [("ack", "Готово, Мастер.")]


def test_streamed_llm_answer_is_llm(devices, monkeypatch):
    """Потоковый голосовой ответ (ask_gemini_voice) — kind=llm."""
    from tests import test_voice_turns as tv
    import sakura_core.llm as llm
    import memory.memory as mem
    import modules.web_search as web_search
    import modules.mood_broadcast as mood_broadcast
    import adapters.voice as voice_mod
    _setup(monkeypatch, devices[MASTER], decision=Decision(None, "conversation"))
    monkeypatch.setattr(llm, "stream_tokens", tv._slow_tokens)
    monkeypatch.setattr(voice_mod, "_live_synthesize", tv._fake_live)
    monkeypatch.setattr(voice_mod, "_make_audio_sender", tts._make_audio_sender)
    monkeypatch.setattr(config, "get_active_key", lambda: "k")
    monkeypatch.setattr(config, "mark_key_used", lambda k: None)

    async def _bs(query="", profile="full"):
        return "s"
    monkeypatch.setattr(llm, "_build_system", _bs)
    monkeypatch.setattr(llm, "_build_contents", lambda *a, **k: [])
    monkeypatch.setattr(web_search, "needs_search", lambda t: False)
    monkeypatch.setattr(mem, "add_to_history", lambda r, t: None)
    monkeypatch.setattr(mood_broadcast, "broadcast_mood_after_reply", AsyncMock())
    asyncio.run(llm.ask_gemini_voice("расскажи", websocket=devices[MASTER], device_id=MASTER))
    (r,) = replies(devices[MASTER])
    assert r["kind"] == "llm" and r["text"].startswith("Это первое предложение")


# ── подтверждения и контракт результата команды ───────────────────

@pytest.fixture
def ack_env(devices, monkeypatch):
    monkeypatch.setattr(acks, "_pending", {})
    monkeypatch.setattr(acks, "_armed_at", {})
    monkeypatch.setattr(acks, "_speak_locks", {})
    monkeypatch.setattr(acks, "_last", {})
    monkeypatch.setattr(config, "ACKS_ENABLED", True)
    monkeypatch.setattr(config, "ACK_WIT_PROB", 0.0)
    monkeypatch.setattr(config, "ACK_PENDING_S", 5.0)

    async def _pcm(text):
        return b"\x01\x00" * 480, "память"
    monkeypatch.setattr(tts_cache, "get_pcm", _pcm)
    return devices


def _ack(ws, cmd, action="music.next", **result):
    async def _go():
        acks.arm(cmd, ws=ws, device_id=MASTER, action=action)
        await acks.on_result(cmd, **result)
    asyncio.run(_go())


@pytest.mark.parametrize("result,kind,text", [
    ({"ok": True, "detail": "", "status": "done"}, "ack", None),
    ({"ok": True, "detail": "нужно подтверждение", "status": "noop"}, "error",
     "Не получилось: нужно подтверждение."),
    ({"ok": False, "detail": "микрофон не найден", "status": "unsupported"}, "error",
     "Не получилось: микрофон не найден."),
    ({"ok": False, "detail": "", "status": "failed"}, "error", "Не получилось."),
    ({"ok": True, "detail": ""}, "ack", None),                       # старый агент без status
    ({"ok": False, "detail": "плеер не отвечает"}, "error", "Не получилось: плеер не отвечает."),
])
def test_ack_kinds_and_status_contract(ack_env, result, kind, text):
    ws = ack_env[MASTER]
    _ack(ws, "c1", **result)
    (r,) = replies(ws)
    assert r["kind"] == kind
    if text:
        assert r["text"] == text
    else:
        assert r["text"] in ("Включаю.", "Готово.")


def test_ok_true_but_status_noop_never_says_done(ack_env):
    ws = ack_env[MASTER]
    _ack(ws, "c2", ok=True, detail="", status="noop")
    assert replies(ws)[0]["text"] == "Не получилось."
    assert "Готово" not in replies(ws)[0]["text"]


def test_pending_phrase_is_ack(ack_env, monkeypatch):
    monkeypatch.setattr(config, "ACK_PENDING_S", 0.01)
    ws = ack_env[MASTER]

    async def _go():
        acks.arm("c3", ws=ws, device_id=MASTER, action="music.next")
        await asyncio.sleep(0.1)
    asyncio.run(_go())
    assert [(r["kind"], r["text"]) for r in replies(ws)] == [("ack", "Выполняю.")]


def _result_ctx():
    return {"ask_gemini": AsyncMock(return_value="LLM-ответ"), "bot": AsyncMock(),
            "_resolve_command_status": lambda *a: None}


def test_unarmed_voice_command_failure_spoken_as_error(ack_env, monkeypatch):
    """followup=llm, ход голосовой, status=failed → «Не получилось», без LLM."""
    ws = ack_env[MASTER]
    ctx = _result_ctx()

    async def _go():
        async def _turn():
            st._pending_commands["c4"] = {"action": "music.now_playing", "device": MASTER,
                                          "ts": 0.0, "status": "sent",
                                          "turn": voice_turns.current()}
        t = voice_turns.start(MASTER, ws, _turn)
        await t.task
        await wp.handle_command_result(None, {
            "type": "command_result", "id": "c4", "device_id": MASTER, "ok": False,
            "status": "failed", "detail": "Яндекс Музыка не запущена",
            "music": {"action": "music.now_playing"}}, ctx)
        return t
    monkeypatch.setattr(st, "_pending_commands", {})
    t = asyncio.run(_go())
    (r,) = replies(ws)
    assert (r["kind"], r["text"]) == ("error", "Не получилось: Яндекс Музыка не запущена.")
    assert r["turn_id"] == t.turn_id
    ctx["ask_gemini"].assert_not_awaited()


def test_unarmed_done_result_continues_normally(ack_env, monkeypatch):
    ws = ack_env[MASTER]
    ctx = _result_ctx()
    monkeypatch.setattr(st, "_pending_commands", {})

    async def _go():
        async def _turn():
            st._pending_commands["c5"] = {"action": "x", "device": MASTER, "ts": 0.0,
                                          "status": "sent", "turn": voice_turns.current()}
        await voice_turns.start(MASTER, ws, _turn).task
        await wp.handle_command_result(None, {
            "type": "command_result", "id": "c5", "device_id": MASTER, "ok": True,
            "status": "done", "detail": "ok"}, ctx)
    asyncio.run(_go())
    assert [r for r in replies(ws) if r["kind"] == "error"] == []


# ── проактивные пути ───────────────────────────────────────────────

def test_kettle_ready_is_proactive_to_all_masters(devices):
    ctx = {"ask_gemini": AsyncMock(return_value="Чай готов."), "bot": AsyncMock()}
    asyncio.run(wp.handle_kettle_ready(None, {"device_id": MASTER, "temp": 100}, ctx))
    assert kinds(devices[MASTER]) == ["proactive"] and kinds(devices[MASTER2]) == ["proactive"]
    assert kinds(devices[GUEST]) == []


def test_reminder_callback_is_proactive(devices):
    from sakura_core.callbacks import make_reminder_cb

    async def _go():
        cb = await make_reminder_cb(lambda: (devices[MASTER], MASTER),
                                    tts.stream_tts_to_device, AsyncMock(), lambda: "спокойная")
        await cb("Напоминаю: позвонить маме.")
    asyncio.run(_go())
    assert kinds(devices[MASTER]) == ["proactive"] and kinds(devices[MASTER2]) == ["proactive"]


def test_achievement_telegram_only_also_replies(devices):
    from sakura_core.callbacks import make_achievement_cb

    async def _go():
        cb = await make_achievement_cb(1, AsyncMock(), lambda **k: None)
        await cb("Hades", {"name": "Побег"})
    asyncio.run(_go())
    assert replies(devices[MASTER2])[0]["text"] == "Выбито достижение: Побег (Hades)."
    assert kinds(devices[MASTER]) == ["proactive"]


def test_proactive_loop_helper_broadcasts(devices):
    from sakura_core.proactive import _reply_proactive
    asyncio.run(_reply_proactive("Через 30 минут: встреча."))
    assert kinds(devices[MASTER]) == kinds(devices[MASTER2]) == ["proactive"]


def test_urgent_notification_is_proactive(devices, monkeypatch):
    import modules.notification_tracker as nt
    from types import SimpleNamespace
    monkeypatch.setattr(wp, "add_notification", lambda *a: SimpleNamespace(urgent=True))
    ctx = {"ask_gemini": AsyncMock(return_value="Срочное письмо от банка."),
           "_get_active_ws": lambda: (devices[MASTER], MASTER)}
    asyncio.run(wp.handle_notification(None, {"source": "mail", "title": "Банк", "body": "x"}, ctx))
    assert kinds(devices[MASTER]) == ["proactive"] and kinds(devices[MASTER2]) == ["proactive"]


def test_briefing_gets_proactive_speech(devices, monkeypatch):
    seen = {}

    async def _brief(device_id, websocket, ask, stream_fn, **kw):
        seen["fn"] = stream_fn
    monkeypatch.setattr(wp, "run_briefing", _brief)
    monkeypatch.setattr(wp, "should_brief", lambda: True)
    monkeypatch.setattr(wp, "should_greet_device", lambda d: False)
    monkeypatch.setattr(wp, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(wp, "ps_update", lambda *a, **k: None)

    async def _go():
        await wp.handle_register(devices[MASTER], {"device_id": MASTER},
                                 {"ask_gemini": AsyncMock(), "bot": AsyncMock()})
        await asyncio.sleep(0.01)
    asyncio.run(_go())
    fn = seen["fn"]
    assert isinstance(fn, partial) and fn.keywords == {"reply_kind": "proactive"}


# ── vision_request ─────────────────────────────────────────────────

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _vreq(ws, device=MASTER, image=None, question="Что тут за ошибка?"):
    data = {"type": "vision_request", "request_id": "v1", "device_id": device,
            "image": base64.b64encode(JPEG).decode() if image is None else image,
            "question": question}
    asyncio.run(vision_request.handle(ws, data))
    return ws.sent[-1]


def test_vision_request_answers_with_reply(monkeypatch, caplog):
    import sakura_core.llm as llm
    seen = {}

    async def _gen(contents, **kw):
        seen["mime"] = contents[0].inline_data.mime_type
        seen["chain"] = kw.get("chain")
        seen["prompt"] = contents[1].text
        return "В окне ошибка 404: страница не найдена."
    monkeypatch.setattr(llm, "generate", _gen)
    caplog.set_level(logging.INFO)
    r = _vreq(FakeWS())
    assert r == {"type": "reply", "request_id": "v1", "device_id": MASTER,
                 "text": "В окне ошибка 404: страница не найдена.", "kind": "llm", "ts": r["ts"]}
    assert seen["mime"] == "image/jpeg" and seen["chain"] == config.VISION_MODEL_CHAIN
    assert "Что тут за ошибка?" in seen["prompt"]
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert base64.b64encode(JPEG).decode()[:16] not in logged, "кадр попал в лог"
    assert "Что тут за ошибка" not in logged, "вопрос попал в лог"


@pytest.mark.parametrize("device,image,code", [
    (GUEST, None, "not_master"),
    (MASTER, "не base64!", "bad_request"),
    (MASTER, base64.b64encode(b"GIF89a....").decode(), "bad_request"),
    (MASTER, "A" * (vision_request.MAX_B64 + 4), "bad_request"),
    (MASTER, "", "bad_request"),
])
def test_vision_request_errors(device, image, code):
    r = _vreq(FakeWS(), device=device, image=image)
    assert r["type"] == "error" and r["code"] == code and r["request_id"] == "v1"


def test_vision_request_model_failure(monkeypatch):
    import sakura_core.llm as llm

    async def _boom(*a, **k):
        raise RuntimeError("503")
    monkeypatch.setattr(llm, "generate", _boom)
    r = _vreq(FakeWS())
    assert r["type"] == "error" and r["code"] == "internal"
