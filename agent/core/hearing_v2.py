"""core/hearing_v2.py — Optimized hearing with streaming STT.

Key optimizations:
1. Streaming STT — process audio in real-time, not after full utterance
2. Reduced silence threshold — 0.3s instead of 1.0s
3. Pre-roll ring buffer — 5s of audio before wake word
4. Silero VAD — better voice detection
5. Partial results — show text as user speaks
"""

import gc
import json
import logging
import os
import re
import threading
import time
from collections import deque

import config

try:
    import sounddevice as sd
except ImportError:
    sd = None
try:
    import numpy as np
except ImportError:
    np = None
try:
    import torch
    torch.set_num_threads(1)
except ImportError:
    torch = None
try:
    from vosk import Model as VoskModel, KaldiRecognizer
except ImportError:
    VoskModel = KaldiRecognizer = None
try:
    from silero_vad import load_silero_vad
except ImportError:
    load_silero_vad = None

log = logging.getLogger("sakura.hearing_v2")

# ── Optimized settings ────────────────────────────────────────────────

# Reduced from 1.0 to 0.3 for faster response
VAD_END_SILENCE = 0.3

# Pre-roll buffer: 5 seconds
PRE_ROLL_SECONDS = 5.0

# Frame duration at 16kHz with 512 samples
FRAME_DURATION = 512 / 16000  # ~32ms


class RingBuffer:
    """Ring buffer for audio pre-roll."""

    def __init__(self, max_seconds: float = 5.0, sample_rate: int = 16000):
        self.max_frames = int(max_seconds * sample_rate / 512)
        self.buffer = deque(maxlen=self.max_frames)

    def push(self, frame: bytes):
        self.buffer.append(frame)

    def drain(self) -> list:
        result = list(self.buffer)
        self.buffer.clear()
        return result

    def clear(self):
        self.buffer.clear()

    def __len__(self):
        return len(self.buffer)


class SileroVAD:
    """Silero VAD for voice detection."""

    SR = 16000
    FRAME = 512

    def __init__(self):
        self._model = load_silero_vad()

    def speech_prob(self, pcm16: bytes) -> float:
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio) != self.FRAME:
            return 0.0
        return self._model(torch.from_numpy(audio), self.SR).item()

    def reset(self):
        self._model.reset_states()


class StreamingSTT:
    """Streaming speech-to-text using Vosk."""

    def __init__(self, model, sample_rate: int = 16000):
        self.model = model
        self.sample_rate = sample_rate
        self.recognizer = KaldiRecognizer(model, sample_rate)
        self.recognizer.SetWords(True)
        self._partial = ""
        self._final = ""

    def feed(self, data: bytes) -> str:
        """Feed audio data, return partial result."""
        if self.recognizer.AcceptWaveform(data):
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").strip()
            if text:
                self._final = text
                return text
        else:
            partial = json.loads(self.recognizer.PartialResult())
            self._partial = partial.get("partial", "")
        return self._partial

    def get_final(self) -> str:
        """Get final result and reset."""
        result = json.loads(self.recognizer.FinalResult())
        text = result.get("text", "").strip()
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
        self.recognizer.SetWords(True)
        return text or self._final

    def reset(self):
        """Reset recognizer."""
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
        self.recognizer.SetWords(True)
        self._partial = ""
        self._final = ""


