"""
modules/tts_server.py — TTS с быстрым первым звуком.

Схема:
  текст → [ТОН:]/очистка → разбивка на речевые чанки
  короткий текст  → одна Live-сессия
  длинный         → гибрид: первое предложение — отдельная быстрая сессия,
                    остальное — вторая сессия ПАРАЛЛЕЛЬНО (asyncio),
                    пакеты на устройство строго по порядку (FIFO-буфер)

Итог: первый звук < 3с, между предложениями нет слышимой паузы.
"""

import asyncio
import base64
import json
import logging
import re
import time
from typing import AsyncIterator

from google import genai
from google.genai import types

from config import get_active_key, mark_key_used

log = logging.getLogger(__name__)

TTS_MODEL       = "gemini-2.5-flash-native-audio-latest"
TTS_VOICE       = "Aoede"
TTS_SAMPLE_RATE = 24000
SESSION_TIMEOUT = 25

# Семафор — не более 2 параллельных TTS сессий
_sem = asyncio.Semaphore(2)

# Переиспользуем клиент между запросами
_client      = None
_client_lock = asyncio.Lock()


# ── Очистка текста перед TTS ─────────────────────────────────────────

# Идентификационные утечки модели («я Gemini») — вырезаем где угодно:
# осмысленного текста с такими фразами не бывает.
_LEAK_ANYWHERE = [
    "Live API", "live api", "LiveApi",
    "I'm Gemini", "I am Gemini", "я Gemini", "я Гемини",
]

# Фразы-отказы/извинения/дисклеймеры — вырезаем ТОЛЬКО если реплика
# НАЧИНАЕТСЯ с них, и целиком до конца предложения. Середину текста не
# трогаем: «поищу в Google», «я не могу открыть дверь» — это нормальный
# ответ Сакуры, а не утечка.
_LEAK_STARTERS = [
    "as an ai", "как ai", "как искусственный интеллект",
    "i'm a language model", "я языковая модель",
    "i can't", "i cannot", "я не могу", "i'm not able", "я не способна",
    "i apologize", "приношу извинения", "извините", "простите",
    "как синтезатор речи", "as a text-to-speech",
]


def _strip_leading_leak(text: str) -> str:
    """Если реплика начинается с фразы-утечки — убирает её до конца
    предложения (включая саму фразу). Повторяет, пока начало — утечка."""
    while text:
        stripped = text.lstrip()
        lead = len(text) - len(stripped)
        low = stripped.lower()
        hit_len = 0
        for phrase in sorted(_LEAK_STARTERS, key=len, reverse=True):
            if low.startswith(phrase):
                after = stripped[len(phrase):len(phrase) + 1]
                # граница слова: после фразы не буква/цифра
                if not after or not after.isalnum():
                    hit_len = len(phrase)
                    break
        if not hit_len:
            break
        rest = stripped[hit_len:]
        m = re.search(r'[.!?…\n]', rest)
        text = (rest[m.end():] if m else "").lstrip()
    return text


def _clean_tts_text(text: str) -> str:
    """Удаляет мусор из текста перед отправкой в TTS."""
    if not text:
        return text
    original = text
    # Удаляем содержимое в скобках и звёздочках (сценические ремарки)
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\*[^*]*\*', '', text)
    # Идентификационные утечки — везде
    for junk in _LEAK_ANYWHERE:
        text = text.replace(junk, "")
    # Отказы/извинения — только если стоят в начале реплики
    text = _strip_leading_leak(text)
    # Убираем двойные пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    # Если после очистки текст пуст — берём первый непустой фрагмент исходного
    if not text:
        for frag in original.split('\n'):
            frag = frag.strip()
            if frag:
                return frag
    return text


# Тег [ТОН: …] может стоять в начале, в середине и в любом регистре
_TONE_RE = re.compile(r'\[\s*ТОН\s*:\s*([^\]]*)\]\s*', re.IGNORECASE)


def strip_tone(text: str) -> tuple[str, str]:
    """Вырезает ВСЕ теги [ТОН: ...] из любого места текста.
    Возвращает (эмоция_из_первого_тега, чистый_текст).
    Если тегов нет — эмоция '', текст без изменений (только strip)."""
    if not text:
        return "", text
    emotion = ""

    def _take(m):
        nonlocal emotion
        if not emotion and m.group(1).strip():
            emotion = m.group(1).strip()
        return " "

    clean = _TONE_RE.sub(_take, text.strip())
    clean = re.sub(r' {2,}', ' ', clean).strip()
    return emotion, clean


