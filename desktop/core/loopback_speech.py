"""desktop.core.loopback_speech — Захват входящей речи из Discord/видео (WASAPI Loopback).

Позволяет Сакуре слышать речь собеседников в звонках Discord / Telegram
и диалоги в YouTube/стримах без необходимости выводить звук на внешние колонки.

Архитектура:
1. Слушает поток воспроизведения Windows (наушники/динамики) через WASAPI Loopback (pyaudiowpatch).
2. Активируется только когда включён Call Mode или Watch Along (0% CPU в простое).
3. Игнорирует звук, когда сама Сакура говорит (защита от зацикливания / самопрослушивания).
4. Режет тишину (RMS / VAD) и отправляет накопленную речь в SpeechRecognizer (GigaAM / Vosk).
5. Направляет распознанный текст в:
   - CallModeManager.process_caller_speech (звонки Discord)
   - WatchAlongManager.feed_speech (совместный просмотр)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("sakura.loopback_speech")


class LoopbackSpeechListener:
    """Захватчик речи из системного вывода (наушников) через WASAPI Loopback."""

    def __init__(
        self,
        is_active_fn: Optional[Callable[[], bool]] = None,
        is_muted_fn: Optional[Callable[[], bool]] = None,
        on_caller_speech: Optional[Callable[[str], None]] = None,
        on_watch_speech: Optional[Callable[[str], None]] = None,
        recognizer: Optional[Any] = None,
    ):
        self.is_active_fn = is_active_fn or (lambda: False)
        self.is_muted_fn = is_muted_fn or (lambda: False)
        self.on_caller_speech = on_caller_speech
        self.on_watch_speech = on_watch_speech
        self.recognizer = recognizer
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="LoopbackSpeech")
        self._thread.start()
        log.info("[loopback_speech] Поток захвата входящего звука запущен")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("[loopback_speech] Поток захвата входящего звука остановлен")

    def _worker(self):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            log.warning("[loopback_speech] pyaudiowpatch не установлен — захват речи из наушников недоступен")
            return

        while self._running:
            # Спим пока ни один режим не включен
            if not self.is_active_fn():
                time.sleep(0.5)
                continue

            pa = None
            stream = None
            try:
                pa = pyaudio.PyAudio()
                wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_out = wasapi_info["defaultOutputDevice"]
                device_info = pa.get_device_info_by_index(default_out)

                if not device_info.get("isLoopbackDevice", False):
                    for i in range(pa.get_device_count()):
                        d = pa.get_device_info_by_index(i)
                        if d.get("name") == device_info["name"] + " [Loopback]":
                            device_info = d
                            default_out = i
                            break

                sample_rate = int(device_info["defaultSampleRate"])
                channels = int(device_info["maxInputChannels"])
                chunk_size = 1024

                stream = pa.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    frames_per_buffer=chunk_size,
                    input=True,
                    input_device_index=default_out,
                )

                log.info(
                    "[loopback_speech] Захват loopback открыт на '%s' (%s Гц, %s кан.)",
                    device_info.get("name"), sample_rate, channels
                )

                speech_frames: list[np.ndarray] = []
                silence_frames = 0
                max_silence = int(0.7 * (sample_rate / chunk_size))  # ~0.7 сек тишины
                min_speech = int(0.4 * (sample_rate / chunk_size))   # минимум 0.4 сек речи
                energy_threshold = 0.015  # RMS порог голоса

                while self._running and self.is_active_fn():
                    try:
                        raw = stream.read(chunk_size, exception_on_overflow=False)
                    except Exception:
                        continue

                    # Если Сакура сама говорит — сбрасываем и пропускаем, чтобы не слышать себя
                    if self.is_muted_fn():
                        speech_frames.clear()
                        silence_frames = 0
                        continue

                    audio_chunk = np.frombuffer(raw, dtype=np.float32)
                    if channels > 1:
                        audio_chunk = audio_chunk.reshape(-1, channels).mean(axis=1)

                    rms = float(np.sqrt(np.mean(audio_chunk**2))) if len(audio_chunk) else 0.0

                    if rms > energy_threshold:
                        speech_frames.append(audio_chunk)
                        silence_frames = 0
                    else:
                        if speech_frames:
                            speech_frames.append(audio_chunk)
                            silence_frames += 1
                            if silence_frames >= max_silence:
                                # Фраза завершилась
                                if len(speech_frames) >= min_speech:
                                    full_audio = np.concatenate(speech_frames)
                                    self._process_utterance(full_audio, sample_rate)
                                speech_frames.clear()
                                silence_frames = 0

            except Exception as e:
                log.warning("[loopback_speech] Ошибка в потоке захвата: %s", e)
                time.sleep(2.0)
            finally:
                if stream:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                if pa:
                    try:
                        pa.terminate()
                    except Exception:
                        pass

    def _process_utterance(self, audio: np.ndarray, orig_sr: int):
        """Ресемплинг в 16 кГц и передача в распознаватель."""
        if len(audio) == 0:
            return

        # Ресемплинг в 16000 Гц float32 для GigaAM / Vosk
        target_sr = 16000
        if orig_sr != target_sr:
            num_samples = int(len(audio) * target_sr / orig_sr)
            audio_16k = np.interp(
                np.linspace(0, len(audio) - 1, num_samples),
                np.arange(len(audio)),
                audio
            ).astype(np.float32)
        else:
            audio_16k = audio.astype(np.float32)

        # Ограничиваем фразу максимум 20 секундами
        if len(audio_16k) > target_sr * 20:
            audio_16k = audio_16k[: target_sr * 20]

        # Нормализация громкости
        max_val = np.max(np.abs(audio_16k))
        if max_val > 1e-4:
            audio_16k = audio_16k / max_val * 0.9

        rec = self.recognizer
        if not rec:
            from desktop.core.hearing import SpeechRecognizer
            try:
                rec = SpeechRecognizer()
                self.recognizer = rec
            except Exception as e:
                log.warning("[loopback_speech] Не удалось инициализировать SpeechRecognizer: %s", e)
                return

        try:
            text = rec.transcribe(audio_16k).strip()
        except Exception as e:
            log.warning("[loopback_speech] Ошибка распознавания: %s", e)
            return

        if not text:
            return

        log.info("[loopback_speech] Распознана речь из войса/видео: «%s»", text)

        from desktop.core.features import get_call_mode_manager, get_watch_along_manager
        cm = get_call_mode_manager()
        wa = get_watch_along_manager()

        if cm.active and self.on_caller_speech:
            self.on_caller_speech(text)

        if wa.active and self.on_watch_speech:
            self.on_watch_speech(text)