class HearingV2(threading.Thread):
    """Optimized hearing with streaming STT."""

    def __init__(self, agent):
        super().__init__(daemon=True)
        self.agent = agent
        self.ok = bool(sd and np and torch and VoskModel and load_silero_vad)
        self._follow_until = 0.0
        self._dialog = False
        self._mute_until = 0.0
        self.vad = None
        self.recognizer = None
        self.ring_buffer = RingBuffer(PRE_ROLL_SECONDS, config.MIC_RATE)

        if self.ok:
            try:
                self.vad = SileroVAD()
            except Exception as e:
                log.error(f"Silero VAD failed: {e}")
                self.ok = False
            try:
                # Use small model for wake word (fast)
                wake_model = VoskModel(config.VOSK_MODEL_PATH)
                self.wake_recognizer = StreamingSTT(wake_model, config.MIC_RATE)
                # Use larger model for command recognition (accurate)
                stt_model_path = os.path.join(config.BASE_DIR, config.VOSK_STT_MODEL)
                if os.path.isdir(stt_model_path):
                    stt_model = VoskModel(stt_model_path)
                else:
                    stt_model = wake_model  # Fallback
                self.command_recognizer = StreamingSTT(stt_model, config.MIC_RATE)
            except Exception as e:
                log.error(f"STT init failed: {e}")
                self.ok = False

    def run(self):
        if not self.ok:
            log.warning("Hearing disabled — missing dependencies")
            return

        log.info("Hearing v2 enabled. Waiting for wake word...")

        try:
            with sd.RawInputStream(
                samplerate=config.MIC_RATE,
                channels=1,
                dtype="int16",
                blocksize=config.MIC_BLOCK,
            ) as stream:
                while True:
                    data = bytes(stream.read(config.MIC_BLOCK)[0])

                    # Buffer audio for pre-roll
                    self.ring_buffer.push(data)

                    # Skip if TTS is playing
                    if self.agent.player.is_playing():
                        self.wake_recognizer.reset()
                        self._mute_until = time.monotonic() + 0.4
                        continue

                    if time.monotonic() < self._mute_until:
                        continue

                    # Dialog/followup mode
                    if self._dialog or time.monotonic() < self._follow_until:
                        self._follow_until = 0.0
                        self._capture_streaming(stream)
                        continue

                    # Wake word detection via streaming
                    self.wake_recognizer.feed(data)
                    partial = self.wake_recognizer._partial

                    if any(w in partial for w in config.WAKE_WORDS):
                        log.info(f"Wake word detected in: '{partial}'")
                        self.wake_recognizer.reset()
                        self._capture_streaming(stream)

        except Exception as e:
            log.error(f"Hearing error: {e}")

    def _capture_streaming(self, stream):
        """Capture and process command with streaming STT."""
        self.agent.set_state("listening")
        self.vad.reset()
        self.command_recognizer.reset()

        pcm = bytearray()
        speaking = False
        silence = 0.0
        start = time.monotonic()
        frame_dur = SileroVAD.FRAME / config.MIC_RATE

        # Reduced silence threshold for faster response
        silence_threshold = VAD_END_SILENCE
        max_utter = config.MAX_UTTER_SEC

        log.info("Listening for command...")

        while True:
            if self.agent.player.is_playing():
                self._mute_until = time.monotonic() + 0.4
                self.agent.set_state("idle")
                return

            data = bytes(stream.read(config.MIC_BLOCK)[0])
            elapsed = time.monotonic() - start

            # VAD processing
            if self.vad.speech_prob(data) >= config.VAD_THRESHOLD:
                speaking = True
                silence = 0.0
                pcm.extend(data)

                # Feed to streaming STT for real-time transcription
                partial = self.command_recognizer.feed(data)
                if partial:
                    log.debug(f"[STT streaming] {partial}")

            elif speaking:
                pcm.extend(data)
                silence += frame_dur

                # Still feed to STT during silence
                self.command_recognizer.feed(data)

                if silence >= silence_threshold:
                    break
            elif elapsed >= config.VAD_START_TIMEOUT:
                self.agent.set_state("idle")
                return

            if elapsed >= max_utter:
                break

        if not speaking:
            self.agent.set_state("idle")
            return

        # Get final transcription
        self.agent.set_state("thinking")
        text = self.command_recognizer.get_final()

        if not text:
            self.agent.set_state("idle")
            return

        # Post-process
        text = _post_process(text)
        log.info(f"[STT] {text!r}")

        # Voice emotion analysis
        prosody = analyze_voice_emotion(bytes(pcm))
        if prosody["label"] != "neutral":
            try:
                from modules.mood_vector import set_target, get_current
                cur = get_current()
                set_target(
                    cur["valence"] + prosody["valence_hint"],
                    cur["arousal"] + prosody["arousal_hint"],
                    blend=0.20,
                )
            except Exception:
                pass

        # Voice bookmark
        tl = text.lower()
        bookmark_kw = ("запомни это", "сохрани это", "заметь это", "в память")
        if any(kw in tl for kw in bookmark_kw):
            bookmark_re = re.compile(
                r"сакура[,\s]*|запомни это[,\s]*|сохрани это[,\s]*|заметь это[,\s]*|в память[,\s]*",
                re.IGNORECASE,
            )
            content = bookmark_re.sub("", text).strip(" ,.—")
            if len(content) > 2:
                self.agent.bus.emit("voice_bookmark", text=content)
                log.info(f"[bookmark] {content[:60]}")
                return

        # Game mode check
        if self._maybe_game_mode(text):
            return

        # Dialog mode
        self._update_dialog(text)

        # Submit to agent
        self.agent.submit_user_text(text)

    def _maybe_game_mode(self, text: str) -> bool:
        import difflib
        low = text.lower()
        words = low.replace(",", " ").split()

        def has(targets, cutoff=0.75):
            return any(difflib.get_close_matches(w, targets, n=1, cutoff=cutoff) for w in words)

        if ((("выйди" in low) or ("выход" in low) or ("обычный" in low) or ("выключи" in low))
                and (has(("игровой", "игры", "игру")) or "режим" in low)):
            self.agent.bus.emit("game_mode", on=False)
            self.agent.set_state("idle")
            return True
        if has(("игровой", "игру", "игры")) and "режим" in low:
            self.agent.bus.emit("game_mode", on=True)
            self.agent.set_state("idle")
            return True
        return False

    def _update_dialog(self, text: str):
        import difflib
        words = text.lower().replace(",", " ").split()

        def has(targets, cutoff=0.75):
            return any(difflib.get_close_matches(w, targets, n=1, cutoff=cutoff) for w in words)

        if not self._dialog and has(("поболтаем", "поболтать", "поговорим", "болтать")):
            self._dialog = True
        elif self._dialog and len(words) <= 4 and has(
                ("хватит", "всё", "стоп", "спасибо", "пока", "достаточно", "закончили")):
            self._dialog = False


