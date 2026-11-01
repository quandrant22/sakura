"""feat/vision: запрос кадра у ПК (sakura_core/vision/capture.py).

Run: python -m pytest tests/test_vision_capture.py -q
"""

import asyncio
import base64
import json

import pytest

import config
import modules.state as st
from sakura_core.vision import capture

MASTER, GUEST = "laptop", "phone"          # conftest: MASTER_DEVICES=laptop,pc
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FakeWS:
    """Сокет ПК: запоминает отправленное и (если задан responder) отвечает
    vision.frame так, как ответил бы клиент."""

    def __init__(self, *, secure=True, responder=None, device=MASTER):
        self.secure = secure
        self.sent = []
        self.responder = responder
        self.device = device

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if self.responder is not None and msg.get("type") == "vision.capture":
            reply = self.responder(msg)
            if reply is not None:
                reply.setdefault("request_id", msg["request_id"])
                reply.setdefault("device_id", self.device)
                asyncio.get_running_loop().call_soon(
                    lambda: asyncio.ensure_future(capture.handle_frame(self, reply)))


def ok(image=JPEG, **extra):
    return lambda msg: {"type": "vision.frame", "status": "ok",
                        "image": base64.b64encode(image).decode(), **extra}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    capture.reset()
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(config, "PRIVATE_REQUIRES_SECURE", True)
    yield
    capture.reset()
    st.connected_devices.clear()
    st.connected_devices.update(saved)


def online(ws, device=MASTER, features=(capture.FEATURE,)):
    st.connected_devices[device] = ws
    capture.note_features(device, {"features": list(features)})
    return ws


def run(coro):
    return asyncio.run(coro)


# ── возможности клиента ─────────────────────────────────────────────

def test_features_noted_and_forgotten():
    capture.note_features(MASTER, {"features": ["vision.capture", 5]})
    assert capture.supports(MASTER)
    capture.note_features(MASTER, {"proto": 2})          # поля нет — не трогаем
    assert capture.supports(MASTER)
    capture.note_features(MASTER, {"features": "vision.capture"})   # не список
    assert not capture.supports(MASTER)
    capture.note_features(MASTER, {"features": ["vision.capture"]})
    capture.forget(MASTER)
    assert not capture.supports(MASTER)


# ── отказы до запроса ──────────────────────────────────────────────

@pytest.mark.parametrize("setup, code", [
    (lambda: None, "offline"),
    (lambda: online(FakeWS(), features=()), "unsupported"),
    (lambda: online(FakeWS(secure=False)), "secure_channel_required"),
])
def test_refusals(setup, code):
    setup()
    with pytest.raises(capture.CaptureError) as e:
        run(capture.request(MASTER, "ask"))
    assert e.value.code == code
    ws = st.connected_devices.get(MASTER)
    assert ws is None or ws.sent == []                  # кадр даже не запрошен


def test_not_master():
    online(FakeWS(device=GUEST), device=GUEST)
    with pytest.raises(capture.CaptureError) as e:
        run(capture.request(GUEST, "ask"))
    assert e.value.code == "not_master"


def test_insecure_allowed_when_policy_off(monkeypatch):
    monkeypatch.setattr(config, "PRIVATE_REQUIRES_SECURE", False)
    online(FakeWS(secure=False, responder=ok()))
    assert isinstance(run(capture.request(MASTER, "ask")), capture.Frame)


def test_unknown_purpose():
    online(FakeWS())
    with pytest.raises(ValueError):
        run(capture.request(MASTER, "spy"))


# ── ответ клиента ──────────────────────────────────────────────────

def test_frame_ok_and_request_shape():
    ws = online(FakeWS(responder=ok(window={"title": "Код — main.py", "process": "code.exe"},
                                    changed=False)))
    frame = run(capture.request(MASTER, "glance", need_change=True, max_side=960, quality=60))
    assert isinstance(frame, capture.Frame)
    assert frame.image == JPEG and frame.mime == "image/jpeg"
    assert frame.title == "Код — main.py" and frame.process == "code.exe"
    assert frame.changed is False
    req = ws.sent[0]
    assert req["type"] == "vision.capture" and req["purpose"] == "glance"
    assert req["need_change"] is True and req["max_side"] == 960 and req["quality"] == 60
    assert capture._waiters == {}                         # ожидание снято


def test_frame_png():
    online(FakeWS(responder=ok(PNG)))
    assert run(capture.request(MASTER, "ask")).mime == "image/png"


@pytest.mark.parametrize("reason, want", [
    ("private_window", "private_window"), ("unchanged", "unchanged"),
    ("disabled", "disabled"), ("что-то новое", "capture_failed"), (None, "capture_failed"),
])
def test_skipped(reason, want):
    online(FakeWS(responder=lambda m: {"type": "vision.frame", "status": "skipped", "reason": reason}))
    assert run(capture.request(MASTER, "ask")) == capture.Skipped(want)


@pytest.mark.parametrize("reply", [
    {"status": "ok", "image": "не base64!!"},
    {"status": "ok", "image": base64.b64encode(b"GIF89a....").decode()},
    {"status": "ok", "image": ""},
    {"status": "ok", "image": "A" * (capture.MAX_B64 + 4)},
    {"status": "maybe"},
])
def test_bad_frame(reply):
    online(FakeWS(responder=lambda m: dict(reply)))
    with pytest.raises(capture.CaptureError) as e:
        run(capture.request(MASTER, "ask"))
    assert e.value.code == "bad_frame"


def test_timeout():
    online(FakeWS())                                      # клиент молчит
    with pytest.raises(capture.CaptureError) as e:
        run(capture.request(MASTER, "ask", timeout=0.05))
    assert e.value.code == "timeout"
    assert capture._waiters == {}


def test_frame_from_other_device_ignored():
    online(FakeWS(responder=lambda m: {**ok()(m), "device_id": "pc"}))
    with pytest.raises(capture.CaptureError) as e:
        run(capture.request(MASTER, "ask", timeout=0.1))
    assert e.value.code == "timeout"


def test_stray_frame_is_ignored():
    run(capture.handle_frame(FakeWS(), {"type": "vision.frame", "request_id": "vc-нет",
                                        "device_id": MASTER, "status": "ok"}))


def test_disconnect_while_waiting():
    online(FakeWS())

    async def go():
        task = asyncio.ensure_future(capture.request(MASTER, "ask", timeout=2))
        await asyncio.sleep(0.01)
        capture.forget(MASTER)
        return await task

    with pytest.raises(capture.CaptureError) as e:
        run(go())
    assert e.value.code == "offline"


def test_frame_repr_has_no_bytes():
    f = capture.Frame(MASTER, JPEG * 100)
    assert "\\xff" not in repr(f) and "KiB" in repr(f)
