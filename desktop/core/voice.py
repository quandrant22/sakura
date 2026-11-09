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

from desktop.core import config

_BLOCKSIZE = 2048   # ~85мс при 24кГц — стабильнее на Windows
_PREROLL_MAX_WAIT = 0.6   # сек с первого чанка — дальше предзаполнения не ждём


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


def find_cable_device() -> tuple[int | None, str]:
    """Поиск виртуального кабеля (VB-Audio Virtual Cable) с приоритетом WASAPI стерео."""
    if not sd:
        return None, ""
    try:
        devices = sd.query_devices()
        apis = sd.query_hostapis()
        # 1. Приоритет: WASAPI со стерео (2 канала), совпадает с нативным форматом VB-Audio Cable
        for i, d in enumerate(devices):
            if "cable input" in d["name"].lower() and d["max_output_channels"] >= 2:
                api_name = apis[d["hostapi"]]["name"].lower()
                if "wasapi" in api_name:
                    return i, d["name"]
        # 2. DirectSound со стерео
        for i, d in enumerate(devices):
            if "cable input" in d["name"].lower() and d["max_output_channels"] >= 2:
                api_name = apis[d["hostapi"]]["name"].lower()
                if "directsound" in api_name:
                    return i, d["name"]
        # 3. Любое устройство CABLE Input с >= 2 каналами
        for i, d in enumerate(devices):
            if "cable input" in d["name"].lower() and d["max_output_channels"] >= 2:
                return i, d["name"]
        # 4. Фолбэк на любое устройство CABLE Input
        for i, d in enumerate(devices):
            if "cable input" in d["name"].lower() and d["max_output_channels"] > 0:
                return i, d["name"]
    except Exception as e:
        log.warning(f"[voice] Ошибка поиска Virtual Cable: {e}")
    return None, ""


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


def resample_pcm16(pcm: bytes, src: int, dst: int) -> bytes:
    """Пересчёт PCM 16 бит моно из src Гц в dst Гц (линейная интерполяция)."""
    import numpy as np
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32)
    if not len(x) or src <= 0 or src == dst:
        return pcm
    n = max(1, round(len(x) * dst / src))
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return np.clip(np.round(y), -32768, 32767).astype("<i2").tobytes()


def decode_binary_chunk(data: bytes):
    if len(data) < 4:
        return b"", 24000
    return data[4:], struct.unpack("<I", data[:4])[0]