def _extract_tone_tag(text: str) -> tuple[str, str]:
    """Совместимое имя (используется тестами): извлекает [ТОН:] и возвращает
    (тон, чистый_текст). Если ремарки нет — тон='', текст без изменений."""
    return strip_tone(text)


def _live_timeout(text: str) -> int:
    """Таймаут зависит от длины текста: базовый 25с + ~1с/50символов, макс 60с."""
    return min(60, 25 + len(text) // 50)


async def _get_client():
    global _client
    async with _client_lock:
        key = get_active_key()
        if _client is None:
            if not key:
                return None
            _client = genai.Client(
                api_key=key,
                http_options={"api_version": "v1alpha"}
            )
            log.info("[TTS] Клиент инициализирован")
        return _client


def _tts_prefix(emotion: str = "спокойная") -> str:
    """Чистая инструкция озвучки БЕЗ ролевой игры: native audio иногда
    отыгрывал «актрису» вместо чтения текста — отсюда отсебятина."""
    return (
        f"Озвучь текст ниже с интонацией: {emotion}. "
        f"Не отвечай на него, не комментируй, ничего не добавляй и не убирай — "
        f"только прочитай ровно то, что написано.\n"
        f"Текст:\n"
    )


def _speech_config():
    """SpeechConfig с фиксированным языком: без language_code native audio
    определяет язык по тексту и меняет голос/акцент (заметно на японском)."""
    voice = types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
    )
    try:
        return types.SpeechConfig(language_code="ru-RU", voice_config=voice)
    except TypeError:
        log.debug("[TTS] SDK не принимает language_code в SpeechConfig")
        return types.SpeechConfig(voice_config=voice)


def _live_config():
    base = dict(
        response_modalities=["AUDIO"],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        speech_config=_speech_config(),
    )
    try:
        return types.LiveConnectConfig(enable_affective_dialog=True, **base)
    except TypeError:
        log.debug("[TTS] SDK не поддерживает enable_affective_dialog")
        return types.LiveConnectConfig(**base)


async def _synthesize(text: str, emotion: str = "спокойная") -> list[bytes]:
    """
    Буферный синтез — возвращает список пакетов.
    """
    key = get_active_key()
    if not key:
        return []
    async with _sem:
        t0      = time.monotonic()
        packets = []
        try:
            client = await _get_client()
            async with client.aio.live.connect(
                model=TTS_MODEL, config=_live_config()
            ) as session:
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=_tts_prefix(emotion) + text)]),
                    turn_complete=True,
                )
                async with asyncio.timeout(SESSION_TIMEOUT):
                    async for response in session.receive():
                        if response.data:
                            packets.append(response.data)
                        if (response.server_content
                                and response.server_content.turn_complete):
                            break
            mark_key_used(key)
            log.info(f"[TTS] синтез (буфер) за {time.monotonic()-t0:.1f}с | {len(packets)} пакетов | тон: {emotion}")
            return packets
        except Exception as e:
            log.error(f"[TTS] Ошибка синтеза: {e}")
            global _client
            _client = None
            return []


async def _synthesize_stream(text: str, websocket, device_id: str, t0: float, emotion: str = "спокойная") -> bool:
    """
    Синтезирует чанк и отправляет агенту.
    """
    key = get_active_key()
    if not key:
        return False

    async with _sem:
        s0    = time.monotonic()
        sent  = 0
        first = True
        try:
            client = await _get_client()
            async with client.aio.live.connect(
                model=TTS_MODEL, config=_live_config()
            ) as session:
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=_tts_prefix(emotion) + text)]
                    ),
                    turn_complete=True,
                )
                async with asyncio.timeout(SESSION_TIMEOUT):
                    async for response in session.receive():
                        if response.data:
                            if first:
                                log.info(f"[TTS] первый звук за {time.monotonic()-t0:.1f}с")
                                first = False
                            try:
                                await websocket.send(json.dumps({
                                    "type":        "tts_chunk",
                                    "device_id":   device_id,
                                    "audio":       base64.b64encode(response.data).decode(),
                                    "sample_rate": TTS_SAMPLE_RATE,
                                }))
                                sent += 1
                            except Exception as e:
                                log.error(f"[TTS] Отправка: {e}")
                                return sent > 0
                        if (response.server_content
                                and response.server_content.turn_complete):
                            break
            mark_key_used(key)
            log.info(f"[TTS] синтез+отправка за {time.monotonic()-s0:.1f}с | {sent} пакетов | тон: {emotion}")
            return sent > 0
        except Exception as e:
            log.error(f"[TTS] Ошибка синтеза: {e!r}")
            global _client
            _client = None
            return sent > 0


