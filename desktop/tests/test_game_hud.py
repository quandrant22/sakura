"""Тесты для модуля desktop.core.game_hud (Game Awareness & HUD Tracking)."""

import os
import tempfile
import cv2
import numpy as np
import pytest

from desktop.core.game_hud.cv_utils import (
    calculate_bar_fill,
    parse_number_from_text,
    preprocess_crop,
    sample_bar_color,
)
from desktop.core.game_hud.debug import render_debug_frame
from desktop.core.game_hud.mapper import denormalize_bbox
from desktop.core.game_hud.telemetry.registry import get_telemetry_provider
from desktop.core.game_hud.tracker import HudTracker
from desktop.core.game_hud.types import (
    BarOrientation,
    GameState,
    HudElementConfig,
    HudProfile,
    PreprocessMode,
    ReaderType,
)


def test_hud_profile_serialization():
    elem = HudElementConfig(
        id="hp_bar",
        type="bar",
        label="Здоровье",
        bbox_1000=[950, 48, 985, 150],
        bbox_px=[48, 548, 150, 568],
        color_hint="lime",
        hsv_lower=[30, 80, 80],
        hsv_upper=[85, 255, 255],
        orientation=BarOrientation.LTR.value,
        preprocess=PreprocessMode.RGB.value,
        reader=ReaderType.LOCAL_CV.value,
    )
    profile = HudProfile(
        game_id="scrapmechanic",
        game_name="Scrap Mechanic",
        resolution=[1920, 1080],
        elements=[elem],
    )

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        path = tf.name

    try:
        profile.save(path)
        loaded = HudProfile.load(path)
        assert loaded is not None
        assert loaded.game_id == "scrapmechanic"
        assert len(loaded.elements) == 1
        le = loaded.elements[0]
        assert le.id == "hp_bar"
        assert le.orientation == "ltr"
        assert le.preprocess == "rgb"
        assert le.hsv_lower == [30, 80, 80]
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_denormalize_bbox():
    # 1000 scale: [ymin, xmin, ymax, xmax] -> [x1, y1, x2, y2]
    bbox_1000 = [500, 200, 600, 400]
    px = denormalize_bbox(bbox_1000, width=1000, height=1000, padding=4, is_bar=False)
    assert px[0] == 200 - 4
    assert px[1] == 500 - 4
    assert px[2] == 400 + 4
    assert px[3] == 600 + 4


def test_calculate_bar_fill_horizontal():
    # Создаем тестовую полоску 20x100 (BGR)
    # Левая половина (50 px) — чисто зеленый лайм (BGR: 0, 255, 100)
    bar = np.zeros((20, 100, 3), dtype=np.uint8)
    bar[:, :50] = [0, 255, 100]

    # ltr
    fill_ltr = calculate_bar_fill(bar, orientation="ltr", hsv_lower=[30, 80, 80], hsv_upper=[85, 255, 255])
    assert 48.0 <= fill_ltr <= 52.0

    # rtl: правая половина заполнена
    bar_rtl = np.zeros((20, 100, 3), dtype=np.uint8)
    bar_rtl[:, 50:] = [0, 255, 100]
    fill_rtl = calculate_bar_fill(bar_rtl, orientation="rtl", hsv_lower=[30, 80, 80], hsv_upper=[85, 255, 255])
    assert 48.0 <= fill_rtl <= 52.0


def test_parse_number_from_text():
    assert parse_number_from_text("142 km/h") == 142.0
    assert parse_number_from_text("30 / 90") == 30.0
    assert parse_number_from_text("HP: 98.5%") == 98.5
    assert parse_number_from_text("No numbers here") is None


def test_game_state_diff():
    s1 = GameState(game_id="game1", game_name="Game 1", metrics={"hp": 80.0, "speed": 60})
    s2 = GameState(game_id="game1", game_name="Game 1", metrics={"hp": 80.5, "speed": 60})
    s3 = GameState(game_id="game1", game_name="Game 1", metrics={"hp": 74.0, "speed": 60})

    # s1 vs s2: изменение < 2% -> False
    assert not s2.has_changed_significantly(s1, threshold=2.0)
    # s1 vs s3: падение на 6% -> True
    assert s3.has_changed_significantly(s1, threshold=2.0)


def test_telemetry_registry():
    cs2_prov = get_telemetry_provider("cs2.exe")
    assert cs2_prov is not None

    ets2_prov = get_telemetry_provider("eurotrucks2.exe")
    assert ets2_prov is not None

    unknown_prov = get_telemetry_provider("some_random_game.exe")
    assert unknown_prov is None


def test_hud_debug_render():
    img = np.zeros((200, 300, 3), dtype=np.uint8)
    elem = HudElementConfig(
        id="hp_bar",
        type="bar",
        label="HP",
        bbox_px=[20, 50, 120, 70],
        orientation="ltr",
    )
    profile = HudProfile(game_id="test", game_name="Test Game", resolution=[300, 200], elements=[elem])
    state = GameState(game_id="test", game_name="Test Game", metrics={"hp_bar": 65.0})

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        out_path = tf.name

    try:
        res = render_debug_frame(img, profile, state, save_path=out_path)
        assert os.path.exists(res)
        assert os.path.getsize(res) > 500
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)
