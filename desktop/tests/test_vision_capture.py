"""Кадр экрана по запросу сервера (desktop/core/vision_capture.py, docs/VISION.md).

Главное: приватное окно → экран не снимается вовсе; без разрешения — только
по прямой просьбе; неизменный экран не кодируется и не отправляется.
"""
import asyncio
import base64
import json
import logging

import pytest
from PIL import Image

from desktop.core import vision_privacy as vp
from desktop.core.vision_capture import ALLOW_KEY, MAX_B64, PRIVATE_KEY, VisionCapture, changed, fingerprint, is_black


class S:
    """Настройки интерфейса (get_bool / get_list, как desktop.core.settings.Settings)."""

    def __init__(self, **data):
        self.data = data

    def get_bool(self, key, default=False):
        return bool(self.data.get(key, default))

    def get_list(self, key, default=None):
        v = self.data.get(key, default or [])
        return v if isinstance(v, list) else []


def screen(color=(40, 120, 200), size=(1920, 1080)):
    return Image.new("RGB", size, color)


class Grab:
    def __init__(self, *frames):
        self.frames = list(frames) or [screen()]
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def vc(settings=None, grab=None, title="Документ — Блокнот", process="notepad.exe", password=False):
    looks = []
    v = VisionCapture(settings, grab=grab or Grab(),
                      foreground=lambda: {"title": title, "process": process},
                      password_focused=lambda: password,
                      on_look=lambda p, a: looks.append((p, a)))
    v.looks = looks
    return v


def req(purpose="ask", **kw):
    return {"type": "vision.capture", "request_id": "vc-1", "purpose": purpose, **kw}


# ── разрешение ─────────────────────────────────────────────────────

def test_ask_works_without_permission():
    out = vc().capture(req("ask"))
    assert out["status"] == "ok" and out["request_id"] == "vc-1" and out["type"] == "vision.frame"


@pytest.mark.parametrize("purpose", ["glance", "watch"])
def test_glance_needs_permission_and_does_not_grab(purpose):
    g = Grab()
    out = vc(S(), grab=g).capture(req(purpose))
    assert out == {"type": "vision.frame", "request_id": "vc-1", "status": "skipped", "reason": "disabled"}
    assert g.calls == 0


def test_glance_allowed():
    v = vc(S(**{ALLOW_KEY: True}))
    assert v.capture(req("glance"))["status"] == "ok"
    assert v.looks == [("glance", True), ("glance", False)]       # индикатор вкл/выкл


def test_ask_does_not_light_indicator():
    v = vc()
    v.capture(req("ask"))
    assert v.looks == []


# ── приватность: экран не снимается ────────────────────────────────

@pytest.mark.parametrize("title, process", [
    ("База паролей — KeePass", "keepass.exe"),
    ("Хранилище", "1Password.exe"),
    ("Новая вкладка — InPrivate — Microsoft Edge", "msedge.exe"),
    ("Новая вкладка (Инкогнито) — Google Chrome", "chrome.exe"),
    ("СберБанк Онлайн — Chrome", "chrome.exe"),
    ("Т-Банк — переводы", "chrome.exe"),
    ("Госуслуги — Личный кабинет", "chrome.exe"),
    ("Sign in to GitHub · GitHub", "firefox.exe"),
])
def test_private_window_never_grabbed(title, process):
    g = Grab()
    v = vc(S(**{ALLOW_KEY: True}), grab=g, title=title, process=process)
    for purpose in ("ask", "glance"):
        out = v.capture(req(purpose))
        assert out["status"] == "skipped" and out["reason"] == "private_window"
    assert g.calls == 0 and v.looks == []


def test_user_private_list():
    g = Grab()
    s = S(**{ALLOW_KEY: True, PRIVATE_KEY: ["Telegram.exe", "переписка"]})
    assert vc(s, grab=g, title="Чат", process="telegram.exe").capture(req("ask"))["reason"] == "private_window"
    mail = vc(s, grab=g, title="Личная переписка — Почта", process="chrome.exe")
    assert mail.capture(req("ask"))["reason"] == "private_window"
    assert g.calls == 0
    assert vc(s, title="Terraria", process="terraria.exe").capture(req("ask"))["status"] == "ok"


def test_password_field_focused():
    g = Grab()
    assert vc(grab=g, password=True).capture(req("ask"))["reason"] == "private_window"
    assert g.calls == 0


@pytest.mark.parametrize("title", ["Terraria", "main.py — Visual Studio Code", "YouTube — Chrome",
                                   "Банкет на 20 человек — рецепты"])
