"""Регрессия на ужимание скриншота под Gemini Vision (этап 8.3).

Кадр смотрит модель, а не человек, поэтому длинная сторона ужимается до
config.SCREENSHOT_MAX_SIDE и только вниз. Тесты держат три вещи: геометрию
ресайза (включая нестандартные пропорции и портрет), неизменность маленьких
экранов и то, что реальный вес кадра после правки падает, а не растёт.
"""

import base64
import io
import os
import sys
import unittest
from unittest.mock import patch

# Ensure the agent package root is importable for core.hands imports.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config
from PIL import Image

from core import hands


def _textured(width: int, height: int) -> Image.Image:
    """Шумный кадр: JPEG на нём сжимается плохо, как на тёмной игре или фото."""
    gray = Image.effect_noise((width, height), 48)
    return gray.convert("RGB")


class TestFitForVision(unittest.TestCase):
    """_fit_for_vision — только уменьшение, пропорции сохраняются."""

    def test_2k_downscaled_to_limit(self):
        view = hands._fit_for_vision(_textured(2560, 1440))
        self.assertEqual(view.size, (1280, 720))

    def test_frame_size_actually_drops(self):
        """Главный смысл правки: кадр уходит по WS меньше, а не больше."""
        big = _textured(2560, 1440)
        buf_big = io.BytesIO()
        big.save(buf_big, format="JPEG", quality=config.SCREENSHOT_QUALITY)

        view = hands._fit_for_vision(big)
        buf_small = io.BytesIO()
        view.save(buf_small, format="JPEG", quality=config.SCREENSHOT_QUALITY)

        self.assertLess(len(buf_small.getvalue()), len(buf_big.getvalue()))

    def test_small_screen_untouched(self):
        """Меньше лимита — не растягиваем и не пересобираем кадр."""
        img = _textured(1024, 768)
        self.assertIs(hands._fit_for_vision(img), img)

    def test_limit_itself_untouched(self):
        img = _textured(1280, 800)
        self.assertIs(hands._fit_for_vision(img), img)

    def test_aspect_ratio_kept_for_16_10(self):
        view = hands._fit_for_vision(_textured(1920, 1200))
        self.assertEqual(view.size, (1280, 800))

    def test_portrait_screen_uses_long_side(self):
        """Вертикальный монитор: длинная сторона — высота."""
        view = hands._fit_for_vision(_textured(1440, 2560))
        self.assertEqual(view.size, (720, 1280))

    def test_extreme_aspect_never_gives_zero(self):
        """Очень узкий кадр не должен схлопнуться в 0 пикселей."""
        view = hands._fit_for_vision(_textured(4000, 3))
        self.assertGreaterEqual(view.width, 1)
        self.assertGreaterEqual(view.height, 1)

    def test_limit_is_configurable(self):
        with patch.object(config, "SCREENSHOT_MAX_SIDE", 640):
            view = hands._fit_for_vision(_textured(2560, 1440))
        self.assertEqual(view.size, (640, 360))


class TestTakeScreenshot(unittest.TestCase):
    """take_screenshot — тот же контракт (base64 JPEG или None) + лог замера."""

    def test_returns_base64_jpeg_of_reduced_size(self):
        with patch.object(hands, "ImageGrab") as grab:
            grab.grab.return_value = _textured(2560, 1440)
            out = hands.take_screenshot()

        self.assertIsNotNone(out)
        raw = base64.b64decode(out)
        self.assertTrue(raw.startswith(b"\xff\xd8"))  # JPEG SOI
        with Image.open(io.BytesIO(raw)) as img:
            self.assertEqual(img.size, (1280, 720))
            self.assertEqual(img.format, "JPEG")

    def test_logs_frame_sizes(self):
        with patch.object(hands, "ImageGrab") as grab:
            grab.grab.return_value = _textured(2560, 1440)
            with self.assertLogs("sakura.hands", level="INFO") as captured:
                hands.take_screenshot()

        line = "\n".join(captured.output)
        self.assertIn("2560x1440", line)
        self.assertIn("1280x720", line)
        self.assertIn("base64", line)

    def test_returns_none_without_imagegrab(self):
        with patch.object(hands, "ImageGrab", None):
            self.assertIsNone(hands.take_screenshot())

    def test_grab_failure_logged_not_raised(self):
        with patch.object(hands, "ImageGrab") as grab:
            grab.grab.side_effect = OSError("display gone")
            with self.assertLogs("sakura.hands", level="ERROR"):
                self.assertIsNone(hands.take_screenshot())


if __name__ == "__main__":
    unittest.main()
