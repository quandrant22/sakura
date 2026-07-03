"""
core/music_listener.py — захват системного аудио для эквалайзера.

Использует WASAPI loopback (Windows) через sounddevice или pyaudiowpatch.
Захватывает то что играет через динамики/наушники и передаёт
спектр в эквалайзер оверлея.

Установка (если не работает через sounddevice):
  pip install pyaudiowpatch
"""

import logging
import threading
import time
from typing import Optional

log = logging.getLogger("sakura.music_listener")

# Количество полос эквалайзера
N_BARS   = 8
# Частотные диапазоны для каждой полосы (Hz)
FREQ_BANDS = [
    (20,   100),   # суббас
    (100,  250),   # бас
    (250,  500),   # нижняя середина
    (500,  1000),  # середина
    (1000, 2000),  # верхняя середина
    (2000, 4000),  # присутствие
    (4000, 8000),  # блеск
    (8000, 16000), # воздух
]

_running  = False
_thread: Optional[threading.Thread] = None
_callback = None   # вызывается с list[float] длиной N_BARS
_smoothed = [0.0] * N_BARS  # сглаженные значения


def set_callback(fn):
    """Устанавливает функцию которая получает уровни полос."""
    global _callback
    _callback = fn


def _compute_bars(audio_chunk, sample_rate: int) -> list[float]:
    """FFT → уровни по полосам частот."""
    import numpy as np

    # Моно
    if audio_chunk.ndim > 1:
        audio_chunk = audio_chunk.mean(axis=1)

    n = len(audio_chunk)
    if n < 512:
        return [0.0] * N_BARS

    # Применяем окно Хэннинга
    window = np.hanning(n)
    windowed = audio_chunk * window

    # FFT
    fft = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, d=1.0/sample_rate)

    import math as _math

    # Фиксированный порог вместо нормализации по максимуму
    # Иначе тихая музыка выглядит так же как громкая
    ref = max(float(np.percentile(fft, 95)), 1.0)

    bars = []
    for low, high in FREQ_BANDS:
        mask = (freqs >= low) & (freqs < high)
        if mask.any():
            energy = float(np.mean(fft[mask])) / ref
            # Усиливаем чувствительность
            level = max(0.0, min(1.0, energy * 2.5))
            # Логарифм для естественного восприятия
            level = max(0.0, min(1.0, _math.log10(1 + level * 9)))
        else:
            level = 0.0
        bars.append(level)

    return bars


def _smooth_bars(new_bars: list[float], attack=0.8, release=0.15) -> list[float]:
    """Сглаживание: быстрый рост, медленный спад."""
    global _smoothed
    result = []
    for i, (new, old) in enumerate(zip(new_bars, _smoothed)):
        if new > old:
            s = old + (new - old) * attack
        else:
            s = old + (new - old) * release
        result.append(s)
    _smoothed = result
    return result


def _run_sounddevice():
    """Захват через sounddevice WASAPI loopback."""
    try:
        import sounddevice as sd
        import numpy as np

        # Ищем WASAPI loopback устройство
        devices    = sd.query_devices()
        loopback_id = None

        for i, d in enumerate(devices):
            name = d['name'].lower()
            if d['max_input_channels'] > 0 and (
                'loopback' in name or
                'stereo mix' in name or
                'что слышит' in name or
                'what u hear' in name
            ):
                loopback_id = i
                log.info(f"[music] WASAPI Loopback: [{i}] {d['name']}")
                break

        if loopback_id is None:
            # Пробуем default output как loopback через WASAPI
            try:
                default_out = sd.default.device[1]
                d = sd.query_devices(default_out)
                # На Windows с WASAPI можно открыть output как input
                loopback_id = default_out
                log.info(f"[music] Пробуем default output как loopback: {d['name']}")
            except Exception:
                log.warning("[music] Loopback устройство не найдено. Включи 'Stereo Mix' в настройках звука Windows.")
                return

        CHUNK       = 512  # меньше буфер = быстрее реакция
        SAMPLE_RATE = 44100

        def audio_callback(indata, frames, time_info, status):
            if not _running:
                return
            try:
                bars = _compute_bars(indata.copy(), SAMPLE_RATE)
                smooth = _smooth_bars(bars)
                if _callback:
                    _callback(smooth)
            except Exception:
                pass

        with sd.InputStream(
            device=loopback_id,
            channels=2,
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK,
            callback=audio_callback,
            latency='low',
        ):
            log.info("[music] Слушаю системный аудио...")
            while _running:
                time.sleep(0.1)

    except Exception as e:
        log.error(f"[music] sounddevice loopback: {e}")
        _run_pyaudiowpatch()


def _run_pyaudiowpatch():
    """Fallback: захват через pyaudiowpatch (гарантированный WASAPI loopback)."""
    try:
        import pyaudiowpatch as pyaudio
        import numpy as np

        pa = pyaudio.PyAudio()

        # Ищем WASAPI loopback устройство по умолчанию
        wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = wasapi_info["defaultOutputDevice"]
        device_info = pa.get_device_info_by_index(default_out)

        if not device_info.get("isLoopbackDevice", False):
            # Ищем loopback версию
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d.get("name") == device_info["name"] + " [Loopback]":
                    device_info = d
                    default_out = i
                    break

        CHUNK       = 512  # меньше буфер = быстрее реакция
        SAMPLE_RATE = int(device_info["defaultSampleRate"])
        CHANNELS    = int(device_info["maxInputChannels"])

        log.info(f"[music] pyaudiowpatch: {device_info['name']} @ {SAMPLE_RATE}Hz")

        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            frames_per_buffer=CHUNK,
            input=True,
            input_device_index=default_out,
        )

        while _running:
            try:
                raw  = stream.read(CHUNK, exception_on_overflow=False)
                audio = np.frombuffer(raw, dtype=np.float32)
                bars  = _compute_bars(audio, SAMPLE_RATE)
                smooth = _smooth_bars(bars)
                if _callback:
                    _callback(smooth)
            except Exception:
                pass

        stream.stop_stream()
        stream.close()
        pa.terminate()

    except ImportError:
        log.warning("[music] pyaudiowpatch не установлен. pip install pyaudiowpatch")
    except Exception as e:
        log.error(f"[music] pyaudiowpatch: {e}")


def start(callback=None):
    """Запускает захват системного аудио в фоновом потоке."""
    global _running, _thread, _callback

    if callback:
        _callback = callback

    if _running:
        return

    _running = True
    _thread  = threading.Thread(target=_run_sounddevice, daemon=True, name="music-listener")
    _thread.start()
    log.info("[music] Захват системного аудио запущен")


def stop():
    global _running
    _running = False
    log.info("[music] Захват остановлен")


def is_running() -> bool:
    return _running