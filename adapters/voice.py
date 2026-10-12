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
    MIN_FIRST_CHUNK,
    SINGLE_MAX_CHARS,
    SINGLE_MAX_SENTENCES,
    _make_audio_sender,
    _live_synthesize,
    _live_synthesize_preferred,
    _stream_two_stage,
)
from modules.state import connected_devices
import modules.tts_server as _tts

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

    # Сколько ждать вердикта, дальше считаем «не команда» (спека п.2):
    # config.VOICE_GATE_WAIT_S (env), по умолчанию 4с. Вердикт «команда»
    # отменяет стрим раньше — через on_command в v3_fast_path.
    def __init__(self) -> None:
        import config
        self._ev = asyncio.Event()
        self.WAIT_S = config.VOICE_GATE_WAIT_S

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
    gate — шлюз классификатора (п.2). Предсинтез (VOICE_PRESYNTH, perf/
    voice-2): стадии синтезируются сразу, не дожидаясь вердикта, готовый
    звук держится в памяти; на устройство он уходит, когда шлюз открыт
    («не команда»). Вердикт «команда» отменяет задачу — синтез снимается,
    удержанный звук выбрасывается. VOICE_PRESYNTH=0 — прежнее поведение:
    до вердикта стадии не стартуют.
    Отправка на устройство идёт параллельно стриму LLM: первая стадия
    звучит, не дожидаясь конца ответа модели.
    received_at — time.monotonic() приёма голоса (п.5): бюджеты «первый
    звук» и «ответ готов» считаются от него, а не от старта этого стрима.
    """
    import config
    from sakura_core import turn_timing

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
    presynth = config.VOICE_PRESYNTH
    max_chars = config.VOICE_MAX_CHARS
    changed = asyncio.Event()          # новая стадия или конец стрима
    stream_done = False

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
        if len(queues) == 1:
            turn_timing.mark("stage1_start")
        held = presynth and gate is not None and not gate.opened
        log.info(f"[voice] стадия {len(queues)}: старт "
                 f"+{(time.monotonic()-base)*1000:.0f}мс от приёма, {len(text)} симв"
                 + (" (звук держится до вердикта)" if held else ""))
        producers.append(asyncio.create_task(_produce(text, q, len(queues))))
        changed.set()

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
                turn_timing.mark("first_audio")
                _ms = (time.monotonic() - base) * 1000
                log.info(f"[voice] первый звук за {_ms:.0f}мс (от приёма голоса)")
                budget.check("voice_first_audio", _ms)

    async def _sender() -> None:
        """Стадии на устройство строго по порядку, параллельно стриму LLM.

        Ждёт шлюз: до вердикта «не команда» готовый звук копится в
        очередях стадий (в памяти)."""
        await _open_gate()
        i = 0
        while True:
            if i < len(queues):
                if not await _drain(queues[i]):
                    return
                i += 1
                continue
            if stream_done:
                return
            changed.clear()
            if i < len(queues) or stream_done:
                continue
            await changed.wait()

    # Планирование стадий (этап 3, п.3.3/3.3б): пока ответ может оказаться
    # коротким (≤ SINGLE_MAX_CHARS и ≤ SINGLE_MAX_SENTENCES), предложения
    # копятся и уходят ОДНОЙ стадией по концу стрима — единая интонация.
    # Стал длинным — стадия 1 (не короче MIN_FIRST_CHUNK), дальше по одному.
    pending: list[str] = []
    started = False

    async def _open_gate() -> None:
        if gate is not None:
            # Вердикт «не команда» (или таймаут шлюза) — звук можно отдавать.
            await gate.wait_open()

    async def _before_stage() -> None:
        # Без предсинтеза стадия не стартует до вердикта (прежний путь).
        if not presynth:
            await _open_gate()

    async def _tokens():
        first = True
        async for tok in _llm.stream_tokens(
                contents, system=system, model=model, max_tokens=max_tokens,
                temperature=temperature, api_key=key,
                timeout=max(0.0, deadline - time.monotonic()),
                chain=chain):
            if first:
                first = False
                turn_timing.mark("first_token")
            yield tok

    sender = asyncio.create_task(_sender())
    try:
        try:
            async for sentence in iter_sentences(_tokens()):
                m = _EMOTION_LINE.match(sentence)
                if m:
                    emotion = m.group(1)
                    continue
                parts.append(sentence)
                if started:
                    await _before_stage()
                    _new_stage(sentence)
                else:
                    pending.append(sentence)
                    joined = " ".join(pending)
                    if not (_tts.TTS_SHORT_SINGLE and len(joined) <= SINGLE_MAX_CHARS
                            and len(pending) <= SINGLE_MAX_SENTENCES):
                        first: list[str] = []
                        while pending and (not first or len(" ".join(first)) < MIN_FIRST_CHUNK):
                            first.append(pending.pop(0))
                        await _before_stage()
                        _new_stage(" ".join(first))
                        started = True
                        for s in pending:
                            _new_stage(s)
                        pending = []
                if max_chars and len(" ".join(parts)) >= max_chars:
                    # Предел длины голосового ответа: дальше не читаем —
                    # и озвучка, и tts_end не ждут длинного хвоста.
                    log.info(f"[voice] предел ответа {max_chars} симв — стрим остановлен")
                    break
        except Exception as e:
            log.error(f"[voice] стрим LLM упал: {e}")
        turn_timing.mark("llm_done")

        if pending:
            # Короткий ответ (или обрыв стрима до роста) — одной стадией.
            await _before_stage()
            _new_stage(" ".join(pending))
            pending = []

        # Ни одного предложения — фолбэк: обычная генерация → двухстадийный путь v2
        if not parts:
            sender.cancel()
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

        stream_done = True
        changed.set()
        await sender
    finally:
        # Отмена задачи (команда) и обычный выход — отправка и продюсеры
        # TTS снимаются всегда: удержанный звук выбрасывается, зависшая
        # Live-сессия не переживает обрыв стрима.
        for t in (sender, *producers):
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