def _make_audio_sender(websocket, device_id: str):
    """Фабрика отправщиков аудио-пакетов на устройство."""
    async def send_audio(data: bytes):
        await websocket.send(json.dumps({
            "type":        "tts_chunk",
            "device_id":   device_id,
            "audio":       base64.b64encode(data).decode(),
            "sample_rate": TTS_SAMPLE_RATE,
        }))
    return send_audio


async def _live_synthesize(text: str, emotion: str, on_packet,
                           label: str = "") -> int:
    """Одна Live-сессия: шлёт текст, каждый аудио-пакет отдаёт в on_packet.
    Возвращает число пакетов. Ошибки глотает (лог + сброс клиента).
    label — метка в логах для двухстадийного пути («стадия 1»/«стадия 2»)."""
    key = get_active_key()
    if not key:
        return 0
    sent = 0
    tag = f"[TTS] {label}: " if label else "[TTS] "
    async with _sem:
        s0 = time.monotonic()
        try:
            client = await _get_client()
            timeout = _live_timeout(text)
            # ВАЖНО: connect под общим таймаутом. Раньше коннект был ВНЕ
            # asyncio.timeout — зависший handshake висел вечно, drain
            # уходил по аварийному таймауту, а финальный await задачи
            # дожидался этого зависшего коннекта (лишние секунды в
            # «Готово за Nс»).
            async with asyncio.timeout(timeout):
                async with client.aio.live.connect(
                    model=TTS_MODEL, config=_live_config()
                ) as session:
                    log.info(f"{tag}коннект за {time.monotonic()-s0:.1f}с | таймаут: {timeout}с")
                    await session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=_tts_prefix(emotion) + text)]
                        ),
                        turn_complete=True,
                    )
                    async for response in session.receive():
                        if response.data:
                            await on_packet(response.data)
                            sent += 1
                        if (response.server_content
                                and response.server_content.turn_complete):
                            break
            mark_key_used(key)
            log.info(f"{tag}синтез за {time.monotonic()-s0:.1f}с | {sent} пакетов | тон: {emotion}")
            return sent
        except Exception as e:
            log.error(f"{tag}Ошибка синтеза: {e!r}")
            global _client
            _client = None
            return sent


async def _synthesize_and_stream(text: str, websocket, device_id: str,
                                 emotion: str = "спокойная") -> int:
    """Одна Live-сессия на весь текст: пакеты сразу на устройство."""
    send_audio = _make_audio_sender(websocket, device_id)
    return await _live_synthesize(text, emotion, send_audio)


# ── Быстрый старт: первое предложение — сразу, остальное — параллельно ──

_SENT_SPLIT_RE = re.compile(r'(?<=[.!?…])\s+')
_MAX_FIRST_CHUNK = 200  # символов; длиннее — режем по запятым/пробелам


def _split_speech(text: str) -> list[str]:
    """Режет текст на речевые чанки: по предложениям, слишком длинные
    предложения — по запятым, затем по пробелам. Пустые не возвращаются."""
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]
    if not sentences:
        return [text.strip()] if text.strip() else []

    parts: list[str] = []
    for s in sentences:
        while len(s) > _MAX_FIRST_CHUNK:
            # режем по запятой в пределах лимита, иначе по пробелу
            cut = s.rfind(",", 0, _MAX_FIRST_CHUNK)
            sep = 1
            if cut < _MAX_FIRST_CHUNK // 2:
                cut = s.rfind(" ", 0, _MAX_FIRST_CHUNK)
                sep = 0
            if cut <= 0:
                break
            parts.append(s[:cut].strip())
            s = s[cut + sep:].strip()
        if s:
            parts.append(s)
    return parts


