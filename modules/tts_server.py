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
import os
import re
import time
from typing import AsyncIterator

from google import genai
from google.genai import types

from config import get_active_key, mark_key_used, VOICE_MODEL_CHAIN
from sakura_core.llm import generate as _llm_generate, stream_tokens as _llm_stream

log = logging.getLogger(__name__)

TTS_MODEL       = "gemini-2.5-flash-native-audio-latest"
# Голос задаётся через .env (TTS_VOICE) — смена без правки кода.
# Список из 30 предустановленных голосов см. в .env.example;
# прослушать кандидатов: python3 tools/voice_test.py
TTS_VOICE       = os.getenv("TTS_VOICE", "Aoede")
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
    отыгрывал «актрису» вместо чтения текста — отсюда отсебятина.
    Эмоция не используется — озвучка ровным голосом."""
    return (
        f"Озвучь текст ниже ровным голосом. "
        f"Не отвечай на него, не комментируй, ничего не добавляй и не убирай — "
        f"только прочитай ровно то, что написано.\n"
        f"Текст:\n"
    )


def _speech_config(voice: str | None = None):
    """SpeechConfig с голосом (по умолчанию — TTS_VOICE из окружения).

    Язык в конфиге НЕ задаётся: native audio модели выбирают язык
    автоматически (док-я Live API: «Native audio output models can switch
    between languages naturally during conversation. You can also restrict
    the languages it speaks in by specifying it in the system instructions»).
    Поле language_code в SpeechConfig поддерживается только half-cascade
    моделями — на native audio оно игнорируется. Поэтому язык управления
    идёт через системную инструкцию, а не через SpeechConfig.
    """
    return types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name=voice or TTS_VOICE
            )
        )
    )


def _live_config(voice: str | None = None):
    base = dict(
        response_modalities=["AUDIO"],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        speech_config=_speech_config(voice),
    )
    try:
        return types.LiveConnectConfig(enable_affective_dialog=True, **base)
    except TypeError:
        log.debug("[TTS] SDK не поддерживает enable_affective_dialog")
        return types.LiveConnectConfig(**base)

# ── Предконнект Live-сессии (п.3 perf/voice-latency) ──────────────────
# Между получением голосовой команды и первым токеном LLM есть окно
# (классификатор роутера + первый токен) — за него успевает пройти
# TCP/TLS/WS-handshake и setup Live API (1-3с). Поэтому сессию открываем
# ЗАРАНЕЕ и держим «в предбаннике»: первая стадия синтеза забирает её
# готовой и платит только за саму генерацию звука.
# Отдельного таймаута простоя у Live API в документации нет: соединение
# живёт «around 10 minutes», перед обрывом сервер шлёт GoAway
# (https://ai.google.dev/gemini-api/docs/live-session; в SDK —
# types.LiveServerGoAway.time_left, клиентского idle-таймера нет). На
# форуме разработчиков простаивающее соединение рвётся через ~2-3 мин.
# Всё это ≫ PRECONNECT_TTL, так что держим 10 с — дольше это уже не наш
# запрос.

PRECONNECT_TTL     = 10.0  # сколько держать готовую сессию в предбаннике
PRECONNECT_GRACE   = 0.15  # фора «успел ли» перед своей сессией
PRECONNECT_TIMEOUT = 8.0   # таймаут самого handshake

_preconnect_task    = None   # задача-держатель коннекта
_preconnect_ready   = None   # Future: _Preconnected | None
_preconnect_release = None   # Event: потребитель закончил работу
_preconnect_lock    = asyncio.Lock()


class _Preconnected:
    """Забранная из предбанника сессия: её жизнью владеет потребитель."""

    __slots__ = ("key", "release", "session", "task")

    def __init__(self, session, key, release, task):
        self.session = session
        self.key     = key
        self.release = release
        self.task    = task


def _clear_if_current(ready) -> None:
    """Снять имена предбанника, если они всё ещё указывают на этот коннект."""
    global _preconnect_task, _preconnect_ready, _preconnect_release
    if _preconnect_ready is ready:
        _preconnect_task = _preconnect_ready = _preconnect_release = None


def preconnect_status() -> str:
    """Состояние предбанника (логи/тесты): off|connecting|ready|failed|done."""
    if _preconnect_task is None:
        return "off"
    if _preconnect_ready is not None and _preconnect_ready.done():
        if _preconnect_ready.cancelled() or _preconnect_ready.result() is None:
            return "failed"
        return "ready"
    return "done" if _preconnect_task.done() else "connecting"


async def preconnect(ttl: float = PRECONNECT_TTL) -> bool:
    """Открыть Live-сессию заранее — до первого токена LLM.

    Идемпотентно: если сессия уже греется или готова, ничего не открывает.
    True — предбанник занят (своей или прежней сессией).
    """
    global _preconnect_task, _preconnect_ready, _preconnect_release
    if not get_active_key():
        return False
    async with _preconnect_lock:
        if _preconnect_task is not None and not _preconnect_task.done():
            return True
        _preconnect_ready   = asyncio.get_running_loop().create_future()
        _preconnect_release = asyncio.Event()
        _preconnect_task = asyncio.create_task(
            _preconnect_holder(_preconnect_ready, _preconnect_release, ttl),
            name="tts-preconnect",
        )
        log.info("[TTS] предконнект: старт")
        return True


async def _preconnect_holder(ready, release, ttl: float) -> None:
    """Держит заранее открытую сессию до claim()/release()/ttl.

    Слот семафора берётся здесь и передаётся потребителю вместе с сессией:
    предконнект не увеличивает число одновременных Live-сессий.
    """
    s0 = time.monotonic()
    connector = None
    try:
        async with _sem:
            client = await _get_client()
            if client is None:
                raise RuntimeError("нет клиента TTS (пустой ключ)")
            key = get_active_key()
            connector = client.aio.live.connect(
                model=TTS_MODEL, config=_live_config()
            )
            # Под таймаутом только handshake (как в _live_synthesize):
            # зависший коннект не должен держать слот семафора.
            session = await asyncio.wait_for(connector.__aenter__(),
                                             PRECONNECT_TIMEOUT)
            try:
                log.info(f"[TTS] предконнект: готов за {time.monotonic()-s0:.1f}с")
                if ready.done():
                    return  # потребителя уже нет — сессия не нужна
                ready.set_result(_Preconnected(
                    session, key, release, asyncio.current_task()))
                try:
                    await asyncio.wait_for(release.wait(), ttl)
                except asyncio.TimeoutError:
                    log.info(f"[TTS] предконнект: не востребован "
                             f"за {ttl:.0f}с — закрываю")
                    _clear_if_current(ready)  # следующий preconnect откроет своё
            finally:
                await connector.__aexit__(None, None, None)
    except asyncio.CancelledError:
        if not ready.done():
            ready.set_result(None)
        raise
    except Exception as e:
        log.debug(f"[TTS] предконнект не удался: {type(e).__name__}: {e}")
        if not ready.done():
            ready.set_result(None)


async def release_preconnect() -> None:
    """Закрыть предконнект: команда/отмена/не успел — слот освобождается.

    Забранную сессию (claim) не трогает: её закрывает потребитель через
    release-событие.
    """
    global _preconnect_task, _preconnect_ready, _preconnect_release
    task    = _preconnect_task
    ready   = _preconnect_ready
    release = _preconnect_release
    _preconnect_task = _preconnect_ready = _preconnect_release = None
    if ready is not None and not ready.done():
        ready.cancel()  # ждать нечего: сессии не будет
    if task is None:
        return
    if release is not None:
        release.set()
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise  # отменили не держателя, а НАС
    except Exception as e:
        log.debug(f"[TTS] предконнект: закрытие: {e}")




async def _synthesize(text: str, emotion: str = "спокойная", voice: str | None = None) -> list[bytes]:
    """
    Буферный синтез — возвращает список пакетов.
    voice — имя предустановленного голоса Live API (None → TTS_VOICE);
    используется tools/voice_test.py для прослушивания кандидатов.
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
                model=TTS_MODEL, config=_live_config(voice)
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
            log.info(f"[TTS] синтез (буфер) за {time.monotonic()-t0:.1f}с | {len(packets)} пакетов")
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
            log.info(f"[TTS] синтез+отправка за {time.monotonic()-s0:.1f}с | {sent} пакетов")
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


