"""Реплей-замер голосового пути на задержках из журнала (perf/voice-2).

Настоящий код хода (handle_voice_command → stream_llm_to_tts) прогоняется
на задержках 20 разговорных ходов прода (journalctl -u sakura, 05–12.10:
только тайминги): вердикт классификатора, первый токен и конец стрима
LLM, задержка TTS от старта стадии до первого пакета. Сеть подменена,
время — настоящее (asyncio.sleep).

    python scripts/voice_bench.py --root /tmp/sakura-p0   # код «до»
    python scripts/voice_bench.py                         # код «после»
    python scripts/voice_bench.py --question              # ранний шлюз
    python scripts/voice_bench.py --acks                  # команда + подтверждение

Ходы без вердикта («—» в журнале: классификатор упал, шлюз открылся по
таймауту 5 с) — роутер отвечает через 6 с при VOICE_GATE_WAIT_S=5.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time

# (метка, вердикт|None, first_token, llm_done, stage1, first_audio) — с
TURNS = [
    ("10-05 21:45", None, 0.94, 0.98, 5.00, 6.11),
    ("10-05 22:41", 3.60, 2.01, 3.60, 3.60, 4.77),
    ("10-07 23:07", 1.12, 1.14, 1.29, 1.28, 2.92),
    ("10-07 23:09", 0.89, 1.58, 1.80, 1.69, 3.42),
    ("10-07 23:09", 4.91, 0.97, 1.09, 4.91, 7.35),
    ("10-07 23:16", 0.85, 1.17, 1.30, 1.26, 2.34),
    ("10-07 23:56", 1.01, 1.32, 1.35, 1.34, 2.29),
    ("10-07 23:58", 0.97, 1.16, 1.33, 1.34, 2.54),
    ("10-07 23:59", 0.90, 0.91, 1.04, 0.98, 2.28),
    ("10-07 23:59", 0.99, 1.01, 1.08, 1.07, 2.17),
    ("10-08 00:00", 0.91, 0.90, 1.01, 0.98, 2.14),
    ("10-08 14:40", 0.97, 0.77, 0.98, 0.98, 2.08),
    ("10-09 14:29", 0.74, 6.08, 6.16, 6.16, 6.78),
    ("10-09 23:31", 0.94, 0.82, 0.89, 0.95, 1.70),
    ("10-12 13:41", None, 3.03, 3.15, 5.01, 5.67),
    ("10-12 13:42", None, 1.03, 1.17, 5.00, 5.62),
    ("10-12 13:44", 2.81, 0.80, 0.83, 2.81, 3.48),
    ("10-12 13:44", 0.84, 4.16, 4.42, 4.42, 5.20),
    ("10-12 16:56", 0.87, 0.73, 0.83, 0.87, 1.50),
    ("10-12 16:56", 1.15, 1.15, 1.15, 1.16, 1.72),
]
GATE_WAIT_S = 5.0
NO_VERDICT_S = 6.0
ANSWER = ("Привет, Мастер, рада тебя слышать.", "У меня всё спокойно, а у тебя?")


def _env(root: str) -> None:
    sys.path.insert(0, root)
    os.chdir(root)
    for k, v in (("MASTER_ID", "1"), ("TELEGRAM_TOKEN", "1:x"), ("GEMINI_KEY_1", "x"),
                 ("WS_SECRET", "bench-secret-0123456789"), ("MASTER_DEVICES", "laptop")):
        os.environ.setdefault(k, v)
    import tempfile
    tmp = tempfile.mkdtemp(prefix="voice_bench_")
    os.environ["MEMORY_DB_PATH"] = os.path.join(tmp, "m.db")
    os.environ["CHAT_DB_PATH"] = os.path.join(tmp, "chat.db")


class _Patch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value, raising=True):
        old = getattr(obj, name, None)
        if raising and not hasattr(obj, name):
            raise AttributeError(name)
        self._undo.append((obj, name, old))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


async def _one(row, question: bool) -> float:
    import adapters.voice as voice_mod
    import adapters.ws as wh
    import config
    import sakura_core.bridge as br
    import sakura_core.llm as llm
    from sakura_core.router import Decision
    from tests.test_turn_end import FakeWS, _data, _mk_ctx, _setup

    label, verdict, first, done, stage1, first_audio = row
    tts_lat = first_audio - stage1
    route_s = verdict if verdict is not None else NO_VERDICT_S
    mp = _Patch()
    ws = FakeWS()
    _setup(mp, ws, decision=Decision(None, "conversation"))
    mp.setattr(config, "VOICE_GATE_WAIT_S", GATE_WAIT_S)
    t = {"t0": 0.0, "sent": None}

    class Router:
        class session:
            pending = None

        async def route(self, text, context=None, *, source=None, on_llm=None):
            if on_llm is not None:
                on_llm()
            await asyncio.sleep(max(0.0, route_s - (time.monotonic() - t["t0"])))
            return Decision(None, "conversation")
    mp.setattr(br, "get_router", lambda: Router())

    async def _tokens(contents, **kw):
        await asyncio.sleep(max(0.0, first - (time.monotonic() - t["t0"])))
        yield ANSWER[0] + " "
        await asyncio.sleep(max(0.0, done - (time.monotonic() - t["t0"])))
        yield ANSWER[1]
    mp.setattr(llm, "stream_tokens", _tokens)

    async def _live(text, emotion, on_packet, label=""):
        await asyncio.sleep(tts_lat)
        await on_packet(b"PCM")
        return 1
    mp.setattr(voice_mod, "_live_synthesize", _live)

    async def _preferred(text, emotion, on_packet, label="", synth=None):
        return await _live(text, emotion, on_packet, label)
    mp.setattr(voice_mod, "_live_synthesize_preferred", _preferred)

    async def _send(data):
        if t["sent"] is None:
            t["sent"] = time.monotonic() - t["t0"]
    mp.setattr(voice_mod, "_make_audio_sender", lambda websocket, device_id: _send)

    async def ask_voice(**kw):
        return await voice_mod.stream_llm_to_tts(
            contents="x", system="", websocket=kw.get("websocket"),
            device_id=kw.get("device_id") or "laptop", max_tokens=60, timeout=12.0,
            gate=kw.get("gate"), received_at=kw.get("received_at"))
    text = "Как дела?" if question else "давно не виделись"
    try:
        t["t0"] = time.monotonic()
        await wh.handle_voice_command(None, _data(text), _mk_ctx(ask_voice))
    finally:
        mp.undo()
    return t["sent"]


async def _ack_one() -> float:
    """Команда реестра (без LLM) → command_result через 65 мс → «Готово»."""
    import config
    import modules.acks as acks
    import modules.tts_cache as tts_cache
    import adapters.ws as wh
    import sakura_core.ws_protocol as wp
    from tests.test_turn_end import FakeWS, _data, _mk_ctx, _setup
    from sakura_core.router import Decision
    import json

    mp = _Patch()
    sent = {"t": None}
    t0 = {"t": 0.0}

    class AgentWS(FakeWS):
        async def send(self, raw):
            msg = json.loads(raw)
            if msg.get("type") == "tts_chunk" and sent["t"] is None:
                sent["t"] = time.monotonic() - t0["t"]
            if msg.get("type") == "command":
                async def _result():
                    await asyncio.sleep(0.065)          # агент исполнил (журнал: 59–71 мс)
                    await wp.handle_command_result(None, {
                        "type": "command_result", "id": msg["id"], "ok": True,
                        "detail": "", "device_id": "laptop"}, ctx)
                asyncio.get_running_loop().create_task(_result())
            await super().send(raw)

    ws = AgentWS()
    _setup(mp, ws, decision=Decision(None, "conversation"))
    ctx = _mk_ctx(None)
    ctx["_register_command"] = wh._register_command
    ctx["_resolve_command_status"] = wh._resolve_command_status
    import sakura_core.bridge as br
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    mp.setattr(br, "get_router", _real_get_router)   # синглтон, как на проде
    mp.setattr(br, "execute_decision", _real_execute)
    mp.setattr(config, "ACKS_ENABLED", True)
    mp.setattr(config, "ACK_WIT_PROB", 0.0)

    async def _pcm(text):
        return b"\x01\x00" * 4800, "память"
    mp.setattr(tts_cache, "get_pcm", _pcm)
    mp.setattr(acks, "_pending", {})
    mp.setattr(acks, "_armed_at", {})
    mp.setattr(acks, "_speak_locks", {})
    import modules.state as st
    st._pending_commands.clear()      # тот же dict, что у adapters.ws
    try:
        t0["t"] = time.monotonic()
        await wh.handle_voice_command(None, _data("следующий трек"), ctx)
        for _ in range(100):
            if sent["t"] is not None:
                break
            await asyncio.sleep(0.01)
    finally:
        mp.undo()
    return sent["t"]


_real_execute = None
_real_get_router = None


def _stats(name, xs):
    xs = sorted(x for x in xs if x is not None)
    p90 = xs[min(len(xs) - 1, round(0.9 * (len(xs) - 1)))]
    print(f"{name}: p50={statistics.median(xs):.2f}с p90={p90:.2f}с "
          f"среднее={statistics.mean(xs):.2f}с n={len(xs)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--question", action="store_true", help="фраза-вопрос (ранний шлюз)")
    ap.add_argument("--acks", action="store_true", help="команда реестра с подтверждением")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    _env(args.root)
    import logging
    logging.basicConfig(level=logging.CRITICAL)
    global _real_execute, _real_get_router
    import sakura_core.bridge as br
    _real_execute = br.execute_decision
    _real_get_router = br.get_router

    if args.acks:
        res = [asyncio.run(_ack_one()) for _ in range(20)]
        _stats("команда → первый звук подтверждения", res)
        return
    res = []
    for row in TURNS:
        r = asyncio.run(_one(row, args.question))
        res.append(r)
        if not args.quiet:
            print(f"{row[0]}  журнал={row[5]:.2f}с  реплей={r:.2f}с")
    _stats("журнал", [r[5] for r in TURNS])
    _stats("реплей", res)


if __name__ == "__main__":
    main()
