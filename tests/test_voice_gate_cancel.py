"""fix/voice-gate-cancel: вердикт «команда» снимает голосовой prefetch сразу.

Раньше v3_fast_path исполнял и озвучивал команду, а prefetch снимался
только после возврата; шлюз VoiceGate открывался по таймауту и стрим
ответа LLM звучал поверх ответа команды. Теперь on_command зовётся до
исполнения и озвучки.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import adapters.voice as voice_mod
import adapters.ws as wh
import config
import modules.tts_server as tts
import sakura_core.bridge as br
from sakura_core.router import Decision
from tests.test_turn_end import FakeWS, _FakeRouter, _data, _mk_ask_voice, _mk_ctx, _setup

ROOT = Path(__file__).resolve().parent.parent


def _track_prefetch_audio(monkeypatch, events):
    """Пакеты prefetch-стрима (stream_llm_to_tts → _live_synthesize)."""
    async def _fake_live(text, emotion, on_packet, label=""):
        events.append(("prefetch_chunk", time.monotonic()))
        await on_packet(b"AUDIO")
        return 1
    monkeypatch.setattr(voice_mod, "_live_synthesize", _fake_live)


def test_command_cancels_prefetch_before_long_speak(monkeypatch):
    """«Команда» + озвучка 3с + шлюз 0.2с → prefetch снят до speak,
    ни одного чанка prefetch в TTS."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision("vps.feeling", "llm"))
    monkeypatch.setattr(config, "VOICE_GATE_WAIT_S", 0.2)

    async def _exec(decision, **kw):
        return (True, ("Чувствую себя спокойно.", True))
    monkeypatch.setattr(br, "execute_decision", _exec)

    events = []
    _track_prefetch_audio(monkeypatch, events)

    async def _slow_speak(text, websocket, device_id, emotion="спокойная"):
        events.append(("speak_start", time.monotonic()))
        await asyncio.sleep(3.0)
        return 1
    monkeypatch.setattr(tts, "_synthesize_and_stream", _slow_speak)

    outcome = {}
    real_ask = _mk_ask_voice(outcome)

    async def ask_voice(**kw):
        try:
            await real_ask(**kw)
        finally:
            events.append(("prefetch_done", time.monotonic()))

    asyncio.run(wh.handle_voice_command(None, _data("как дела"), _mk_ctx(ask_voice)))

    kinds = [k for k, _ in events]
    assert outcome.get("cancelled"), outcome
    assert "prefetch_chunk" not in kinds, events
    assert kinds.index("prefetch_done") < kinds.index("speak_start"), events
    assert len(ws.tts_ends()) == 1, ws.sent


def test_conversation_keeps_prefetch_stream(monkeypatch):
    """«Не команда» → поведение прежнее: буфер prefetch уходит в TTS."""
    ws = FakeWS()
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    events = []
    _track_prefetch_audio(monkeypatch, events)
    outcome = {}

    asyncio.run(wh.handle_voice_command(
        None, _data("расскажи что-нибудь"), _mk_ctx(_mk_ask_voice(outcome))))

    assert outcome.get("completed"), outcome
    assert not outcome.get("cancelled")
    assert [k for k, _ in events].count("prefetch_chunk") >= 1
    assert len(ws.tts_ends()) == 1, ws.sent


def _run_fast_path(monkeypatch, decision, executed):
    order = []
    monkeypatch.setattr(br, "get_router", lambda: _FakeRouter(decision))

    async def _exec(decision, **kw):
        order.append("execute")
        return (executed, None)
    monkeypatch.setattr(br, "execute_decision", _exec)

    async def _on_command():
        order.append("on_command")

    result = asyncio.run(br.v3_fast_path(
        "текст", data={}, device_ws=None, device_id="laptop",
        register_command=None, speak=AsyncMock(), on_command=_on_command))
    return result, order


def test_on_command_called_before_execute(monkeypatch):
    result, order = _run_fast_path(monkeypatch, Decision("music.next", "llm"), True)
    assert result is True
    assert order == ["on_command", "execute"]


def test_on_command_not_called_for_conversation(monkeypatch):
    result, order = _run_fast_path(monkeypatch, Decision(None, "conversation"), False)
    assert result is False
    assert "on_command" not in order


def test_gate_wait_default_and_config(monkeypatch):
    """VoiceGate берёт таймаут из config.VOICE_GATE_WAIT_S на создании."""
    monkeypatch.setattr(config, "VOICE_GATE_WAIT_S", 0.3)
    assert voice_mod.VoiceGate().WAIT_S == 0.3


def _wait_in_subprocess(env_value):
    env = {k: v for k, v in os.environ.items() if k != "VOICE_GATE_WAIT_S"}
    if env_value is not None:
        env["VOICE_GATE_WAIT_S"] = env_value
    out = subprocess.run(
        [sys.executable, "-c",
         "import config, adapters.voice as v; "
         "print(config.VOICE_GATE_WAIT_S, v.VoiceGate().WAIT_S)"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=True)
    return out.stdout.strip().splitlines()[-1]


def test_env_changes_gate_wait():
    assert _wait_in_subprocess("2.5") == "2.5 2.5"


def test_gate_wait_default_is_4s():
    assert _wait_in_subprocess(None) == "4.0 4.0"
