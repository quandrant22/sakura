"""tests/test_overlay_idle_return.py — после set_state("idle") сфера
возвращается в нейтраль: кадр совпадает с эталоном idle.

Остатки активного состояния (эквалайзер, уровни, круги, дыхание)
НЕ подменяются — их должны привести в нейтраль сами _tick.
Перед рендером фиксируются только «часы» анимации (углы, фазы),
которые крутятся всегда и от состояния не зависят.
"""
import importlib.util
import os
import random
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage

from ui import overlay as ov

# общие хелперы и эталоны — из test_overlay_render
_spec = importlib.util.spec_from_file_location(
    "_overlay_render_helpers", Path(__file__).with_name("test_overlay_render.py"))
r = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r)

TICKS = 20   # ~1 с при idle-таймере 50 мс


def _freeze_clocks(w):
    random.seed(0)
    w._a1 = 30.0
    w._a2 = 120.0
    w._phase = 0.7
    w._cloud = [0.5, 2.6, 4.7]
    w._ghost = 0.4
    w._ghost_dir = 1
    w._echo = 0.3
    w._breathe_phase = 0.5
    w._petals = []


def _settle_to_idle(from_state, mood):
    r._get_app()
    w = ov.SphereCore()
    w._timer.stop()
    w.resize(300, 300)
    w.set_state(from_state)
    w._timer.stop()
    if mood:
        w.set_mood(dict(r.MOOD))
    r._freeze(w)
    # остатки активного состояния — как после громкой реплики
    w._audio_level = 0.9
    w._tts_level = 0.8
    w._eq_bars = [1.0] * 8
    w._eq_target = [0.9] * 8
    w._col_targets = [1.0] * 20
    w._ripples = [0.2, 0.6]
    w._breathe_amp = 0.0

    w.set_state("idle")
    w._timer.stop()
    random.seed(1)
    for _ in range(TICKS):
        w._tick()
    _freeze_clocks(w)

    img = QImage(300, 300, QImage.Format.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


@pytest.mark.parametrize("from_state", ["speaking", "listening", "thinking"])
@pytest.mark.parametrize("mood_on", [False, True])
def test_returns_to_idle_baseline(from_state, mood_on):
    tag = f"idle{'_mood' if mood_on else ''}"
    base = QImage(str(r.BASELINE_DIR / f"{tag}.png"))
    img = _settle_to_idle(from_state, mood_on)
    ratio = r._diff_ratio(img, base)
    assert ratio <= 0.01, f"{from_state}->{tag}: доля различающихся пикселей {ratio:.4f} > 1%"
