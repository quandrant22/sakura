"""feat/vision: редкий случайный взгляд (sakura_core/vision/glance.py).

Часы, календарь и случайность — свои; кадр, модель и доставка — подменены.
Run: python -m pytest tests/test_vision_glance.py -q
"""

import asyncio
import random
from datetime import datetime

import pytest

import config
import modules.state as st
from sakura_core import voice_turns
from sakura_core.vision import capture, glance, model, seen, settings

DEV = "laptop"
JPEG = b"\xff\xd8\xff" + b"\x00" * 32


class Clock:
    def __init__(self):
        self.t = 100_000.0
        self.day = datetime(2026, 11, 2, 14, 0)

    def now(self):
        return self.t

    def wall(self):
        return self.day


class Stand:
    """Мир вокруг Glance: всё, что взгляд спрашивает, задаётся полями."""

    def __init__(self, monkeypatch):
        self.clock = Clock()
        self.enabled = True
        self.device = DEV
        self.supports = True
        self.quiet = False
        self.status = "normal"
        self.talking = False
        self.window = None
        self.frames = []          # что вернёт capture.request (по очереди) или Frame по умолчанию
        self.replies = []         # ответы модели по очереди
        self.captured = []
        self.delivered = []
        self.on_see = None        # хук: что поменять, пока модель «думает»

        monkeypatch.setattr(config, "VISION_GLANCE", True)
        monkeypatch.setattr(config, "GLANCE_BASE_MIN", 30)
        monkeypatch.setattr(config, "GLANCE_ATTEMPTS_PER_HOUR", 3)
        monkeypatch.setattr(config, "GLANCE_SPOKEN_PER_DAY", 6)
        monkeypatch.setattr(config, "GLANCE_AFTER_TURN_S", 120)
        monkeypatch.setattr(config, "GLANCE_AFTER_SPOKEN_S", 900)
        monkeypatch.setattr(st, "_last_command_ts", 0.0)
        monkeypatch.setattr(st, "_pending_power", {})
        monkeypatch.setattr(settings, "glance_enabled", lambda: self.enabled)
        monkeypatch.setattr(capture, "supports", lambda d: self.supports)
        monkeypatch.setattr(voice_turns, "active", lambda d: object() if self.talking else None)
        import modules.proactive as pr
        import modules.window_watcher as ww
        monkeypatch.setattr(ww, "is_quiet_mode", lambda: self.quiet)
        monkeypatch.setattr(pr, "get_master_status", lambda: self.status)
        from sakura_core import bridge

        class _Router:
            class session:
                pending = None
        monkeypatch.setattr(bridge, "get_router", lambda: _Router)
        monkeypatch.setattr(glance.Glance, "target", lambda g: self.device)
        monkeypatch.setattr(glance.Glance, "window_now", staticmethod(lambda d: self.window))

        async def fake_request(device, purpose, **kw):
            self.captured.append((device, purpose, kw))
            if self.frames:
                f = self.frames.pop(0)
                if isinstance(f, Exception):
                    raise f
                return f
            return capture.Frame(device, JPEG, title="Terraria")

        async def fake_see(image, mime, prompt, **kw):
            self.prompts.append(prompt)
            if self.on_see:
                self.on_see()
            return self.replies.pop(0) if self.replies else "ПРОПУСК"

        async def fake_deliver(g, device, line):
            self.delivered.append((device, line))
            return True

        self.prompts = []
        monkeypatch.setattr(capture, "request", fake_request)
        monkeypatch.setattr(model, "see", fake_see)
        monkeypatch.setattr(glance.Glance, "_deliver", fake_deliver)
        self.g = glance.Glance(now=self.clock.now, wall=self.clock.wall, rng=random.Random(7))

    def tick(self):
        return asyncio.run(self.g.tick())

    def due(self):
        """Перевести часы на момент взгляда."""
        if self.g.next_at is None:
            self.tick()                       # первый такт: «включили» → расписание
        self.clock.t = max(self.clock.t, self.g.next_at)
        st._last_command_ts = 0.0


@pytest.fixture
def w(monkeypatch):
    seen.reset()
    yield Stand(monkeypatch)
    seen.reset()


SPEAK = "ВИДЕЛА: Terraria, бой с Глазом Ктулху. СКАЖУ: Глаз Ктулху уже близко, держись!"


# ── выключено / расписание ─────────────────────────────────────────

def test_disabled_never_captures(w):
    w.enabled = False
    for _ in range(5):
        assert w.tick() == "disabled"
        w.clock.t += 3600
    assert w.captured == []


def test_server_switch_off_wins(w, monkeypatch):
    monkeypatch.setattr(config, "VISION_GLANCE", False)
    assert w.tick() == "disabled"


def test_first_glance_5_to_15_minutes_after_enable(w):
    assert w.tick() == "not_due"
    delay = w.g.next_at - w.clock.t
    assert 300 <= delay <= 900


def test_interval_is_random_within_bounds(w):
    for _ in range(50):
        w.g.schedule(0.0)
        assert 0.6 * 30 * 60 <= w.g.next_at <= 1.4 * 30 * 60


