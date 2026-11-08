"""desktop.core.loopback_speech — Захват входящей речи из Discord/видео (WASAPI Loopback).

Позволяет Сакуре слышать речь собеседников в звонках Discord / Telegram
и диалоги в YouTube/стримах без необходимости выводить звук на внешние колонки.

Архитектура:
1. Слушает поток воспроизведения Windows (наушники/динамики) через WASAPI Loopback (pyaudiowpatch).
2. Активируется только когда включён Call Mode или Watch Along (0% CPU в простое).
3. Игнорирует звук, когда сама Сакура говорит (защита от зацикливания / самопрослушивания).
4. Режет тишину нейросетевым Silero VAD (или RMS) и отправляет накопленную речь в SpeechRecognizer (GigaAM).
5. Направляет распознанный текст в:
   - CallModeManager.process_caller_speech (звонки Discord)
   - WatchAlongManager.feed_speech (совместный просмотр)
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

log = logging.getLogger("sakura.loopback_speech")


def resample_to_16k(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    """Качественный ресемплинг в 16000 Гц float32 с защитой от алиасинга."""
    if len(audio) == 0:
        return np.zeros(0, dtype=np.float32)
    if orig_sr == 16000:
        return audio.astype(np.float32)
    try:
        import torch
        import torchaudio.transforms as T
        resampler = T.Resample(orig_sr, 16000)
        t = torch.from_numpy(audio.astype(np.float32)).unsqueeze(0)
        return resampler(t).squeeze(0).numpy()
    except Exception:
        try:
            from scipy import signal
            num_samples = int(len(audio) * 16000 / orig_sr)
            return signal.resample(audio, num_samples).astype(np.float32)
        except Exception:
            num_samples = int(len(audio) * 16000 / orig_sr)
            return np.interp(
                np.linspace(0, len(audio) - 1, num_samples),
                np.arange(len(audio)),
                audio
            ).astype(np.float32)


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
            if not self.is_active_fn():
                time.sleep(0.3)
                continue

            pa = None
            stream = None
            try:
                pa = pyaudio.PyAudio()
                device_info = None

                # 1. Попытка получить WASAPI Loopback по умолчанию напрямую
                try:
                    device_info = pa.get_default_wasapi_loopback()
                except Exception as ex:
                    log.debug("[loopback_speech] get_default_wasapi_loopback(): %s", ex)

                # 2. Фолбэк поиск loopback устройства
                if device_info is None:
                    wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                    default_out = wasapi_info["defaultOutputDevice"]
                    dev = pa.get_device_info_by_index(default_out)
                    dev_name = dev.get("name", "")
                    for i in range(pa.get_device_count()):
                        d = pa.get_device_info_by_index(i)
                        if d.get("isLoopbackDevice", False) and (
                            d.get("name", "") == dev_name + " [Loopback]"
                            or dev_name in d.get("name", "")
                            or "[loopback]" in d.get("name", "").lower()
                        ):
                            device_info = d
                            break

                if device_info is None:
                    for i in range(pa.get_device_count()):
                        d = pa.get_device_info_by_index(i)
                        if d.get("isLoopbackDevice", False):
                            device_info = d
                            break

                if device_info is None:
                    log.warning("[loopback_speech] WASAPI Loopback устройство не найдено")
                    time.sleep(2.0)
                    continue

                sample_rate = int(device_info["defaultSampleRate"])
                channels = int(device_info["maxInputChannels"])
                chunk_size = 1024

                stream = pa.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    frames_per_buffer=chunk_size,
                    input=True,
                    input_device_index=device_info["index"],
                )

                log.info(
                    "[loopback_speech] Захват loopback открыт на '%s' (%s Гц, %s кан.)",
                    device_info.get("name"), sample_rate, channels
                )

                # Инициализация VAD (нейросеть Silero или fallback RMS)
                vad = None
                try:
                    from desktop.core.hearing import SileroVAD
                    vad = SileroVAD()
                except Exception as e:
                    log.debug("[loopback_speech] SileroVAD не загружен: %s", e)

                # Буферы детекции
                pre_roll = collections.deque(maxlen=10)  # ~0.35 сек предзаписи
                current_speech: list[np.ndarray] = []
                is_speaking = False
                silence_chunks = 0
                max_silence_chunks = int(0.85 * (sample_rate / chunk_size))  # ~0.85 сек тишины для закрытия фразы
                min_speech_chunks = int(0.25 * (sample_rate / chunk_size))   # минимум 0.25 сек речи
                vad_pcm_buffer = bytearray()
                read_errors = 0

                while self._running and self.is_active_fn():
                    try:
                        raw = stream.read(chunk_size, exception_on_overflow=False)
                        read_errors = 0
                    except Exception as ex:
                        read_errors += 1
                        if read_errors > 5:
                            log.warning("[loopback_speech] Ошибки чтения stream: %s, переоткрываем", ex)
                            break
                        time.sleep(0.02)
                        continue

                    # Если Сакура сама говорит — сбрасываем, чтобы не слышать себя
                    if self.is_muted_fn():
                        current_speech.clear()
                        is_speaking = False
                        silence_chunks = 0
                        pre_roll.clear()
                        vad_pcm_buffer.clear()
                        continue

                    chunk = np.frombuffer(raw, dtype=np.float32)
                    if channels > 1:
                        chunk = chunk.reshape(-1, channels).mean(axis=1)

                    rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) else 0.0

                    # 1. Проверка голоса через Silero VAD или по RMS
                    has_voice = False
                    if vad is not None:
                        # Ресемплируем чанк в 16кГц для Silero VAD
                        chunk_16k = resample_to_16k(chunk, sample_rate)
                        pcm_16k = (np.clip(chunk_16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                        vad_pcm_buffer.extend(pcm_16k)

                        while len(vad_pcm_buffer) >= 1024:  # 512 сэмплов int16 = 1024 байта
                            frame = bytes(vad_pcm_buffer[:1024])
                            del vad_pcm_buffer[:1024]
                            prob = vad.speech_prob(frame)
                            if prob > 0.40:
                                has_voice = True
                                break
                    else:
                        # Fallback по RMS порогу: 0.003 (~ -50 dBFS)
                        has_voice = rms > 0.003

                    # 2. Логика накопления фразы
                    if has_voice:
                        if not is_speaking:
                            is_speaking = True
                            current_speech.extend(pre_roll)
                        current_speech.append(chunk)
                        silence_chunks = 0
                    else:
                        if is_speaking:
                            current_speech.append(chunk)
                            silence_chunks += 1
                            # Пауза превысила порог — фраза завершена!
                            if silence_chunks >= max_silence_chunks:
                                if len(current_speech) >= min_speech_chunks:
                                    full_audio = np.concatenate(current_speech)
                                    # Запускаем распознавание в отдельном потоке
                                    threading.Thread(
                                        target=self._process_utterance,
                                        args=(full_audio, sample_rate),
                                        daemon=True,
                                        name="LoopbackTranscribe",
                                    ).start()
                                current_speech.clear()
                                is_speaking = False
                                silence_chunks = 0
                                if vad:
                                    vad.reset()
                        else:
                            pre_roll.append(chunk)

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
        """Ресемплинг в 16 кГц, нормализация и передача в распознаватель."""
        if len(audio) == 0:
            return

        # Качественный ресемплинг в 16000 Гц
        audio_16k = resample_to_16k(audio, orig_sr)

        # Ограничиваем фразу максимум 20 секундами
        if len(audio_16k) > 16000 * 20:
            audio_16k = audio_16k[: 16000 * 20]

        # Нормализация громкости речи: приведение тихого голоса из наушников к рабочему RMS
        rms = float(np.sqrt(np.mean(audio_16k**2))) if len(audio_16k) else 0.0
        if 0.0 < rms < 0.08:
            target_rms = 0.09
            gain = min(6.0, target_rms / max(rms, 1e-4))
            audio_16k = np.clip(audio_16k * gain, -1.0, 1.0)

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

        if not text or len(text.strip()) < 2:
            return

        log.info("[loopback_speech] Распознана речь из войса/видео: «%s»", text)

        from desktop.core.features import get_call_mode_manager, get_watch_along_manager
        cm = get_call_mode_manager()
        wa = get_watch_along_manager()

        if cm.active and self.on_caller_speech:
            self.on_caller_speech(text)

        if wa.active and self.on_watch_speech:
            self.on_watch_speech(text)
