"""Тесты для desktop.core.gamesense"""

import time
import pytest
from desktop.core.gamesense import GameSenseDetector, GameSenseEvent


def test_gamesense_dark_detection_once_per_blackout():
    detector = GameSenseDetector(on_event=lambda ev: None, cooldown=1.0)
    width, height = 100, 100
    black_frame = b"\x00\x00\x00\xff" * (width * height)
    gray_frame = b"\x50\x50\x50\xff" * (width * height)

    kinds = []
    for i in range(12):  # 2 секунды чёрного экрана (загрузка) — одно событие, не каждые 2.5 с
        kinds += [e.kind for e in detector.feed_frame(black_frame, width, height, timestamp=100.0 + i * 0.17)]
    assert kinds.count("dark") == 1
    # Короткое мигание в чёрное (меньше 4 кадров) — не событие
    detector.feed_frame(gray_frame, width, height, timestamp=110.0)
    blink = [e.kind for i in range(2) for e in detector.feed_frame(black_frame, width, height, timestamp=110.2 + i * 0.17)]
    assert "dark" not in blink


def test_gamesense_flash_detection():
    events = []
    detector = GameSenseDetector(on_event=lambda ev: events.append(ev), cooldown=1.0)
    width, height = 100, 100

    # Frame 1: normal dark/gray frame (mean ~50)
    gray_frame = b"\x32\x32\x32\xff" * (width * height)
    detector.feed_frame(gray_frame, width, height, timestamp=100.0)

    # Frame 2: sudden white flash (mean 255)
    white_frame = b"\xff\xff\xff\xff" * (width * height)
    res = detector.feed_frame(white_frame, width, height, timestamp=100.1)

    assert any(e.kind == "flash" for e in res)


def _frame(w, h, border_bgra: bytes, center_bgra: bytes, band: int = 6) -> bytes:
    """Кадр: полоса шириной 1/band по краям одного цвета, остальное — другого."""
    by, bx = h // band, w // band
    out = bytearray()
    for y in range(h):
        for x in range(w):
            edge = y < by or y >= h - by or x < bx or x >= w - bx
            out += border_bgra if edge else center_bgra
    return bytes(out)


GRAY = b"\x50\x50\x50\xff"
RED = b"\x0a\x0a\xf0\xff"  # BGRA


def _feed(detector, frames, t0=100.0):
    kinds = []
    for i, f in enumerate(frames):
        kinds += [e.kind for e in detector.feed_frame(f, 160, 90, timestamp=t0 + i * 0.17)]
    return kinds


def test_gamesense_hurt_red_vignette_two_frames():
    detector = GameSenseDetector(on_event=lambda ev: None)
    normal = _frame(160, 90, GRAY, GRAY)
    vignette = _frame(160, 90, RED, GRAY)
    assert _feed(detector, [normal, normal, vignette, vignette, vignette]).count("hurt") == 1


def test_gamesense_hurt_single_frame_is_not_damage():
    detector = GameSenseDetector(on_event=lambda ev: None)
    normal = _frame(160, 90, GRAY, GRAY)
    vignette = _frame(160, 90, RED, GRAY)
    assert "hurt" not in _feed(detector, [normal, normal, vignette, normal, normal])


def test_gamesense_red_scene_is_not_damage():
    """Весь экран красный (закат, красная комната, поворот камеры на стену) — не урон."""
    detector = GameSenseDetector(on_event=lambda ev: None)
    normal = _frame(160, 90, GRAY, GRAY)
    red = _frame(160, 90, RED, RED)
    assert "hurt" not in _feed(detector, [normal, normal, red, red, red, red])


def test_gamesense_permanent_red_ui_is_not_damage():
    """Красная рамка интерфейса с первого кадра — фон, а не урон."""
    detector = GameSenseDetector(on_event=lambda ev: None)
    vignette = _frame(160, 90, RED, GRAY)
    assert "hurt" not in _feed(detector, [vignette] * 10)
