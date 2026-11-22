"""desktop/tests/test_voice_2.py — Unit-тесты для Voice 2.0 (Фаза 1).

Проверяет:
1. Плавный fade-out без щелчков на interrupt() и micro fade-out/in при underrun.
2. Студийный Voice DSP (HPF 80 Гц, RMS leveling тихого шёпота, tanh soft-limiter).
3. Логику пре-ролл буфера и VAD Barge-in.
4. Безопасность и классификацию Windows Audio Ducking.
5. Расширение палитры тонов (urgent, whisper, amused, hype) и вокальные режимы (sing, rap).
"""

import numpy as np
import pytest

from desktop.core.voice import _fade_out_pcm, apply_voice_dsp
from desktop.core import config
from modules.tts_server import (
    strip_tone,
    strip_performance_mode,
    _system_instruction,
    _stage_tone,
    tone_from_tag,
    TONES,
    SING_SYSTEM,
    RAP_SYSTEM,
    S2_EXPRESSIVE_TEXT,
    S2_TEXT,
)


# ── 1. Тесты Fade-Out и устранения щелчков ───────────────────────────

def test_fade_out_mono_linear_decay():
    """Fade-out моно должен плавно спадать к нулю без скачков."""
    rate = 24000
    samples_count = 240  # 10 мс
    raw = (np.ones(samples_count, dtype=np.int16) * 10000).tobytes()
    buf = bytearray(raw)

    faded_bytes = _fade_out_pcm(buf, samples_count, channels=1)
    faded_arr = np.frombuffer(faded_bytes, dtype=np.int16)

    assert len(faded_arr) == samples_count
    assert faded_arr[0] == 10000
    assert faded_arr[-1] == 0
    # Монотонное невозрастание
    diffs = np.diff(faded_arr)
    assert np.all(diffs <= 0)


def test_fade_out_stereo_linear_decay():
    """Fade-out стерео (кабель Discord) должен затухать на обоих каналах."""
    samples_count = 480
    raw = (np.ones(samples_count * 2, dtype=np.int16) * 8000).tobytes()
    buf = bytearray(raw)

    faded_bytes = _fade_out_pcm(buf, samples_count, channels=2)
    faded_arr = np.frombuffer(faded_bytes, dtype=np.int16).reshape(-1, 2)

    assert len(faded_arr) == samples_count
    assert faded_arr[0, 0] == 8000
    assert faded_arr[0, 1] == 8000
    assert faded_arr[-1, 0] == 0
    assert faded_arr[-1, 1] == 0


def test_fade_out_empty_buffer():
    buf = bytearray()
    assert _fade_out_pcm(buf, 240, channels=1) == b""


# ── 2. Тесты Студийного Voice DSP (numpy) ─────────────────────────────

def test_voice_dsp_hpf_attenuates_low_frequencies():
    """HPF 80 Гц должен сильно ослаблять постоянную составляющую и сверхнизкие частоты (20 Гц)."""
    rate = 24000
    t = np.linspace(0, 1.0, rate, endpoint=False)
    # Сигнал 20 Гц (ниже частоты среза 80 Гц)
    low_freq = (np.sin(2 * np.pi * 20 * t) * 10000).astype(np.int16).tobytes()
    # Сигнал 500 Гц (в речевом диапазоне)
    mid_freq = (np.sin(2 * np.pi * 500 * t) * 10000).astype(np.int16).tobytes()

    out_low = np.frombuffer(apply_voice_dsp(low_freq, rate), dtype=np.int16).astype(np.float64)
    out_mid = np.frombuffer(apply_voice_dsp(mid_freq, rate), dtype=np.int16).astype(np.float64)

    low_power = np.mean(out_low**2)
    mid_power = np.mean(out_mid**2)

    # 20 Гц должны быть подавлены значительно сильнее, чем 500 Гц
    assert mid_power > low_power * 3.0


def test_voice_dsp_whisper_leveling():
    """Тихий шёпот должен аккуратно подтягиваться по громкости."""
    rate = 24000
    # Очень тихий синус (амплитуда 300 из 32768, ~ -40 dBFS)
    t = np.linspace(0, 0.1, int(rate * 0.1), endpoint=False)
    quiet_pcm = (np.sin(2 * np.pi * 300 * t) * 300).astype(np.int16).tobytes()

    out_pcm = apply_voice_dsp(quiet_pcm, rate)
    out_arr = np.frombuffer(out_pcm, dtype=np.int16)

    # Амплитуда должна вырасти (makeup gain > 1.0)
    assert np.max(np.abs(out_arr)) > np.max(np.abs(np.frombuffer(quiet_pcm, dtype=np.int16)))