def test_enable_again_restarts_schedule(w):
    w.tick()
    w.enabled = False
    w.tick()
    w.enabled = True
    w.clock.t += 10_000
    assert w.tick() == "not_due"                 # не сразу после включения
    assert 300 <= w.g.next_at - w.clock.t <= 900


# ── гейты ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("change, reason", [
    (lambda w: setattr(w, "device", None), "away"),
    (lambda w: setattr(w, "supports", False), "unsupported"),
    (lambda w: setattr(w, "quiet", True), "quiet"),
    (lambda w: setattr(w, "status", "busy"), "busy"),
    (lambda w: setattr(w, "talking", True), "talking"),
    (lambda w: setattr(w.clock, "day", datetime(2026, 11, 2, 23, 30)), "night"),
    (lambda w: setattr(w.clock, "day", datetime(2026, 11, 2, 7, 59)), "night"),
])
def test_gates(w, change, reason):
    w.due()
    change(w)
    assert w.tick() == f"blocked:{reason}"
    assert w.captured == []
    assert w.g.next_at == pytest.approx(w.clock.t + glance.RETRY_S)


def test_recent_turn_gate(w):
    w.due()
    st._last_command_ts = w.clock.t - 30
    assert w.tick() == "blocked:recent_turn"


def test_pending_power_gate(w):
    w.due()
    st._pending_power = {"x": 1}
    assert w.tick() == "blocked:pending"


# ── взгляд целиком ─────────────────────────────────────────────────

def test_full_glance_speaks_once(w):
    w.replies = [SPEAK]
    w.due()
    assert w.tick() == "spoken"
    assert w.delivered == [(DEV, "Глаз Ктулху уже близко, держись!")]
    dev, purpose, kw = w.captured[0]
    assert (dev, purpose, kw.get("need_change")) == (DEV, "glance", True)
    s = seen.latest(now=w.clock.t)
    assert s.saw.startswith("Terraria") and s.purpose == "glance" and s.title == "Terraria"
    assert w.tick() == "not_due"                  # следующий — по расписанию


def test_skip_is_silent_but_remembers(w):
    w.replies = ["ВИДЕЛА: VS Code, файл glance.py СКАЖУ: ПРОПУСК"]
    w.due()
    assert w.tick() == "silent"
    assert w.delivered == []
    assert seen.latest(now=w.clock.t).saw == "VS Code, файл glance.py"


def test_unsure_is_silent_and_not_remembered(w):
    w.replies = ["ВИДЕЛА: кажется, какая-то игра СКАЖУ: Ого!"]
    w.due()
    assert w.tick() == "silent"
    assert seen.latest(now=w.clock.t) is None


def test_client_skip(w):
    w.frames = [capture.Skipped("unchanged")]
    w.due()
    assert w.tick() == "skipped:unchanged"


def test_capture_error(w):
    w.frames = [capture.CaptureError("timeout", "нет")]
    w.due()
    assert w.tick() == "error:timeout"


def test_became_busy_while_thinking(w):
    w.replies = [SPEAK]
    w.on_see = lambda: setattr(w, "talking", True)
    w.due()
    assert w.tick() == "late:talking"
    assert w.delivered == []


def test_window_changed_while_thinking(w):
    w.replies = [SPEAK]
    w.window = "Telegram"
    w.due()
    assert w.tick() == "window_changed"
    assert w.delivered == []


def test_repeat_is_dropped_and_prompt_lists_said(w):
    w.replies = [SPEAK, "ВИДЕЛА: Terraria СКАЖУ: Опять Глаз Ктулху!"]
    w.due()
    assert w.tick() == "spoken"
    w.clock.t += 901                             # прошёл cooldown
    w.due()
    assert w.tick() == "repeat"
    assert "Глаз Ктулху уже близко" in w.prompts[1]     # модели показали сказанное
    assert len(w.delivered) == 1


# ── лимиты ─────────────────────────────────────────────────────────

def test_cooldown_after_spoken(w):
    w.replies = [SPEAK]
    w.due()
    assert w.tick() == "spoken"
    w.g.next_at = w.clock.t                      # «пора» по таймеру
    assert w.tick() == "blocked:cooldown"


def test_hour_limit(w):
    for _ in range(3):
        w.due()
        assert w.tick() == "silent"
        w.clock.t += 60
        w.g.next_at = w.clock.t
    assert w.tick() == "blocked:hour_limit"
    w.clock.t += 3601
    w.g.next_at = w.clock.t
    assert w.tick() == "silent"


def test_day_limit(w, monkeypatch):
    monkeypatch.setattr(config, "GLANCE_SPOKEN_PER_DAY", 2)
    monkeypatch.setattr(config, "GLANCE_AFTER_SPOKEN_S", 0)
    monkeypatch.setattr(config, "GLANCE_ATTEMPTS_PER_HOUR", 99)
    lines = ["ВИДЕЛА: игра СКАЖУ: Красивый закат.", "ВИДЕЛА: игра СКАЖУ: Мощный удар мечом."]
    w.replies = list(lines)
    for _ in range(2):
        w.due()
        assert w.tick() == "spoken"
        w.g.next_at = w.clock.t
    assert w.tick() == "blocked:day_limit"
    w.clock.day = datetime(2026, 11, 3, 14, 0)                # новый день
    w.g.next_at = w.clock.t
    assert w.tick() == "silent"
