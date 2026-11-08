"""Тесты для desktop.core.gamesense"""

import time
import pytest
from desktop.core.gamesense import GameSenseDetector, GameSenseEvent


def test_gamesense_dark_detection():
    events = []
    detector = GameSenseDetector(on_event=lambda ev: events.append(ev), cooldown=1.0)

    # 100x100 black frame
    width, height = 100, 100
    black_frame = b"\x00\x00\x00\xff" * (width * height)

    res = detector.feed_frame(black_frame, width, height, timestamp=100.0)
    assert any(e.kind == "dark" for e in res)


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


def test_gamesense_hurt_detection():
    events = []
    detector = GameSenseDetector(on_event=lambda ev: events.append(ev), cooldown=1.0)
    width, height = 100, 100

    # Normal frame
    gray_frame = b"\x50\x50\x50\xff" * (width * height)
    detector.feed_frame(gray_frame, width, height, timestamp=100.0)

    # Hurt frame with bright red vignette
    # BGRA: B=10, G=10, R=240, A=255
    red_frame = b"\x0a\x0a\xf0\xff" * (width * height)
    res = detector.feed_frame(red_frame, width, height, timestamp=100.2)

    assert any(e.kind == "hurt" for e in res)