class Player:
    """
    Простой потоковый плеер без jitter buffer.
    feed() добавляет PCM в очередь, callback читает синхронно.
    """

    # Значения по умолчанию (экземпляр, созданный без __init__, тоже работает)
    _preroll_bytes = 0
    _first_chunk_ts = 0.0
    _started = False
    _ended = False
    _format_logged = False
    _ur_count = _ur_total = _ur_max = _ur_cur = 0
    _cable_stream = None
    _cable_lock = None
    _cable_buf = None

    def __init__(self, rate: int):
        self._rate   = rate
        self._buf    = bytearray()
        self._lock   = threading.Lock()
        self._stream = None
        self._stream_lock = threading.Lock()
        self.last_feed_ts = 0.0   # time.monotonic() последнего feed/feed_binary
        # Предзаполнение: старт звука, когда накоплено PLAYER_PREROLL_MS
        # (или пришёл tts_end, или прошло _PREROLL_MAX_WAIT с первого чанка)
        self._preroll_bytes = int(getattr(config, "PLAYER_PREROLL_MS", 0) * rate / 1000) * 2
        self._cable_stream = None
        self._cable_lock = threading.Lock()
        self._cable_buf = bytearray()
        self._reset_response()
        self._open_stream()
        self._open_cable_stream()
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

    def _open_cable_stream(self):
        if not sd:
            return
        cable_idx, cable_name = find_cable_device()
        if cable_idx is None:
            log.warning("[voice] Виртуальный кабель не найден среди устройств вывода")
            return
        with self._cable_lock:
            if self._cable_stream:
                try:
                    self._cable_stream.stop()
                    self._cable_stream.close()
                except Exception:
                    pass
                self._cable_stream = None
            try:
                # 48000 Hz, 2 канала (Stereo), blocksize 1024 сэмплов
                # Полное совпадение с нативной конфигурацией VB-Audio Cable (ch 2, 48000 Hz, 1024 smp)
                self._cable_stream = sd.RawOutputStream(
                    samplerate=48000,
                    channels=2,
                    dtype="int16",
                    blocksize=1024,
                    device=cable_idx,
                    callback=self._cable_callback,
                    latency="low",
                )
                self._cable_stream.start()
                log.info(f"[voice] Вывод в виртуальный кабель Discord открыт (WASAPI 48кГц Стерео, блок 1024): dev {cable_idx} ({cable_name})")
            except Exception as e:
                log.warning(f"[voice] Кабель Discord (dev {cable_idx}) не открыт: {e}")

    def _cable_callback(self, outdata, frames, time_info, status):
        need = frames * 4  # 2 channels * 2 bytes/sample
        n = 0
        with self._lock:
            n = min(need, len(self._cable_buf))
            if n:
                outdata[:n] = bytes(self._cable_buf[:n])
                del self._cable_buf[:n]
        if n < need:
            outdata[n:] = b"\x00" * (need - n)

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
            try:
                with self._cable_lock:
                    cable_alive = self._cable_stream and self._cable_stream.active
                if not cable_alive:
                    log.warning("[voice] Стрим кабеля упал — переоткрываем")
                    self._open_cable_stream()
            except Exception:
                pass

    def _reset_response(self):
        """Счётчики одного ответа (под self._lock или в __init__)."""
        self._format_logged = False  # формат и частота ответа — один раз в лог
        self._first_chunk_ts = 0.0
        self._started = False     # звук этого ответа уже пошёл
        self._ended   = False     # tts_end получен
        self._ur_count = 0        # разрывов (underrun) за ответ
        self._ur_total = 0        # байт тишины в разрывах
        self._ur_max   = 0        # самая длинная пауза, байт
        self._ur_cur   = 0        # текущая пауза, байт

    def _bytes_ms(self, n: int) -> int:
        return int(n / 2 / self._rate * 1000)

    def _finish_response(self):
        """Конец ответа: один INFO о разрывах, сброс счётчиков (под self._lock)."""
        if self._started and self._ur_count:
            log.info(f"[voice] underrun: {self._ur_count} раз, всего "
                     f"{self._bytes_ms(self._ur_total)} мс, макс. пауза "
                     f"{self._bytes_ms(self._ur_max)} мс")
        self._reset_response()

    def _callback(self, outdata, frames, time_info, status):
        need = frames * 2
        with self._lock:
            n = 0
            if not self._started and self._buf:
                # Ждём предзаполнения (по умолчанию выключено)
                if (len(self._buf) >= self._preroll_bytes or self._ended
                        or time.monotonic() - self._first_chunk_ts >= _PREROLL_MAX_WAIT):
                    self._started = True
            if self._started:
                n = min(need, len(self._buf))
                if n:
                    outdata[:n] = bytes(self._buf[:n])
                    del self._buf[:n]
                if n < need and not self._ended:
                    # Звук шёл, а данных не хватило — разрыв
                    if self._ur_cur == 0:
                        self._ur_count += 1
                    self._ur_cur += need - n
                    self._ur_total += need - n
                    self._ur_max = max(self._ur_max, self._ur_cur)
                elif n == need:
                    self._ur_cur = 0
                if self._ended and not self._buf:
                    self._finish_response()
        if n < need:
            outdata[n:] = b"\x00" * (need - n)

    def feed(self, pcm: bytes, rate: int | None = None, fmt: str = "json"):
        """Добавляет PCM (16 бит, моно) в буфер. rate — частота чанка: если она не совпадает
        с частотой выхода, звук пересчитывается, иначе голос звучит выше или ниже («другой голос»)."""
        if not pcm:
            return
        rate = int(rate) if rate else self._rate
        if rate != self._rate:
            pcm = resample_pcm16(pcm, rate, self._rate)
        with self._lock:
            if not self._format_logged:
                self._format_logged = True
                log.info("[voice] ответ: %s, %d Гц%s", fmt, rate,
                         "" if rate == self._rate else f" → пересчёт в {self._rate} Гц")
            if self._ended:
                # Новый ответ после tts_end, а старый ещё не доигран
                self._finish_response()
            if not self._started and not self._first_chunk_ts:
                self._first_chunk_ts = time.monotonic()
            import numpy as np
            # 1. Громкость наушников мастера (микшер VOICE_VOLUME 0..100%)
            vol_pct = getattr(config, "VOICE_VOLUME", 50)
            gain = max(0.0, min(1.0, vol_pct / 100.0))
            if gain != 1.0:
                pcm_arr = np.frombuffer(pcm, dtype=np.int16)
                pcm_head = (pcm_arr * gain).astype(np.int16).tobytes()
            else:
                pcm_head = pcm
            self._buf.extend(pcm_head)

            # 2. Вывод в кабель Discord ТОЛЬКО при включённом режиме звонка (Call Mode)!
            from desktop.core.features import get_call_mode_manager
            cm = get_call_mode_manager()
            cable_s = getattr(self, '_cable_stream', None)
            if cm.active and cable_s and getattr(cable_s, 'active', False):
                pcm_arr = np.frombuffer(pcm, dtype=np.int16)
                # Переводим 24кГц моно -> 48кГц стерео для виртуального кабеля Discord
                pcm_48k = np.repeat(pcm_arr, 2)
                c_pct = getattr(config, "CABLE_VOLUME", 85)
                c_gain = max(0.0, min(1.0, c_pct / 100.0))
                if c_gain != 1.0:
                    pcm_scaled = (pcm_48k * c_gain).astype(np.int16)
                else:
                    pcm_scaled = pcm_48k
                pcm_stereo = np.column_stack((pcm_scaled, pcm_scaled)).ravel().tobytes()
                if getattr(self, '_cable_buf', None) is not None:
                    self._cable_buf.extend(pcm_stereo)
            self.last_feed_ts = time.monotonic()

    def feed_binary(self, data: bytes):
        """Бинарный чанк: 4 байта заголовок (частота, little-endian) + PCM."""
        pcm, rate = decode_binary_chunk(data)
        if pcm:
            self.feed(pcm, rate, fmt="binary")

    def flush(self):
        """Конец фразы (tts_end): буфер доиграет сам, затем итог по разрывам."""
        with self._lock:
            self._ended = True
            if not self._buf:
                self._finish_response()

    def interrupt(self):
        """Баржинг — очищаем буфер."""
        with self._lock:
            self._buf.clear()
            self._cable_buf.clear()
            self._finish_response()

    def buffer_bytes(self) -> int:
        with self._lock:
            return len(self._buf)

    def switch_device(self, device_id=None):
        if device_id is not None:
            import os
            os.environ["AUDIO_OUTPUT_DEVICE"] = str(device_id)
        self._open_stream()

    def is_playing(self) -> bool:
        with self._lock:
            return len(self._buf) > 0

    def is_drained(self) -> bool:
        """В буфере нет непроигранного звука."""
        with self._lock:
            return len(self._buf) == 0

    def get_buffer_ms(self) -> float:
        with self._lock:
            return (len(self._buf) // 2) / self._rate * 1000
