"""capture — кадр экрана с ПК по запросу сервера.

Сервер → клиент:
  {"type": "vision.capture", "request_id", "purpose": "ask|glance|watch",
   "max_side", "quality", "need_change"}
Клиент → сервер (ответ с тем же request_id):
  {"type": "vision.frame", "request_id", "device_id", "status": "ok",
   "image": <JPEG|PNG base64>, "window": {"title", "process"}, "changed"}
  {"type": "vision.frame", "request_id", "device_id", "status": "skipped",
   "reason": "private_window|unchanged|disabled|capture_failed|no_display"}

Клиент объявляет поддержку в register: "features": ["vision.capture"].
Только master-устройства и только защищённый канал (кадр — приватный
класс). Кадр в лог не пишется: в лог — устройство, цель, размер, итог.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
import uuid
from dataclasses import dataclass

import config

log = logging.getLogger("sakura.vision")

FEATURE = "vision.capture"
PURPOSES = ("ask", "glance", "watch")
SKIP_REASONS = ("private_window", "unchanged", "disabled", "capture_failed", "no_display")
MAX_B64 = 2_000_000                 # как у vision_request (WINDOW_ASK_MAX_B64)
TITLE_MAX = 200
PROCESS_MAX = 80


@dataclass(frozen=True)
class Frame:
    device_id: str
    image: bytes = b""
    mime: str = "image/jpeg"
    title: str = ""
    process: str = ""
    changed: bool = True

    def __repr__(self) -> str:      # байты кадра не попадают в лог даже через repr
        return (f"Frame(device_id={self.device_id!r}, {len(self.image) // 1024} KiB, "
                f"mime={self.mime!r}, changed={self.changed})")


@dataclass(frozen=True)
class Skipped:
    reason: str


class CaptureError(Exception):
    """Кадр не получен по вине канала/устройства: code — для ответа и тестов."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_features: dict[str, frozenset[str]] = {}
_waiters: dict[str, tuple[str, asyncio.Future]] = {}


# ── объявленные возможности клиента ────────────────────────────────

def note_features(device_id: str | None, data: dict) -> None:
    """register/ping: запомнить features клиента (нет поля — не трогать)."""
    if not device_id or "features" not in data:
        return
    feats = data.get("features")
    if not isinstance(feats, (list, tuple)):
        feats = ()
    _features[device_id] = frozenset(str(f) for f in feats if isinstance(f, str))


def supports(device_id: str | None) -> bool:
    return bool(device_id) and FEATURE in _features.get(device_id, frozenset())


def forget(device_id: str | None) -> None:
    """Устройство отключилось: возможности и ожидающие запросы снимаются."""
    if not device_id:
        return
    _features.pop(device_id, None)
    for rid, (dev, fut) in list(_waiters.items()):
        if dev == device_id and not fut.done():
            fut.set_exception(CaptureError("offline", "устройство отключилось"))
            _waiters.pop(rid, None)


def reset() -> None:
    """Для тестов."""
    _features.clear()
    for _, fut in _waiters.values():
        if not fut.done():
            fut.cancel()
    _waiters.clear()


# ── запрос кадра ───────────────────────────────────────────────────

def _mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def _secure_ok(websocket) -> bool:
    if not getattr(config, "PRIVATE_REQUIRES_SECURE", True):
        return True
    from sakura_core.proto_v2 import connection_secure
    return connection_secure(websocket)


async def request(device_id: str, purpose: str, *, need_change: bool = False,
                  max_side: int = 1280, quality: int = 70,
                  timeout: float | None = None) -> Frame | Skipped:
    """Запросить кадр у ПК. Frame — кадр; Skipped — клиент отказал сам;
    CaptureError — нет канала, нет поддержки, таймаут, битый ответ."""
    if purpose not in PURPOSES:
        raise ValueError(f"vision: неизвестная цель {purpose!r}")
    import modules.state as st
    from modules.ws_auth import is_master_device
    if not is_master_device(device_id):
        raise CaptureError("not_master", "кадр — только с master-устройства")
    ws = st.connected_devices.get(device_id)
    if ws is None:
        raise CaptureError("offline", "устройство не в сети")
    if not supports(device_id):
        raise CaptureError("unsupported", "клиент не умеет vision.capture")
    if not _secure_ok(ws):
        raise CaptureError("secure_channel_required", "кадр экрана — только по защищённому каналу")

    rid = f"vc-{uuid.uuid4().hex[:12]}"
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _waiters[rid] = (device_id, fut)
    t0 = time.monotonic()
    try:
        await ws.send(json.dumps({
            "type": "vision.capture", "request_id": rid, "purpose": purpose,
            "max_side": int(max_side), "quality": int(quality),
            "need_change": bool(need_change),
        }))
        result = await asyncio.wait_for(
            fut, timeout if timeout is not None else config.VISION_CAPTURE_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.info(f"[vision] {device_id}: {purpose} — нет ответа за "
                 f"{time.monotonic() - t0:.1f}с")
        raise CaptureError("timeout", "ПК не прислал кадр") from None
    except CaptureError:
        raise
    except Exception as e:
        raise CaptureError("send_failed", f"запрос не ушёл: {type(e).__name__}") from None
    finally:
        _waiters.pop(rid, None)
    if isinstance(result, Frame):
        log.info(f"[vision] {device_id}: {purpose} — кадр {len(result.image) // 1024} КиБ "
                 f"({result.mime}) за {time.monotonic() - t0:.1f}с")
    else:
        log.info(f"[vision] {device_id}: {purpose} — пропуск ({result.reason})")
    return result


def _parse(device_id: str, data: dict) -> Frame | Skipped:
    status = data.get("status")
    if status == "skipped":
        reason = str(data.get("reason") or "")
        return Skipped(reason if reason in SKIP_REASONS else "capture_failed")
    if status != "ok":
        raise CaptureError("bad_frame", "неизвестный status")
    image = data.get("image")
    if not isinstance(image, str) or not image or len(image) > MAX_B64:
        raise CaptureError("bad_frame", "нет кадра или он слишком большой")
    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        raise CaptureError("bad_frame", "кадр не в base64") from None
    mime = _mime(raw)
    if mime is None:
        raise CaptureError("bad_frame", "кадр не JPEG и не PNG")
    window = data.get("window") if isinstance(data.get("window"), dict) else {}
    return Frame(device_id=device_id, image=raw, mime=mime,
                 title=str(window.get("title") or "")[:TITLE_MAX],
                 process=str(window.get("process") or "")[:PROCESS_MAX],
                 changed=data.get("changed") is not False)


async def handle_frame(websocket, data: dict) -> None:
    """vision.frame от клиента: отдать ожидающему запросу. Чужой или
    устаревший request_id, ответ не с того устройства — молча мимо."""
    rid = data.get("request_id")
    waiter = _waiters.get(rid) if isinstance(rid, str) else None
    if waiter is None:
        log.debug("[vision] frame без ожидающего запроса — пропущен")
        return
    device_id, fut = waiter
    if data.get("device_id") != device_id or fut.done():
        log.warning(f"[vision] frame {rid}: не от того устройства — пропущен")
        return
    try:
        fut.set_result(_parse(device_id, data))
    except CaptureError as e:
        fut.set_exception(e)
