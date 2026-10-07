"""tests/test_overlay_render.py — эталонные кадры SphereCore (offscreen QImage 300x300).

Состояния idle/listening/thinking/speaking, с цветом настроения и без.
Детерминированность: random.seed(0), фиксированные поля анимации,
лепестки и частицы отключены на время теста.
Допуск: не больше 1% пикселей с разницей > 2 по каналу.
Картинки до/после складываются в tests/render_out/ (в .gitignore).
"""
import os
import random
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from ui import overlay as ov

BASELINE_DIR = Path(__file__).resolve().parent / "render_baseline"
OUT_DIR = Path(__file__).resolve().parent / "render_out"

MOOD = {"color": "#ffb36b", "pulse_amp": 0.05, "petal_speed": 1.0, "inner_weather": "clear"}

STATES = ["idle", "listening", "thinking", "speaking"]

_app = None


def _get_app():
    global _app
    inst = QApplication.instance()
    if inst is not None:
        _app = inst
        return inst
    if _app is None:
        _app = QApplication([])
    return _app


def _freeze(widget):
    random.seed(0)
    widget._a1 = 30.0
    widget._a2 = 120.0
    widget._phase = 0.7
    widget._cloud = [0.5, 2.6, 4.7]
    widget._ghost = 0.4
    widget._ghost_dir = 1
    widget._echo = 0.3
    widget._ripples = [0.3] if widget._state == "listening" else []
    widget._rip_acc = 0
    widget._audio_level = 0.25
    widget._tts_level = 0.0
    widget._eq_bars = [0.3] * 8
    widget._eq_target = [0.3] * 8
    widget._col_targets = [0.3] * 20
    widget._col_weights = [1.0] * 20
    widget._breathe_phase = 0.5
    widget._breathe_amp = 0.02
    widget._petals = []
    widget._ring_color = None


def render_frame(state, mood):
    _get_app()
    w = ov.SphereCore()
    w._timer.stop()
    w.resize(300, 300)
    w.set_state(state)
    w._timer.stop()
    if mood:
        w.set_mood(dict(MOOD))
    _freeze(w)
    img = QImage(300, 300, QImage.Format.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


def _save(img, path):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img.save(str(path))


def _diff_ratio(a: QImage, b: QImage) -> float:
    assert a.size() == b.size()
    w, h = a.width(), a.height()
    bad = 0
    for y in range(h):
        la = a.scanLine(y).asarray(w * 4)
        lb = b.scanLine(y).asarray(w * 4)
        for x in range(w):
            o = x * 4
            if (abs(la[o] - lb[o]) > 2 or abs(la[o + 1] - lb[o + 1]) > 2
                    or abs(la[o + 2] - lb[o + 2]) > 2):
                bad += 1
    return bad / (w * h)


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("mood_on", [False, True])
def test_frame_matches_baseline(state, mood_on):
    tag = f"{state}{'_mood' if mood_on else ''}"
    base_path = BASELINE_DIR / f"{tag}.png"
    assert base_path.exists(), f"нет эталона {base_path}"
    img = render_frame(state, mood_on)
    _save(img, OUT_DIR / f"{tag}_check.png")
    base = QImage(str(base_path))
    ratio = _diff_ratio(img, base)
    assert ratio <= 0.01, f"{tag}: доля различающихся пикселей {ratio:.4f} > 1%"