def _post_process(text: str) -> str:
    """Post-process STT output."""
    if not text:
        return text

    # Capitalize first letter
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    # Add period if no punctuation
    if text and text[-1] not in ".!?":
        text += "."

    return text


def analyze_voice_emotion(pcm_bytes: bytes, sample_rate: int = 16000) -> dict:
    """Quick voice emotion analysis."""
    if not np or not pcm_bytes:
        return {"label": "neutral", "valence_hint": 0.0, "arousal_hint": 0.0}

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    dur = len(audio) / sample_rate
    if dur < 0.1:
        return {"label": "neutral", "valence_hint": 0.0, "arousal_hint": 0.0}

    rms = float(np.sqrt(np.mean(audio ** 2)))
    energy = min(1.0, rms * 10)
    zcr = float(np.mean(np.abs(np.diff(np.sign(audio)))) / 2)
    tempo = min(2.0, zcr / 0.08)

    if energy > 0.65 and tempo > 1.3:
        return {"label": "excited", "valence_hint": 0.05, "arousal_hint": 0.15}
    elif energy > 0.70 and tempo < 0.8:
        return {"label": "angry", "valence_hint": -0.20, "arousal_hint": 0.18}
    elif energy < 0.25 and tempo < 0.7:
        return {"label": "tired", "valence_hint": -0.08, "arousal_hint": -0.15}
    elif energy < 0.30:
        return {"label": "calm", "valence_hint": 0.05, "arousal_hint": -0.08}

    return {"label": "neutral", "valence_hint": 0.0, "arousal_hint": 0.0}
