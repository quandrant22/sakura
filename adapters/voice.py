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
    _live_synthesize_preferred,
    _stream_two_stage,
)
from modules.state import connected_devices

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


class VoiceGate:
    """Шлюз «классификатор роутера ∥ голосовой стрим» (п.2 perf/voice-latency).

    Пока классификатор не вернул «не команда», накопленные предложения
    НЕ уходят в TTS: их буфер держит stream_llm_to_tts, читая токены
    LLM дальше (подготовка параллельна классификации). Вердикт «команда»
    приходит снаружи — задача голоса отменяется, буфер выбрасывается.
    open() после «не команда» (и по таймауту — как «не команда») отдаёт
    буфер в TTS и продолжает стрим без потери токенов.
    """

    # Таймаут классификатора — 5с (bridge.get_router: llm_classify timeout=5.0);
    # ждём чуть дольше, дальше считаем «не команда» (спека п.2).
    WAIT_S = 6.0

    def __init__(self) -> None:
        self._ev = asyncio.Event()

    def open(self) -> None:
        self._ev.set()

    @property
    def opened(self) -> bool:
        return self._ev.is_set()

    async def wait_open(self, timeout: Optional[float] = None) -> bool:
        """Ждать вердикта; по таймауту открываемся сами («не команда»).

        Возвращает True — вердикт пришёл, False — открылись по таймауту.
        """
        if self._ev.is_set():
            return True
        try:
            await asyncio.wait_for(
                self._ev.wait(),
                self.WAIT_S if timeout is None else timeout,
            )
            return True
        except asyncio.TimeoutError:
            self._ev.set()
            return False


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
    timeout: float = 8.0,
    chain=None,
    gate: Optional[VoiceGate] = None,
    received_at: Optional[float] = None,
) -> tuple[str, str]:
    """Стриминг LLM→TTS: предложение готово → сразу в синтез.

    Сигнатура совместима с вызовами v2 (main.py ask_gemini_voice): голосовой
    путь идёт через этот адаптер. Возвращает (полный текст, эмоция).
    stop — опциональный callable(): True между пакетами → обрыв озвучки.
    gate — шлюз классификатора (п.2): пока не открыт, накопленные
    предложения НЕ уходят в стадии TTS, но чтение токенов продолжается.
    received_at — time.monotonic() приёма голоса (п.5): бюджеты «первый
    звук» и «ответ готов» считаются от него, а не от старта этого стрима,
    иначе параллельная классификация выпадает из замера.
    """
    key = _llm.pick_key(api_key)
    if client is None:
        client = _llm.get_client(key)
    t0 = time.monotonic()
    base = budget.since(received_at, t0)   # точка отсчёта голосовых бюджетов
    deadline = t0 + timeout
    parts: list[str] = []
    queues: list[asyncio.Queue] = []
    producers: list[asyncio.Task] = []
    first_audio_logged = False
    synth_failed = False

    async def _produce(text: str, q: asyncio.Queue, stage: int) -> None:
        try:
            if stage == 1:
                # Стадия 1 — из предбанника TTS (п.3): коннект открыт
                # заранее, handshake не на критическом пути. synth —
                # подмена синтеза (тесты/этап 6).
                await _live_synthesize_preferred(
                    text, emotion, q.put, label=f"стадия {stage}",
                    synth=_live_synthesize)
            else:
                await _live_synthesize(text, emotion, q.put,
                                       label=f"стадия {stage}")
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
                _ms = (time.monotonic() - base) * 1000
                log.info(f"[voice] первый звук за {_ms:.0f}мс (от приёма голоса)")
                budget.check("voice_first_audio", _ms)


    try:
        try:
            tokens = _llm.stream_tokens(
                contents, system=system, model=model, max_tokens=max_tokens,
                temperature=temperature, api_key=key,
                timeout=max(0.0, deadline - time.monotonic()),
                chain=chain,
            )
            async for sentence in iter_sentences(tokens):
                m = _EMOTION_LINE.match(sentence)
                if m:
                    emotion = m.group(1)
                    continue
                parts.append(sentence)
                if gate is not None:
                    # Токены читаются параллельно классификатору, но в TTS
                    # предложение уходит только после вердикта «не команда».
                    await gate.wait_open()
                _new_stage(sentence)
        except Exception as e:
            log.error(f"[voice] стрим LLM упал: {e}")

        # Ни одного предложения — фолбэк: обычная генерация → двухстадийный путь v2
        if not parts:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "", emotion
            text = (await _llm.generate(contents, system=system, model=model,
                                        max_tokens=max_tokens, temperature=temperature,
                                        api_key=key, timeout=remaining,
                                        chain=chain)).strip()
            if not text:
                return "", emotion
            clean = text
            for line in text.split("\n"):
                if line.strip().startswith("EMOTION:"):
                    emotion = line.strip().replace("EMOTION:", "").strip()
            clean = _NL_WS.sub(" ", _EMOTION_LINE.sub("", clean)).strip()
            if gate is not None:
                # Вердикта ещё нет: команда → задача отменена здесь же,
                # буфер выброшен, TTS не вызван.
                await gate.wait_open()
            first, _, rest = clean.partition(". ")
            if rest.strip():
                await _stream_two_stage(first.strip() + ".", rest.strip(), websocket,
                                        device_id, emotion, t0, stop=stop)
            elif websocket:
                await _live_synthesize_preferred(
                    clean, emotion, _make_audio_sender(websocket, device_id),
                    synth=_live_synthesize)
            return clean, emotion

        # Пакеты уходят строго по порядку стадий
        for q in queues:
            if not await _drain(q):
                break
    finally:
        # Отмена задачи (команда) и обычный выход — продюсеры TTS снимаются
        # всегда: зависшая Live-сессия не переживает обрыв стрима.
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
        budget.timed("voice_llm_done", base)
    full_text = " ".join(parts)
    now = time.monotonic()
    log.info(f"[voice] ответ готов: {now-base:.1f}с от приёма голоса, "
             f"{now-t0:.1f}с от старта стрима, {len(full_text)} симв")
    return full_text, emotion



def _get_active_ws():
    """Возвращает websocket активного подключённого устройства."""
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