async def _stream_two_stage(first: str, rest: str, websocket, device_id: str,
                            emotion: str, t0: float) -> int:
    """Гибрид быстрого старта БЕЗ пауз между предложениями.

    Первое предложение синтезируется отдельной быстрой сессией и уходит
    на устройство сразу. Остальной текст стартует ВТОРОЙ сессией
    ПАРАЛЛЕЛЬНО — её ранние пакеты буферизуются в очереди и вытекают
    строго после пакетов первой, поэтому порядок сохранён, а между
    первым и вторым предложением нет слышимой паузы.

    Завершение: каждый продюсер кладёт в свою очередь sentinel None
    (гарантированно, в finally) — drain заканчивается СРАЗУ по этому
    признаку конца потока, а не ждёт пакетов до аварийного таймаута.
    Сам таймаут остался только страховкой: если продюсер молчит дольше
    SESSION_TIMEOUT — предупреждение в лог (однократно) и продолжение
    ожидания, пакеты НЕ бросаются (продюсер ограничен своим внутренним
    таймаутом сессии и в любом случае поставит sentinel)."""
    send_audio = _make_audio_sender(websocket, device_id)

    q_first: asyncio.Queue = asyncio.Queue()
    q_rest: asyncio.Queue = asyncio.Queue()

    async def _produce(text: str, q: "asyncio.Queue", stage: int) -> None:
        """Продюсер стадии: синтез + гарантированный sentinel конца потока."""
        log.info(f"[TTS] стадия {stage}: старт (+{time.monotonic()-t0:.1f}с от начала, {len(text)} симв)")
        try:
            await _live_synthesize(text, emotion, q.put, label=f"стадия {stage}")
        finally:
            await q.put(None)

    task_first = asyncio.create_task(_produce(first, q_first, 1))
    task_rest  = asyncio.create_task(_produce(rest,  q_rest, 2))

    sent = 0
    first_logged = False

    async def drain(q: "asyncio.Queue", stage: int) -> None:
        """Выкачивает очередь стадии на устройство до sentinel-а конца.

        Раньше выход по таймауту БРОСАЛ остаток очереди, а заблокированное
        ожидание не замечало завершения продюсера — отсюда лишние секунды
        после «синтез за …» обеих стадий. Теперь конец потока приходит
        sentinel-ом немедленно."""
        nonlocal sent, first_logged
        warned = False
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=SESSION_TIMEOUT)
            except asyncio.TimeoutError:
                # Аварийная страховка: продюсер молчит. НЕ выходим и НЕ
                # бросаем очередь — его внутренний таймаут гарантированно
                # завершит продюсер (sentinel в finally). Ждём дальше.
                if not warned:
                    log.warning(
                        f"[TTS] two-stage: стадия {stage} молчит >{SESSION_TIMEOUT}с "
                        f"— продолжаем ждать sentinel (пакеты не бросаем)")
                    warned = True
                continue
            if data is None:
                log.info(f"[TTS] стадия {stage}: поток завершён (+{time.monotonic()-t0:.1f}с)")
                return
            try:
                await send_audio(data)
            except Exception as e:
                log.error(f"[TTS] Отправка: {e}")
                return
            sent += 1
            if not first_logged:
                log.info(f"[TTS] первый звук за {time.monotonic()-t0:.1f}с")
                first_logged = True

    # Фаза 1: первая сессия (быстрый старт)
    await drain(q_first, 1)
    # Фаза 2: вторая сессия — её ранние пакеты уже ждут в очереди
    await drain(q_rest, 2)

    # Нормальный путь: оба продюсера уже завершены (sentinel приходит из
    # их finally). Если вышли раньше (ошибка отправки) — снимаем задачи,
    # чтобы не дожидаться зависшую сессию.
    for t in (task_first, task_rest):
        if not t.done():
            t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"[TTS] producer: {e}")
    return sent


async def _send_end(websocket, device_id: str):
    try:
        await websocket.send(json.dumps({
            "type": "tts_end",
            "device_id": device_id
        }))
    except Exception:
        pass