def test_ordinary_windows_are_not_private(title):
    assert not vp.is_private(title, "app.exe")


# ── снятие ─────────────────────────────────────────────────────────

def test_frame_shape_and_resize():
    out = vc(title="Terraria", process="terraria.exe").capture(req("ask", max_side=960, quality=60))
    raw = base64.b64decode(out["image"])
    assert raw[:3] == b"\xff\xd8\xff"
    import io
    img = Image.open(io.BytesIO(raw))
    assert max(img.size) == 960
    assert out["window"] == {"title": "Terraria", "process": "terraria.exe"}
    assert out["changed"] is True


@pytest.mark.parametrize("side, want", [(10, 320), (99999, 1920), ("x", 1280)])
def test_max_side_clamped(side, want):
    out = vc().capture(req("ask", max_side=side))
    import io
    assert max(Image.open(io.BytesIO(base64.b64decode(out["image"]))).size) == min(want, 1920)


def test_need_change_skips_unchanged_screen():
    g = Grab(screen((40, 120, 200)), screen((40, 120, 200)), screen((200, 40, 40)))
    v = vc(S(**{ALLOW_KEY: True}), grab=g)
    assert v.capture(req("glance", need_change=True))["status"] == "ok"
    assert v.capture(req("glance", need_change=True))["reason"] == "unchanged"
    assert v.capture(req("glance", need_change=True))["status"] == "ok"


def test_need_change_is_per_purpose():
    v = vc(S(**{ALLOW_KEY: True}), grab=Grab(screen()))
    assert v.capture(req("glance", need_change=True))["status"] == "ok"
    assert v.capture(req("watch", need_change=True))["status"] == "ok"      # у watch своя память


def test_without_need_change_always_sends():
    v = vc(grab=Grab(screen()))
    assert v.capture(req("ask"))["status"] == "ok"
    assert v.capture(req("ask"))["status"] == "ok"


def test_black_screen_is_no_display():
    assert vc(grab=Grab(screen((0, 0, 0)))).capture(req("ask"))["reason"] == "no_display"


def test_grab_failure():
    def boom():
        raise OSError("нет экрана")
    v = vc(S(**{ALLOW_KEY: True}), grab=boom)
    assert v.capture(req("glance"))["reason"] == "capture_failed"
    assert v.looks == [("glance", True), ("glance", False)]                # индикатор погас


def test_size_limit_respected():
    import random
    noisy = Image.frombytes("RGB", (1920, 1080), random.Random(1).randbytes(1920 * 1080 * 3))
    out = vc(grab=Grab(noisy)).capture(req("ask", max_side=1920, quality=90))
    assert out["status"] == "skipped" or len(out["image"]) <= MAX_B64


# ── отпечаток ──────────────────────────────────────────────────────

def test_fingerprint_threshold():
    a = fingerprint(screen((100, 100, 100)))
    assert len(a) == 64 * 36 * 3
    assert not changed(a, a)
    assert changed(None, a)
    small = bytearray(a)
    for i in range(0, 20 * 3, 3):                       # 20 пикселей чуть изменились
        small[i] += 30
    assert not changed(a, bytes(small))
    big = bytearray(a)
    for i in range(0, 30 * 3, 3):                       # 30 пикселей — уже изменение
        big[i] += 30
    assert changed(a, bytes(big))
    assert is_black(fingerprint(screen((5, 5, 5)))) and not is_black(a)


# ── приватность в логах ────────────────────────────────────────────

def test_frame_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    out = vc(title="Секретный проект", process="code.exe").capture(req("ask"))
    assert out["image"][:40] not in caplog.text
    assert "КиБ" in caplog.text


# ── ядро: register и обработка vision.capture ──────────────────────

def test_agent_answers_vision_capture(monkeypatch):
    from desktop.core import agent as agent_module

    class WS:
        def __init__(self):
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = WS()
    a.vision = vc(S(), title="Terraria", process="terraria.exe")
    asyncio.run(a._vision_capture(req("glance")))
    msg = a._ws.sent[0]
    assert msg["type"] == "vision.frame" and msg["status"] == "skipped" and msg["reason"] == "disabled"
    assert msg["request_id"] == "vc-1" and msg["device_id"]


def test_agent_capture_failure_still_answers():
    from desktop.core import agent as agent_module

    class Broken:
        def capture(self, msg):
            raise RuntimeError("сломалось")

    class WS:
        sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

    a = agent_module.Agent.__new__(agent_module.Agent)
    a._ws = WS()
    a.vision = Broken()
    asyncio.run(a._vision_capture(req("ask")))
    assert a._ws.sent[0]["reason"] == "capture_failed"
