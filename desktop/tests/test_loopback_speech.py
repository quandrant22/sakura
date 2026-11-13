"""Тесты для desktop.core.loopback_speech"""

import numpy as np
import pytest
from desktop.core.loopback_speech import LoopbackSpeechListener


def test_loopback_speech_init_and_state():
    caller_lines = []
    watch_lines = []

    listener = LoopbackSpeechListener(
        is_active_fn=lambda: True,
        is_muted_fn=lambda: False,
        on_caller_speech=lambda t: caller_lines.append(t),
        on_watch_speech=lambda t: watch_lines.append(t),
    )

    assert listener.is_active_fn() is True
    assert listener.is_muted_fn() is False


def test_loopback_speech_resample_and_process():
    processed = []

    class DummyRecognizer:
        def transcribe(self, audio):
            assert len(audio) > 0
            return "привет сакура"

    listener = LoopbackSpeechListener(
        on_caller_speech=lambda t: processed.append(t),
        recognizer=DummyRecognizer(),
    )

    # Fake 44.1kHz audio array (0.5s)
    fake_audio = np.sin(np.linspace(0, 100, 22050)).astype(np.float32)

    from desktop.core.features import get_call_mode_manager
    cm = get_call_mode_manager()
    cm.enable("Discord")

    listener._process_utterance(fake_audio, orig_sr=44100)

    assert len(processed) == 1
    assert processed[0] == "привет сакура"
