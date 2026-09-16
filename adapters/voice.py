"""Голосовой адаптер v3 (этап 4): честный стриминг LLM → TTS.

В v2 stream_llm_to_tts (modules/tts_server.py:563) называется «стримингом»,
но дренирует итератор до конца (asyncio.to_thread _drain) и только потом
зовёт синтез; переменные buf/sentences для посентенсной отдачи объявлены
и не использованы (ruff F841). Бюджет «первый звук 800 мс» при таком коде
недостижим.

Здесь стриминг — основа: предложение готово → сразу в синтез. Стадии
синтезируются параллельно, пакеты уходят на устройство строго по порядку
стадий (обобщение правильного _stream_two_stage из v2 на N стадий).
Примитивы синтеза берутся из v2 как есть (переносятся на этапе 6):
_make_audio_sender, _live_synthesize, _stream_two_stage.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import AsyncIterator, Optional

from sakura_core import budget
from sakura_core import llm as _llm
from modules.tts_server import (
    _make_audio_sender,
    _live_synthesize,
    _stream_two_stage,
)

log = logging.getLogger("sakura.voice")

_SENT_END = re.compile(r"(?<=[.!?…])\s+")
_NL_WS = re.compile(r"\s*\n\s*")
_EMOTION_LINE = re.compile(r"^EMOTION:\s*(.+?)\s*$", re.MULTILINE)


async def iter_sentences(tokens: AsyncIterator[str]) -> AsyncIterator[str]:
    """Ассемблер стрима: токены → готовые предложения.

    Предложение высвобождается сразу, как только встречен разделитель —
    поток не дожидается конца (это и есть честный стриминг).
    """
    buf = ""
    async for tok in tokens:
        buf += tok
        while True:
            m = _SENT_END.search(buf)
            if not m:
                break
            head, buf = buf[: m.end()], buf[m.end():]
            if head.strip():
                yield head.strip()
    if buf.strip():
        yield buf.strip()


async def stream_llm_to_tts(
    contents,
    system: str = "",
    websocket=None,
    device_id=None,
    client=None,
    model: Optional[str] = None,
    max_tokens: int = 200,
    temperature: float = 0.85,
    api_key: Optional[str] = None,
    emotion: str = "спокойная",
    stop=None,
) -> tuple[str, str]:
    """Стриминг LLM→TTS: предложение готово → сразу в синтез.

    Сигнатура совместима с вызовами v2 (main.py ask_gemini_voice): голосовой
    путь идёт через этот адаптер. Возвращает (полный текст, эмоция).
    stop — опциональный callable(): True между пакетами → обрыв озвучки.
    """
    key = _llm.pick_key(api_key)
    if client is None:
        client = _llm.get_client(key)
    t0 = time.monotonic()
    parts: list[str] = []
    queues: list[asyncio.Queue] = []
    producers: list[asyncio.Task] = []
    first_audio_logged = False
    synth_failed = False

    async def _produce(text: str, q: asyncio.Queue, stage: int) -> None:
        try:
            await _live_synthesize(text, emotion, q.put, label=f"стадия {stage}")
        except Exception as e:
            log.error(f"[voice] стадия {stage}: синтез упал: {e}")
            await q.put(e)
        finally:
            await q.put(None)

    def _new_stage(text: str) -> None:
        q: asyncio.Queue = asyncio.Queue()
        queues.append(q)
        producers.append(asyncio.create_task(_produce(text, q, len(queues))))

    async def _drain(q: asyncio.Queue) -> bool:
        """Выкачать стадию на устройство до sentinel-а. True — дочитана."""
        nonlocal first_audio_logged, synth_failed
        while True:
            data = await q.get()
            if data is None:
                return True
            if isinstance(data, Exception):
                synth_failed = True
                return True
            if stop is not None and stop():
                return False
            try:
                await _make_audio_sender(websocket, device_id)(data)
            except Exception as e:
                log.error(f"[voice] отправка пакета: {e}")
                return True
            if not first_audio_logged:
                first_audio_logged = True
                _ms = (time.monotonic() - t0) * 1000
                log.info(f"[voice] первый звук за {_ms:.0f}мс")
                budget.check("voice_first_audio", _ms)


    try:
        tokens = _llm.stream_tokens(
            contents, system=system, model=model, max_tokens=max_tokens,
            temperature=temperature, api_key=key,
        )
        async for sentence in iter_sentences(tokens):
            m = _EMOTION_LINE.match(sentence)
            if m:
                emotion = m.group(1)
                continue
            parts.append(sentence)
            _new_stage(sentence)
    except Exception as e:
        log.error(f"[voice] стрим LLM упал: {e}")

    # Ни одного предложения — фолбэк: обычная генерация → двухстадийный путь v2
    if not parts:
        text = (await _llm.generate(contents, system=system, model=model,
                                    max_tokens=max_tokens, temperature=temperature,
                                    api_key=key)).strip()
        if not text:
            return "", emotion
        clean = text
        for line in text.split("\n"):
            if line.strip().startswith("EMOTION:"):
                emotion = line.strip().replace("EMOTION:", "").strip()
        clean = _NL_WS.sub(" ", _EMOTION_LINE.sub("", clean)).strip()
        first, _, rest = clean.partition(". ")
        if rest.strip():
            await _stream_two_stage(first.strip() + ".", rest.strip(), websocket,
                                    device_id, emotion, t0, stop=stop)
        elif websocket:
            await _live_synthesize(clean, emotion,
                                   _make_audio_sender(websocket, device_id))
        return clean, emotion

    # Пакеты уходят строго по порядку стадий
    for q in queues:
        if not await _drain(q):
            break

    for t in producers:
        if not t.done():
            t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"[voice] продюсер: {e}")

    if not synth_failed:
        budget.timed("voice_total", t0)
    full_text = " ".join(parts)
    log.info(f"[voice] ответ за {time.monotonic() - t0:.1f}с, {len(full_text)} симв")
    return full_text, emotion


# ── WebSocket-команды (перенесено из main.py, commit 6) ──────────────────

import uuid

from modules.state import _pending_commands, connected_devices


def _cleanup_pending_commands():
    """Удаляет команды старше 5 минут."""
    now = time.monotonic()
    expired = [k for k, v in _pending_commands.items() if now - v["ts"] > 300]
    for k in expired:
        del _pending_commands[k]


def _register_command(action: str, device: str) -> str:
    """Регистрирует команду и возвращает её id."""
    cmd_id = uuid.uuid4().hex[:12]
    _pending_commands[cmd_id] = {
        "action": action,
        "device": device,
        "ts": time.monotonic(),
        "status": "sent",
    }
    _cleanup_pending_commands()
    return cmd_id


def _resolve_command_status(device: str, ok: bool, detail: str) -> str:
    """Находит последнюю pending-команду (status==sent) для устройства, обновляет статус."""
    now = time.monotonic()
    best_id = None
    best_ts = -1
    for cmd_id, cmd in _pending_commands.items():
        if cmd["status"] == "sent" and cmd["device"] == device and now - cmd["ts"] < 300:
            if cmd["ts"] > best_ts:
                best_ts = cmd["ts"]
                best_id = cmd_id
    if best_id:
        _pending_commands[best_id]["status"] = "executed" if ok else "failed"
        _pending_commands[best_id]["detail"] = detail
        return _pending_commands[best_id]["status"]
    return "executed" if ok else "failed"


def _get_active_ws():
    """Возвращает websocket активного подключённого устройства.
    Порядок: активное по presence_sync → первое онлайн → None.
    """
    try:
        from modules.presence_sync import get_active_device
        dev = get_active_device()
        if dev and dev in connected_devices:
            return connected_devices[dev], dev
    except Exception as e:
        log.debug(f"[voice] _get_active_ws: {type(e).__name__}: {e}")
    for dev_id, ws in connected_devices.items():
        return ws, dev_id
    return None, None