# Порог отсечки пустоты/мусора. Прежний порог в 20 символов молчал на
# коротких ответах («Принято.», «Готово.»); контентный мусор вычищает
# _clean_tts_text, здесь оставляем только защиту от пустоты.
MIN_TTS_LEN = 2


async def stream_tts_to_device(
    text: str,
    websocket,
    device_id: str,
    literal: bool = False,
    emotion: str = "спокойная",
):
    """Единая точка входа озвучки (голос и все фоновые пути).

    Обработка одинаковая для обоих путей вызова:
      main.py → stream_llm_to_tts → сюда; ws_handlers → напрямую сюда.
    [ТОН:], очистка текста и эмоция применяются здесь же.

    Схема: короткий текст — одна Live-сессия; длинный — гибрид быстрого
    старта (_stream_two_stage): первое предложение звучит сразу (<3с),
    остальное синтезируется параллельно без слышимых пауз."""
    tone, text = _extract_tone_tag(text)
    if tone:
        emotion = tone

    text = _clean_tts_text(text)
    if not text or len(text.strip()) < MIN_TTS_LEN:
        return

    t0 = time.monotonic()
    parts = _split_speech(text)
    if len(parts) <= 1:
        sent = await _synthesize_and_stream(text, websocket, device_id, emotion)
    else:
        sent = await _stream_two_stage(
            parts[0], " ".join(parts[1:]), websocket, device_id, emotion, t0)
    await _send_end(websocket, device_id)
    log.info(f"[TTS] Готово за {time.monotonic()-t0:.1f}с | {sent} пакетов | тон: {emotion}")


async def stream_llm_to_tts(
    contents,
    system: str,
    websocket,
    device_id: str,
    client,
    model: str,
    max_tokens: int = 200,
    temperature: float = 0.85,
    api_key: str = None,
    emotion: str = "спокойная",
) -> tuple[str, str]:
    """
    Стриминг LLM→TTS: предложение готово → сразу в синтез.
    """
    t0       = time.monotonic()
    full_text = ""

    try:
        from google.genai import types as _t

        response_iter = await asyncio.to_thread(
            lambda: client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=_t.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
        )

        # Инкрементальная итерация: читаем токены по мере поступления
        _SENT_END = re.compile(r'(?<=[.!?…])\s+')
        buf = ""
        sentences = []

        def _drain():
            """Читаем все доступные чанки из итератора (блокирующий поток)."""
            parts = []
            for chunk in response_iter:
                t = chunk.text or ""
                if t:
                    parts.append(t)
            return parts

        text_chunks = await asyncio.to_thread(_drain)
        mark_key_used(api_key)

        combined = "".join(text_chunks)
        full_text = combined

        log.info(f"[TTS stream] LLM за {time.monotonic()-t0:.1f}с")

        # Парсим эмоцию
        for line in combined.split("\n"):
            if line.strip().startswith("EMOTION:"):
                emotion = line.strip().replace("EMOTION:", "").strip()

        clean = re.sub(r'EMOTION:\w+', '', combined).strip()

        if clean and websocket:
            await stream_tts_to_device(clean, websocket, device_id, emotion=emotion)

        return full_text, emotion

    except Exception as e:
        log.error(f"[TTS stream] {e}")

        # Fallback: обычная генерация
        try:
            from google.genai import types as _t
            r = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=contents,
                config=_t.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
            full_text = (r.text or "").strip()
            mark_key_used(api_key)

            for line in full_text.split("\n"):
                if line.strip().startswith("EMOTION:"):
                    emotion = line.strip().replace("EMOTION:", "").strip()

            clean = re.sub(r'EMOTION:\w+', '', full_text).strip()
            if clean and websocket:
                await stream_tts_to_device(clean, websocket, device_id, emotion=emotion)

        except Exception as e2:
            log.error(f"[TTS stream fallback] {e2}")

        return full_text, emotion


def add_emotion_pauses(text: str, emotion: str = "neutral") -> str:
    """Добавляет паузы для эмоциональности. Не меняет текст."""
    # Не добавляем ничего — говорим дословно
    return text


def start():
    log.info(f"[TTS] Запущен. Модель: {TTS_MODEL}, голос: {TTS_VOICE}")


async def warmup_cache():
    pass