async def _claim_preconnected(grace: float = PRECONNECT_GRACE):
    """Забрать готовую сессию из предбанника: _Preconnected | None.

    None — предконнект не открылся за grace секунд: вызывающий синтезирует
    своей сессией, а предбанник снимается (слот освобождается). Забравший
    ОБЯЗАН выставить release — держатель закроет сессию и вернёт слот.
    """
    ready = _preconnect_ready
    if ready is None:
        return None
    if not ready.done():
        # Первое предложение готово — даём предконнекту крошечную фору.
        try:
            await asyncio.wait_for(asyncio.shield(ready), grace)
        except asyncio.TimeoutError:
            await release_preconnect()
            return None
    if ready.cancelled() or ready.result() is None:
        await release_preconnect()
        return None
    p = ready.result()
    # Сессия забрана: глобальные имена свободны для следующего предконнекта
    # (этот держатель доработает в фоне за потребителем).
    _clear_if_current(ready)
    return p


async def _pump_session(session, text: str, emotion: str, on_packet) -> int:
    """Отправить текст в Live-сессию и выкачать аудио-пакеты."""
    sent = 0
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
    return sent



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
                    sent = await _pump_session(session, text, emotion, on_packet)
            mark_key_used(key)
            log.info(f"{tag}синтез за {time.monotonic()-s0:.1f}с | {sent} пакетов")
            return sent
        except Exception as e:
            log.error(f"{tag}Ошибка синтеза: {e!r}")
            global _client
            _client = None
            return sent


