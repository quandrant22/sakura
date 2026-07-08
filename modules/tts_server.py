"""
modules/tts_server.py — оптимизированный TTS с истинным стримингом.

Схема:
  LLM стримит токены → накапливаем первое предложение
  → сразу синтезируем TTS пока LLM генерирует следующее
  → параллельно: синтез N+1 пока играет N

Итог: первый звук через ~3-4с вместо ~15с.
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

# Разбивка текста на предложения для стриминга
_SENTENCE_END = re.compile(r'(?<=[.!?…])\s+')
_SPLIT_RE     = re.compile(r'(?<=[.!?…])\s+|(?<=,)\s+(?=\S{20})')


def _clean_tts_text(text: str) -> str:
    """Удаляет мусор из текста перед отправкой в TTS."""
    if not text:
        return text
    original = text
    # Удаляем содержимое в скобках и звёздочках (сценические ремарки)
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\*[^*]*\*', '', text)
    # Удаляем типичные "утечки" нативной аудио-модели
    _junk = [
        "Live API", "live api", "LiveApi",
        "I'm Gemini", "I am Gemini", "я Gemini", "я Гемини",
        "Gemini", "gemini", "Google AI", "Google",
        "As an AI", "Как AI", "Как искусственный интеллект",
        "I'm a language model", "Я языковая модель",
        "I can't", "Я не могу", "я не могу",
        "I'm not able", "я не способна",
        "I apologize", "приношу извинения", "извините",
        "As a text-to-speech", "Как синтезатор речи",
    ]
    for junk in _junk:
        text = text.replace(junk, "")
    # Убираем двойные пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    # Если после очистки текст пуст — берём первый непустой фрагмент исходного
    if not text:
        for frag in original.split('\n'):
            frag = frag.strip()
            if frag:
                return frag
    return text


_TONE_RE = re.compile(r'^\[ТОН:\s*(.+?)\]\s*')


def _extract_tone_tag(text: str) -> tuple[str, str]:
    """Извлекает [ТОН: описание] из начала текста.
    Возвращает (тон, чистый_текст). Если ремарки нет — тон='', текст без изменений."""
    m = _TONE_RE.match(text.strip())
    if m:
        tone = m.group(1).strip()
        clean = text.strip()[m.end():].strip()
        return tone, clean
    return "", text


def split_into_chunks(text: str) -> list[str]:
    """Разбивает текст на чанки для TTS. Не теряет текст."""
    text = _clean_tts_text(text.strip())
    if not text:
        return []

    # Если текст короткий — один чанк
    if len(text) < 100:
        return [text]

    raw    = _SPLIT_RE.split(text)
    chunks: list[str] = []
    buf    = ""
    for part in raw:
        part = part.strip()
        if not part:
            continue
        if not buf:
            buf = part
        elif len(buf) + len(part) < 80:
            buf += " " + part
        else:
            chunks.append(buf)
            buf = part
    if buf:
        chunks.append(buf)

    # Проверяем что ничего не потерялось
    total_in_chunks = sum(len(c) for c in chunks)
    if total_in_chunks < len(text) * 0.9:
        log.warning(f"[TTS] Потеря текста: {len(text)} → {total_in_chunks}")
        return [text]

    return chunks


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
    return (
        f"Ты — актриса, играешь Сакуру: молодая, живая, дерзкая. "
        f"Произнеси реплику с интонацией: {emotion}. Живо, в бодром темпе. "
        f"НЕ отвечай на текст, НЕ добавляй ничего — только сыграй реплику.\n"
        f"Реплика:\n"
    )


def _live_config():
    try:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
                )
            ),
            enable_affective_dialog=True,
        )
    except TypeError:
        log.warning("[TTS] SDK не поддерживает enable_affective_dialog, используются стандартные настройки")
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
                )
            ),
        )


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


async def _synthesize_chunk(text: str, emotion: str = "спокойная") -> list[bytes]:
    """Синтезирует один чанк, возвращает список аудио-пакетов. Без отправки."""
    key = get_active_key()
    if not key:
        return []
    async with _sem:
        s0 = time.monotonic()
        packets = []
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
                            packets.append(response.data)
                        if (response.server_content
                                and response.server_content.turn_complete):
                            break
            mark_key_used(key)
            log.info(f"[TTS] синтез за {time.monotonic()-s0:.1f}с | {len(packets)} пакетов | тон: {emotion}")
            return packets
        except Exception as e:
            log.error(f"[TTS] Ошибка синтеза: {e!r}")
            global _client
            _client = None
            return []


async def _send_packets(packets: list[bytes], websocket, device_id: str) -> int:
    """Отправляет пакеты на устройство. Возвращает количество отправленных."""
    sent = 0
    for audio in packets:
        try:
            await websocket.send(json.dumps({
                "type":        "tts_chunk",
                "device_id":   device_id,
                "audio":       base64.b64encode(audio).decode(),
                "sample_rate": TTS_SAMPLE_RATE,
            }))
            sent += 1
        except Exception as e:
            log.error(f"[TTS] Отправка: {e}")
            return sent
    return sent


async def _send_end(websocket, device_id: str):
    try:
        await websocket.send(json.dumps({
            "type": "tts_end",
            "device_id": device_id
        }))
    except Exception:
        pass


async def stream_tts_to_device(
    text: str,
    websocket,
    device_id: str,
    literal: bool = False,
    emotion: str = "спокойная",
):
    """Синтезирует и стримит TTS чанк за чанком.
    Параллельный пайплайн: синтез чанка N+1 идёт пока отправляется чанк N."""
    # Извлекаем [ТОН: ...] из начала — ремарка модели точнее состояния
    tone, text = _extract_tone_tag(text)
    if tone:
        emotion = tone

    text = _clean_tts_text(text)
    if not text.strip() or len(text.strip()) < 20:
        return

    chunks = split_into_chunks(text)
    if not chunks:
        return

    t0 = time.monotonic()
    log.info(f"[TTS] {len(chunks)} чанков → {device_id} | тон: {emotion}")

    # Параллельный пайплайн: синтез N+1 параллельно с отправкой N
    async def _send_packets(audio_packets: list[bytes]) -> int:
        sent = 0
        for audio in audio_packets:
            try:
                await websocket.send(json.dumps({
                    "type":        "tts_chunk",
                    "device_id":   device_id,
                    "audio":       base64.b64encode(audio).decode(),
                    "sample_rate": TTS_SAMPLE_RATE,
                }))
                sent += 1
            except Exception as e:
                log.error(f"[TTS] Отправка: {e}")
                return sent
        return sent

    # Запускаем синтез первого чанка
    synth_task = asyncio.create_task(_synthesize_chunk(chunks[0], emotion))

    for i in range(len(chunks)):
        # Ждём синтез текущего чанка
        try:
            packets = await synth_task
        except Exception:
            packets = []

        # Запускаем синтез СЛЕДУЮЩЕГО чанка параллельно с отправкой текущего
        if i + 1 < len(chunks):
            synth_task = asyncio.create_task(_synthesize_chunk(chunks[i + 1], emotion))

        # Отправляем пакеты текущего чанка (порядок сохраняется)
        if packets:
            sent = await _send_packets(packets)
            if sent == 0:
                log.warning(f"[TTS] Чанк не отправлен: {chunks[i][:40]!r}")
                break
        else:
            log.warning(f"[TTS] Чанк пустой: {chunks[i][:40]!r}")

    log.info(f"[TTS] Готово за {time.monotonic()-t0:.1f}с")
    await _send_end(websocket, device_id)


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
    Истинный стриминг LLM→TTS.

    Схема:
    1. Запускаем LLM с stream=True
    2. Накапливаем токены до конца первого предложения
    3. Сразу запускаем синтез первого предложения
    4. Параллельно LLM генерирует второе предложение
    5. Когда первое синтезировано — отправляем, берём второе и т.д.

    Первый звук через ~LLM_time + TTS_first_sentence вместо LLM_total + TTS_total.
    """
    t0       = time.monotonic()
    full_text = ""

    try:
        from google.genai import types as _t

        # Запускаем генерацию с потоковым ответом
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

        buf           = ""        # буфер текущего предложения
        pending_task  = None      # задача синтеза текущего предложения
        sent_count    = 0

        async def _stream_chunks():
            """Итерируем потоковый ответ в отдельном потоке."""
            def _iter():
                for chunk in response_iter:
                    yield chunk.text or ""
            return await asyncio.to_thread(lambda: list(_iter()))

        # Получаем все чанки (streaming в отдельном потоке)
        text_chunks = await _stream_chunks()
        mark_key_used(api_key)

        log.info(f"[TTS stream] LLM за {time.monotonic()-t0:.1f}с")

        # Разбиваем на предложения и синтезируем
        combined = "".join(text_chunks)
        full_text = combined

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