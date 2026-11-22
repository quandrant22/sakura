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


def test_gamesense_no_false_hurt_on_orange_wall():
    """Проверяем, что оранжевые/желтые стены и объекты (как в Scrap Mechanic) НЕ вызывают ложный урон."""
    events = []
    detector = GameSenseDetector(on_event=lambda ev: events.append(ev), cooldown=1.0)
    width, height = 160, 90

    # Frame 1: серый
    gray_frame = b"\x50\x50\x50\xff" * (width * height)
    detector.feed_frame(gray_frame, width, height, timestamp=100.0)

    # Frame 2: оранжевая стена (BGRA: B=20, G=140, R=230, A=255)
    orange_frame = b"\x14\x8c\xe6\xff" * (width * height)
    res = detector.feed_frame(orange_frame, width, height, timestamp=100.2)

    # Ложного урона быть НЕ должно!
    assert not any(e.kind == "hurt" for e in res)


def test_gamesense_hp_bar_drop_and_low_hp():
    """Проверяем обнаружение полоски HP, регистрацию урона при падении и предупреждение о критическом ХП."""
    import numpy as np

    events = []
    detector = GameSenseDetector(on_event=lambda ev: events.append(ev), cooldown=1.0)
    width, height = 160, 90

    # Создаем базовый кадр (BGRA)
    base = np.zeros((height, width, 4), dtype=np.uint8)
    base[:, :, 3] = 255
    base[:, :, :3] = 40  # темный фон

    # Рисуем зеленую/лаймовую полоску HP в левом нижнем углу:
    # y=85..86, x=10..25 (длина 16 пикселей, цвет лайм BGRA: B=40, G=210, R=180, A=255)
    lime_bgra = [40, 210, 180, 255]
    base[85:87, 10:26] = lime_bgra

    # Frame 1 & 2: закрепление полоски (2 кадра)
    detector.feed_frame(base.tobytes(), width, height, timestamp=100.0)
    detector.feed_frame(base.tobytes(), width, height, timestamp=100.5)
    assert detector.hp_bar_locked is not None
    assert detector.hp_bar_locked["color"] == "lime"

    # Frame 3: урон! Полоска упала с 16 до 3 пикселей (менее 20% оставшегося ХП)
    damaged = base.copy()
    damaged[85:87, 13:26] = [40, 40, 40, 255]  # стерли большую часть

    events.clear()
    detector.feed_frame(damaged.tobytes(), width, height, timestamp=101.0)

    kinds = [e.kind for e in events]
    assert "hurt" in kinds
    assert "low_hp" in kinds