async def _live_synthesize_preferred(text: str, emotion: str, on_packet,
                                     label: str = "", synth=None) -> int:
    """Синтез в УЖЕ подключённой сессии из предбанника (п.3), иначе обычный.

    Экономит handshake (1-3с) на первой стадии: сессия открыта заранее,
    пока роутер классифицировал запрос и шёл первый токен LLM. Слот
    семафора взят держателем предконнекта и вернётся при release.
    synth — вызывающий может дать свой синтез-фолбэк (по умолчанию
    _live_synthesize; так подмена синтеза в тестах сохраняется).

    Сессия из предбанника умерла до первого пакета (обрыв провайдером,
    таймаут) — синтез повторяется обычным путём; после первого пакета
    не повторяется: иначе начало фразы прозвучит дважды.
    """
    if synth is None:
        synth = _live_synthesize
    p = await _claim_preconnected()
    if p is None:
        return await synth(text, emotion, on_packet, label=label)

    tag = f"[TTS] {label}: " if label else "[TTS] "
    sent = 0
    s0 = time.monotonic()
    retry = False

    async def _counted(data):
        nonlocal sent
        await on_packet(data)
        sent += 1

    try:
        log.info(f"{tag}предконнект: синтез на заранее открытой сессии")
        async with asyncio.timeout(_live_timeout(text)):
            await _pump_session(p.session, text, emotion, _counted)
        if p.key:
            mark_key_used(p.key)
        log.info(f"{tag}синтез за {time.monotonic()-s0:.1f}с | {sent} пакетов "
                 f"(без коннекта)")
    except Exception as e:
        global _client
        _client = None
        if sent == 0:
            log.warning(f"{tag}предконнект: сессия упала до первого пакета "
                        f"({e!r}) — фолбэк на обычный синтез")
            retry = True
        else:
            log.error(f"{tag}Ошибка синтеза (предконнект) после {sent} "
                      f"пакетов: {e!r}")
    finally:
        # Держатель закроет сессию и вернёт слот семафора — до фолбэка:
        # обычный синтез сам берёт слот, иначе ждал бы чужую стадию.
        p.release.set()
    if retry:
        return await synth(text, emotion, on_packet, label=label)
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
                            emotion: str, t0: float,
                            stop=None) -> int:
    """Гибрид быстрого старта БЕЗ пауз между предложениями.

    Первое предложение синтезируется отдельной быстрой сессией и уходит
    на устройство сразу; остальной текст стартует ВТОРОЙ сессией
    ПАРАЛЛЕЛЬНО — её ранние пакеты буферизуются и вытекают строго после
    пакетов первой, поэтому порядок сохранён. Каждый продюсер кладёт
    sentinel None (в finally) — drain заканчивается сразу по концу потока.

    stop — опциональный callable(): вызывается МЕЖДУ пакетами drain-а.
    Вернул True → озвучка обрывается: продюсеры отменяются, пакеты не
    отправляются, возвращаем -1 (означает «прервано»).
    """

    send_audio = _make_audio_sender(websocket, device_id)

    q_first: asyncio.Queue = asyncio.Queue()
    q_rest: asyncio.Queue = asyncio.Queue()

    async def _produce(text: str, q: "asyncio.Queue", stage: int) -> None:
        """Продюсер стадии: синтез + гарантированный sentinel конца потока."""
        log.info(f"[TTS] стадия {stage}: старт (+{time.monotonic()-t0:.1f}с от начала, {len(text)} симв)")
        try:
            # Стадия 1 — из предбанника (п.3): коннект открыт заранее,
            # первая стадия не платит за handshake.
            synth = (_live_synthesize_preferred if stage == 1
                     else _live_synthesize)
            await synth(text, emotion, q.put, label=f"стадия {stage}")
        finally:
            await q.put(None)

    task_first = asyncio.create_task(_produce(first, q_first, 1))
    task_rest  = asyncio.create_task(_produce(rest,  q_rest, 2))

    sent = 0
    first_logged = False

    async def drain(q: "asyncio.Queue", stage: int) -> bool:
        """Выкачивает очередь стадии на устройство до sentinel-а конца.

        Раньше выход по таймауту БРОСАЛ остаток очереди, а заблокированное
        ожидание не замечало завершения продюсера — отсюда лишние секунды
        после «синтез за …» обеих стадий. Теперь конец потока приходит
        sentinel-ом немедленно.
        → True — стадия дочитана; False — прервана (stop=True)."""
        nonlocal sent, first_logged
        warned = False
        while True:
            if stop is not None and stop():
                log.info(f"[TTS] two-stage: стадия {stage} — прервано по стоп-сигналу")
                return False
            try:
                data = await asyncio.wait_for(q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                # Poll stop-а и тихий повтор; от длинного wait_for отказались,
                # чтобы «стоп» срабатывал быстро. Продюсер, завернившись,
                # всегда ставит sentinel — конец потока не теряется.
                continue
            if data is None:
                log.info(f"[TTS] стадия {stage}: поток завершён (+{time.monotonic()-t0:.1f}с)")
                return True
            try:
                await send_audio(data)
            except Exception as e:
                log.error(f"[TTS] Отправка: {e}")
                return True
            sent += 1
            if not first_logged:
                log.info(f"[TTS] первый звук за {time.monotonic()-t0:.1f}с")
                first_logged = True

    # Фаза 1: первая сессия (быстрый старт); Фаза 2 — вторая.
    ok1 = await drain(q_first, 1)
    ok2 = await drain(q_rest, 2)

    # Прервано по стоп-сигналу — снимаем продюсеров и возвращаем -1.
    stopped = (stop is not None) and stop()
    if not (ok1 and ok2) or stopped:
        for t in (task_first, task_rest):
            if not t.done():
                t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug(f"[TTS] producer: {e}")
        return -1

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


async def _send_end(websocket, device_id: str, listen: float | None = None):
    try:
        payload = {"type": "tts_end", "device_id": device_id}
        if listen is not None:
            payload["listen"] = listen
        await websocket.send(json.dumps(payload))
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
    stop=None,
    listen: float | None = None,
):
    """Единая точка входа озвучки (голос и все фоновые пути).

    Обработка одинаковая для обоих путей вызова:
      main.py → stream_llm_to_tts → сюда; ws_handlers → напрямую сюда.
    Очистка текста и удаление [ТОН:] применяются здесь же.

    Схема: короткий текст — одна Live-сессия; длинный — гибрид быстрого
    старта (_stream_two_stage): первое предложение звучит сразу (<3с),
    остальное синтезируется параллельно без слышимых пауз.

    stop — опциональный callable(): вернул True → озвучка прекращается
    (между пакетами). Полезно для прерывания длинного списка голосом."""
    from modules.state import tts_stop_requested
    if stop is None:
        stop = lambda: tts_stop_requested(device_id)

    _, text = _extract_tone_tag(text)

    text = _clean_tts_text(text)
    if not text or len(text.strip()) < MIN_TTS_LEN:
        return

    t0 = time.monotonic()
    parts = _split_speech(text)
    sent = 0
    if len(parts) <= 1:
        sent = await _synthesize_and_stream(text, websocket, device_id, emotion)
    else:
        sent = await _stream_two_stage(
            parts[0], " ".join(parts[1:]), websocket, device_id, emotion, t0, stop)
    await _send_end(websocket, device_id, listen=listen)
    if sent == -1:
        log.info(f"[TTS] Озвучка прервана по стоп-сигналу | {device_id}")
    else:
        log.info(f"[TTS] Готово за {time.monotonic()-t0:.1f}с | {sent} пакетов")


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
        full_text = ""

        async for token in _llm_stream(
            contents,
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            safety=False,
            thinking=False,
            chain=VOICE_MODEL_CHAIN,
        ):
            full_text += token

        mark_key_used(api_key)

        log.info(f"[TTS stream] LLM за {time.monotonic()-t0:.1f}с")

        # Парсим эмоцию
        for line in full_text.split("\n"):
            if line.strip().startswith("EMOTION:"):
                emotion = line.strip().replace("EMOTION:", "").strip()

        clean = re.sub(r'EMOTION:\w+', '', full_text).strip()

        if clean and websocket:
            await stream_tts_to_device(clean, websocket, device_id, emotion=emotion)

        return full_text, emotion

    except Exception as e:
        log.error(f"[TTS stream] {e}")

        # Fallback: обычная генерация
        try:
            full_text = await _llm_generate(
                contents,
                system=system,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                safety=False,
                thinking=False,
                chain=VOICE_MODEL_CHAIN,
            )
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