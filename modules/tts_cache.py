"""Кэш озвученных фраз: PCM в памяти (LRU) и на диске (config.TTS_CACHE_DIR).

Ключ — (модель озвучки, голос, стиль-префикс, текст): смена любого из них
даёт новый ключ, и фраза синтезируется заново. Отправка на устройство —
тем же путём, что обычная озвучка: пакеты tts_chunk и в конце tts_end.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict

import config
import modules.tts_server as tts

log = logging.getLogger(__name__)

MEM_MAX = 64
# Пауза между синтезами при прогреве — не забивать Live API на старте.
WARMUP_PAUSE_S = 1.0
# 0.1с звука при 24кГц 16 бит моно — размер пакета при отправке из кэша.
CHUNK_BYTES = tts.TTS_SAMPLE_RATE * 2 // 10

_mem: "OrderedDict[str, bytes]" = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def cache_key(text: str) -> str:
    raw = "\x1f".join((tts.TTS_MODEL, tts.TTS_VOICE, tts._tts_prefix(), text))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _path(key: str) -> str:
    return os.path.join(config.TTS_CACHE_DIR, f"{key}.pcm")


def _remember(key: str, pcm: bytes) -> None:
    _mem[key] = pcm
    _mem.move_to_end(key)
    while len(_mem) > MEM_MAX:
        _mem.popitem(last=False)


def _read_disk(key: str) -> bytes | None:
    try:
        with open(_path(key), "rb") as f:
            return f.read() or None
    except OSError:
        return None


def _write_disk(key: str, pcm: bytes) -> None:
    try:
        os.makedirs(config.TTS_CACHE_DIR, exist_ok=True)
        tmp = _path(key) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(pcm)
        os.replace(tmp, _path(key))
    except OSError as e:
        log.warning(f"[tts_cache] не записан на диск: {type(e).__name__}: {e}")


async def _synthesize(text: str) -> bytes:
    buf = bytearray()

    async def _collect(data: bytes):
        buf.extend(data)
    try:
        await tts._live_synthesize(text, "спокойная", _collect, label="кэш",
                                   strict=True)
    except Exception:
        return b""
    return bytes(buf)


async def get_pcm(text: str) -> tuple[bytes | None, str]:
    """PCM фразы и источник: 'память' | 'диск' | 'синтез'. None — синтез не удался."""
    key = cache_key(text)
    pcm = _mem.get(key)
    if pcm is not None:
        _mem.move_to_end(key)
        return pcm, "память"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        pcm = _mem.get(key)
        if pcm is not None:
            return pcm, "память"
        pcm = await asyncio.to_thread(_read_disk, key)
        if pcm:
            _remember(key, pcm)
            return pcm, "диск"
        pcm = await _synthesize(text)
        if not pcm:
            return None, "синтез"
        _remember(key, pcm)
        await asyncio.to_thread(_write_disk, key, pcm)
        return pcm, "синтез"


async def play(text: str, websocket, device_id: str,
               t_ref: float | None = None) -> str:
    """Озвучить фразу из кэша (или синтезировать и положить в кэш).

    tts_end уходит всегда, даже если звук не получился. t_ref —
    time.monotonic() события, от которого меряется первый пакет (лог).
    Возвращает источник звука ('память' | 'диск' | 'синтез')."""
    source = "синтез"
    try:
        pcm, source = await get_pcm(text)
        if pcm:
            send = tts._make_audio_sender(websocket, device_id)
            for i in range(0, len(pcm), CHUNK_BYTES):
                await send(pcm[i:i + CHUNK_BYTES])
                if i == 0 and t_ref is not None:
                    log.info(f"[tts_cache] {text!r}: первый пакет через "
                             f"{(time.monotonic() - t_ref) * 1000:.0f}мс ({source})")
    except Exception as e:
        log.error(f"[tts_cache] {text!r}: {type(e).__name__}: {e}")
    finally:
        await tts._send_end(websocket, device_id)
    return source


async def warmup(phrases) -> None:
    """Предсинтез фраз без переменной части. Уже лежащие на диске — без синтеза."""
    phrases = list(phrases)
    made = 0
    for text in phrases:
        try:
            _, source = await get_pcm(text)
            if source == "синтез":
                made += 1
                await asyncio.sleep(WARMUP_PAUSE_S)
        except Exception as e:
            log.warning(f"[tts_cache] прогрев {text!r}: {type(e).__name__}: {e}")
    log.info(f"[tts_cache] прогрев: фраз {len(phrases)}, синтезировано {made}")