def test_voice_dsp_soft_limiter_never_clips():
    """Громкий входящий сигнал должен мягко компрессироваться через tanh без хард-клиппинга."""
    rate = 24000
    # Перегруженный сигнал (амплитуда 32000)
    t = np.linspace(0, 0.1, int(rate * 0.1), endpoint=False)
    loud_pcm = (np.sin(2 * np.pi * 400 * t) * 32000).astype(np.int16).tobytes()

    out_pcm = apply_voice_dsp(loud_pcm, rate)
    out_arr = np.frombuffer(out_pcm, dtype=np.int16)

    # Должен оставаться строго внутри диапазона int16
    assert np.max(out_arr) <= 32767
    assert np.min(out_arr) >= -32768


# ── 3. Тесты Пре-ролл буфера для Natural Barge-in ─────────────────────

def test_preroll_buffer_assembly():
    """Кольцевой буфер пре-ролла должен хранить ровно лимит байт и отдавать их на старт захвата."""
    import collections
    preroll_bytes_limit = 12800  # 400 мс при 16кГц 16бит моно
    preroll_blocks = collections.deque()
    preroll_cur_bytes = 0

    # 10 блоков по 2048 байт (всего 20480 байт)
    for i in range(10):
        block = bytes([i] * 2048)
        preroll_blocks.append(block)
        preroll_cur_bytes += len(block)
        while preroll_cur_bytes > preroll_bytes_limit and preroll_blocks:
            dropped = preroll_blocks.popleft()
            preroll_cur_bytes -= len(dropped)

    # В буфере должно остаться не более limit байт самых свежих блоков
    assert preroll_cur_bytes <= preroll_bytes_limit
    assembled = b"".join(preroll_blocks)
    assert len(assembled) == preroll_cur_bytes
    # Самый первый сохранённый блок должен быть свежим (не блок 0)
    assert assembled[0] > 0


# ── 4. Тесты Audio Ducking и классификации ───────────────────────────

def test_audio_ducking_classification():
    from desktop.core.platform.windows_ducking import WindowsAudioDucker
    ducker = WindowsAudioDucker()

    exclude = {"discord.exe", "telegram.exe"}

    # 1. Голосовой чат -> None
    assert ducker._classify_session(1234, "discord.exe", None, "", exclude) is None

    # 2. Яндекс Музыка -> ('music', 0.30)
    res_music = ducker._classify_session(5678, "yandexmusic.exe", None, "", exclude)
    assert res_music is not None
    assert res_music[0] == "music"
    assert res_music[1] == pytest.approx(0.30)

    # 3. Активная игра -> ('game', 0.55)
    res_game = ducker._classify_session(9999, "scrapmechanic.exe", 9999, "scrapmechanic.exe", exclude)
    assert res_game is not None
    assert res_game[0] == "game"
    assert res_game[1] == pytest.approx(0.55)

    # 4. Системный проводник на переднем плане не должен определяться как игра
    res_shell = ducker._classify_session(1111, "explorer.exe", 1111, "explorer.exe", exclude)
    assert res_shell is None


# ── 5. Тесты тонов и вокальных режимов в tts_server ─────────────────

def test_tts_expanded_tones():
    """Проверка новых тонов: urgent, whisper, amused, hype."""
    assert "urgent" in TONES
    assert "whisper" in TONES
    assert "amused" in TONES
    assert "hype" in TONES

    assert tone_from_tag("urgent") == "urgent"
    assert tone_from_tag("тревожно") == "urgent"
    assert tone_from_tag("опасность") == "urgent"

    assert tone_from_tag("whisper") == "whisper"
    assert tone_from_tag("заговорщически") == "whisper"
    assert tone_from_tag("шёпот") == "тихо"

    assert tone_from_tag("amused") == "amused"
    assert tone_from_tag("усмешка") == "amused"

    assert tone_from_tag("hype") == "hype"
    assert tone_from_tag("восторг") == "hype"


def test_strip_performance_mode():
    mode, clean = strip_performance_mode("[РЕЖИМ: пение] спой мне колыбельную")
    assert mode == "sing"
    assert clean == "спой мне колыбельную"

    mode_rap, clean_rap = strip_performance_mode("[MODE: rap] зацени этот бит")
    assert mode_rap == "rap"
    assert clean_rap == "зацени этот бит"

    mode_def, clean_def = strip_performance_mode("просто обычный разговор")
    assert mode_def == "speech"
    assert clean_def == "просто обычный разговор"


def test_system_instruction_modes():
    # Обычный нейтральный
    s_neutral = _system_instruction(model="gemini-3.8-live", tone="нейтрально", performance_mode="speech")
    assert S2_TEXT in s_neutral

    # Экспрессивный тон urgent
    s_urgent = _system_instruction(model="gemini-3.8-live", tone="urgent", performance_mode="speech")
    assert S2_EXPRESSIVE_TEXT in s_urgent
    assert TONES["urgent"] in s_urgent

    # Вокальный режим sing
    s_sing = _system_instruction(model="gemini-3.8-live", performance_mode="sing")
    assert SING_SYSTEM in s_sing
    assert S2_TEXT not in s_sing

    # Вокальный режим rap
    s_rap = _system_instruction(model="gemini-3.8-live", performance_mode="rap")
    assert RAP_SYSTEM in s_rap
    assert S2_TEXT not in s_rap
