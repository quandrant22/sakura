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
from desktop.core.voice_tuning import pcm_level

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
    # Колбэк звука не пишет в журнал и не вызывает чужой код: он отмечает события, а поток-уведомитель
    # (_notify_loop) пишет итог разрывов и зовёт on_start/on_end, когда звук дошёл до колонок / доиграл.
    level = 0.0              # громкость реально выведенного звука 0..1 (последний блок)
    _latency = 0.0           # задержка устройства вывода, с (если time_info её не даёт)
    _resp_seq = 0            # номер ответа: растёт с первым чанком и при interrupt()
    _sound_seq = 0           # ответ, чей звук уже пошёл в устройство
    _last_sound_at = 0.0     # когда доиграет последний выведенный звук (monotonic)
    _pending_start = None    # (seq, когда звук дойдёт до колонок)
    _pending_end = None      # (seq, когда звук доиграет)
    _pending_report = None   # итог разрывов для журнала
    _notify = None
    on_start = None          # on_start(seq) — звук ответа пошёл из колонок
    on_end = None            # on_end(seq) — звук ответа доиграл (после tts_end)

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
        self._reset_response()
        self._notify = threading.Event()
        self._open_stream()
        threading.Thread(target=self._watchdog, daemon=True).start()
        threading.Thread(target=self._notify_loop, daemon=True, name="player-notify").start()

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
                    try:
                        self._latency = max(0.0, float(s.latency))
                    except (TypeError, ValueError):
                        self._latency = 0.0
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

    def _finish_response(self, quiet: bool = False):
        """Конец ответа: итог разрывов, сброс счётчиков (под self._lock). quiet — из колбэка звука:
        итог пишет в журнал уведомитель, а не колбэк."""
        if self._started and self._ur_count:
            report = (self._ur_count, self._bytes_ms(self._ur_total), self._bytes_ms(self._ur_max))
            if quiet:
                self._pending_report = report
            else:
                self._log_underrun(report)
        self._reset_response()

    @staticmethod
    def _log_underrun(report):
        log.info(f"[voice] underrun: {report[0]} раз, всего {report[1]} мс, макс. пауза {report[2]} мс")

    def _out_delay(self, time_info) -> float:
        """Сколько звук идёт от колбэка до колонок: из time_info, иначе задержка потока."""
        try:
            d = float(time_info.outputBufferDacTime - time_info.currentTime)
            if time_info.currentTime > 0 and 0.0 <= d < 1.0:
                return d
        except (AttributeError, TypeError, ValueError):
            pass
        return self._latency

    def _callback(self, outdata, frames, time_info, status):
        need = frames * 2
        chunk = b""
        signal = False
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
                    chunk = bytes(self._buf[:n])
                    outdata[:n] = chunk
                    del self._buf[:n]
                    out_at = time.monotonic() + self._out_delay(time_info)
                    self._last_sound_at = out_at + n / 2 / self._rate
                    if self._sound_seq != self._resp_seq:
                        # Первый звук ответа: speaking — когда он дойдёт до колонок, а не при приходе чанка.
                        self._sound_seq = self._resp_seq
                        self._pending_start = (self._resp_seq, out_at)
                        signal = True
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
                    # Доиграл: idle — когда последний блок выйдет из устройства.
                    self._pending_end = (self._resp_seq, self._last_sound_at)
                    self._finish_response(quiet=True)
                    signal = True
        if n < need:
            outdata[n:] = b"\x00" * (need - n)
        self.level = pcm_level(chunk) if chunk else 0.0
        if signal and self._notify is not None:
            self._notify.set()

    # ── уведомления (поток player-notify) ──────────────────────────────
    @property
    def resp_seq(self) -> int:
        return self._resp_seq

    def _notify_loop(self):
        while True:
            self._notify.wait()
            self._notify.clear()
            try:
                self._dispatch(wait=True)
            except Exception:  # noqa: BLE001
                log.exception("[voice] уведомление плеера")

    def _dispatch(self, wait: bool = False):
        """Итог разрывов — в журнал; on_start/on_end — в момент выхода звука (wait=False — только наступившие)."""
        with self._lock:
            report, self._pending_report = self._pending_report, None
        if report:
            self._log_underrun(report)
        for kind in ("start", "end"):
            attr = "_pending_" + kind
            with self._lock:
                ev = getattr(self, attr)
            if ev is None:
                continue
            delay = ev[1] - time.monotonic()
            if delay > 0:
                if not wait:
                    continue
                time.sleep(delay)
            with self._lock:
                if getattr(self, attr) != ev:
                    continue  # снято interrupt() или заменено
                setattr(self, attr, None)
                current = ev[0] == self._resp_seq
            cb = self.on_start if kind == "start" else self.on_end
            if current and cb is not None:
                cb(ev[0])

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
                self._resp_seq += 1   # первый чанк нового ответа
            self._buf.extend(pcm)
            self.last_feed_ts = time.monotonic()

    def feed_binary(self, data: bytes):
        """Бинарный чанк: 4 байта заголовок (частота, little-endian) + PCM."""
        pcm, rate = decode_binary_chunk(data)
        if pcm:
            self.feed(pcm, rate, fmt="binary")

    def flush(self):
        """Конец фразы (tts_end): буфер доиграет сам (конец отметит колбэк), затем итог по разрывам.
        Буфер уже пуст — звук доиграл раньше (или его не было): конец — когда доиграет хвост в устройстве."""
        with self._lock:
            self._ended = True
            if not self._buf:
                self._pending_end = (self._resp_seq, max(time.monotonic(), self._last_sound_at))
                self._finish_response()
        if self._notify is not None:
            self._notify.set()

    def interrupt(self):
        """Баржинг — очищаем буфер; отложенные «звук пошёл/доиграл» прерванного ответа не придут."""
        with self._lock:
            self._buf.clear()
            self._finish_response()
            self._resp_seq += 1
            self._pending_start = self._pending_end = None
            self.level = 0.0

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
