"""core/voice.py — голос (выход).

Простая и надёжная реализация без jitter buffer.
PCM пишется в bytearray, callback читает по мере воспроизведения.
"""

import logging
import struct
import threading
import time

log = logging.getLogger("sakura.voice")

try:    import sounddevice as sd
except ImportError: sd = None
try:    import numpy as np
except ImportError: np = None

import config

_BLOCKSIZE = 2048   # ~85мс при 24кГц — стабильнее на Windows


def find_output_device():
    if not sd:
        return None, "sounddevice недоступен"
    preferred = getattr(config, "AUDIO_OUTPUT_DEVICE", "default")
    if isinstance(preferred, int) or (isinstance(preferred, str) and str(preferred).isdigit()):
        dev_id = int(preferred)
        try:
            info = sd.query_devices(dev_id)
            return dev_id, info["name"]
        except Exception:
            pass
    if str(preferred).lower() in ("default", ""):
        try:
            info = sd.query_devices(kind="output")
            for i, dev in enumerate(sd.query_devices()):
                if dev["name"] == info["name"] and dev["max_output_channels"] > 0:
                    return i, info["name"]
            return None, info["name"]
        except Exception:
            return None, "неизвестно"
    try:
        pref = str(preferred).lower()
        for i, dev in enumerate(sd.query_devices()):
            if pref in dev["name"].lower() and dev["max_output_channels"] > 0:
                return i, dev["name"]
    except Exception:
        pass
    return None, "дефолт"


def list_output_devices() -> str:
    if not sd:
        return "sounddevice недоступен"
    try:
        lines = []
        default_o = sd.default.device[1]
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0:
                mark = " <- ДЕФОЛТ" if i == default_o else ""
                lines.append(f"  [{i}] {dev['name']}{mark}")
        return "\n".join(lines)
    except Exception as e:
        return f"ошибка: {e}"


def decode_binary_chunk(data: bytes):
    if len(data) < 4:
        return b"", 24000
    return data[4:], struct.unpack("<I", data[:4])[0]


class Player:
    """
    Простой потоковый плеер без jitter buffer.
    feed() добавляет PCM в очередь, callback читает синхронно.
    """

    def __init__(self, rate: int):
        self._rate   = rate
        self._buf    = bytearray()
        self._lock   = threading.Lock()
        self._stream = None
        self._stream_lock = threading.Lock()
        self._open_stream()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _open_stream(self):
        dev_id, name = find_output_device()
        with self._stream_lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            for dev in ([dev_id] if dev_id is not None else []) + [None]:
                try:
                    s = sd.RawOutputStream(
                        samplerate=self._rate,
                        channels=1,
                        dtype="int16",
                        blocksize=_BLOCKSIZE,
                        device=dev,
                        callback=self._callback,
                        latency="low",
                    )
                    s.start()
                    self._stream = s
                    log.info(f"[voice] Аудио-выход открыт: {name if dev == dev_id else 'дефолт'}")
                    log.info(f"[voice] Все устройства вывода:\n{list_output_devices()}")
                    break
                except Exception as e:
                    log.warning(f"[voice] Устройство {dev}: {e}")

    def _watchdog(self):
        time.sleep(3.0)
        while True:
            time.sleep(5.0)
            try:
                with self._stream_lock:
                    alive = self._stream and self._stream.active
                if not alive:
                    log.warning("[voice] Стрим упал — переоткрываем")
                    self._open_stream()
            except Exception:
                pass

    def _callback(self, outdata, frames, time_info, status):
        need = frames * 2
        with self._lock:
            n = min(need, len(self._buf))
            if n:
                outdata[:n] = bytes(self._buf[:n])
                del self._buf[:n]
            else:
                n = 0
        if n < need:
            outdata[n:] = b"\x00" * (need - n)

    def feed(self, pcm: bytes):
        """Добавляет PCM в буфер воспроизведения."""
        if not pcm:
            return
        with self._lock:
            self._buf.extend(pcm)

    def feed_binary(self, data: bytes):
        """Бинарный чанк: 4 байта заголовок + PCM."""
        pcm, _ = decode_binary_chunk(data)
        if pcm:
            self.feed(pcm)

    def flush(self):
        """Конец фразы — ничего не делаем, буфер доиграет сам."""
        pass

    def interrupt(self):
        """Баржинг — очищаем буфер."""
        with self._lock:
            self._buf.clear()

    def switch_device(self, device_id=None):
        if device_id is not None:
            import os
            os.environ["AUDIO_OUTPUT_DEVICE"] = str(device_id)
        self._open_stream()

    def is_playing(self) -> bool:
        with self._lock:
            return len(self._buf) > 0

    def get_buffer_ms(self) -> float:
        with self._lock:
            return (len(self._buf) // 2) / self._rate * 1000