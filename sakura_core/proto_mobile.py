"""Протокол v2 — интеграция мобильного пульта, виджетов и голоса (remote_command, widgets_data, voice_audio).

Все три запроса приватны (PRIVATE_PREFIXES в proto_v2): требуют master-устройства
и защищённого Noise-канала.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import time
import uuid

import modules.state as st
from sakura_core import proto_devices, proto_v2, voice_turns
from sakura_core.proto_v2 import V2Error

log = logging.getLogger("sakura.mobile_v2")

_MAX_AUDIO_BYTES = 4 * 1024 * 1024
_ALLOWED_MIME = frozenset({
    "audio/mp4", "audio/m4a", "audio/aac", "audio/mpeg", "audio/wav",
    "audio/x-wav", "audio/webm", "audio/ogg",
})
_LEGACY_SYSTEM = {
    "system.shutdown": "system:shutdown",
    "system.restart": "system:restart",
    "system.sleep": "system:sleep",
    "system.lock": "system:lock",
    "system.shutdown_cancel": "system:shutdown_cancel",
}


def _pick_target_pc(requested: str | None) -> tuple[str, object]:
    """Найти онлайн-устройство ПК (явный target или первый онлайн PC)."""
    devs = proto_devices.devices()
    if requested and requested != "auto":
        ws = st.connected_devices.get(requested)
        if ws is None:
            raise V2Error("offline", f"Устройство {requested} не в сети")
        return requested, ws
    for preferred in ("pc", "laptop"):
        if preferred in st.connected_devices:
            return preferred, st.connected_devices[preferred]
    for d in devs:
        if d.get("online") and d.get("kind") == "pc" and d["id"] in st.connected_devices:
            return d["id"], st.connected_devices[d["id"]]
    raise V2Error("offline", "Компьютер не в сети")


def _normalize_remote_wire(action: str, arg: str) -> tuple[str, str]:
    a = (action or "").strip()
    v = (arg or "").strip()
    if a == "system.volume_up":
        step = v.lstrip("+") if v else "10"
        return "system.volume", f"+{step if step.isdigit() else '10'}"
    if a == "system.volume_down":
        step = v.lstrip("-") if v else "10"
        return "system.volume", f"-{step if step.isdigit() else '10'}"
    if a == "power.sleep":
        return "system.sleep", ""
    return a, v


async def _remote_command(websocket, data: dict, ctx: dict) -> dict:
    """Мгновенное выполнение команды с мобильного пульта на онлайн-ПК без подтверждения."""
    action = str(data.get("action") or "").strip()
    if not action:
        raise V2Error("bad_request", "action: нужна команда")
    arg = str(data.get("arg") or "").strip()
    target_req = data.get("target")
    target_id, target_ws = _pick_target_pc(str(target_req).strip() if target_req else None)

    wire_action, wire_arg = _normalize_remote_wire(action, arg)
    cmd_id = uuid.uuid4().hex[:10]
    if st.device_proto.get(target_id) == 2 or wire_action not in _LEGACY_SYSTEM:
        msg: dict[str, object] = {
            "type": "command",
            "action": wire_action,
            "id": cmd_id,
            "confirmed": bool(data.get("confirmed", True)),
        }
        if wire_arg:
            msg["arg"] = wire_arg
    else:
        msg = {"type": "command", "action": _LEGACY_SYSTEM[wire_action]}

    reg = ctx.get("_register_command") if isinstance(ctx, dict) else None
    if callable(reg):
        try:
            reg(wire_action, target_id)
        except Exception:
            pass
    try:
        await target_ws.send(json.dumps(msg))
    except Exception as e:
        raise V2Error("offline", f"Не удалось отправить на {target_id}: {e}") from e

    st._last_command_ts = time.monotonic()
    log.info(f"[mobile] remote_command {data.get('device_id')} → {target_id}: {wire_action} {wire_arg!r}")
    return {
        "type": "remote_command_ok",
        "target": target_id,
        "action": wire_action,
        "id": cmd_id,
    }


def _lesson_wire(lesson) -> dict:
    return {
        "date": lesson.date.isoformat(),
        "start": f"{lesson.start:%H:%M}",
        "end": f"{lesson.end:%H:%M}",
        "subject": lesson.subject,
        "room": lesson.room or "",
        "teacher": lesson.teacher or "",
        "kind": lesson.kind_raw or "",
    }


def _build_widgets_snapshot(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    today = now.date()
    tomorrow = today + dt.timedelta(days=1)

    schedule_out: dict = {
        "has_data": False,
        "stale": True,
        "today_label": "Сегодня",
        "tomorrow_label": "Завтра",
        "today": [],
        "tomorrow": [],
        "current": None,
        "next": None,
    }
    try:
        from sakura_core.schedule import query as sched
        has_data = sched.has_data()
        cur = sched.current_lesson(now)
        nxt = sched.next_lesson(now)
        schedule_out = {
            "has_data": has_data,
            "stale": sched.is_stale(now) if has_data else True,
            "today_label": sched.day_label(today, today),
            "tomorrow_label": sched.day_label(tomorrow, today),
            "today": [_lesson_wire(x) for x in sched.on(today)],
            "tomorrow": [_lesson_wire(x) for x in sched.on(tomorrow)],
            "current": _lesson_wire(cur) if cur else None,
            "next": _lesson_wire(nxt) if nxt else None,
        }
    except Exception as e:
        log.debug(f"[mobile] widgets schedule: {e}")

    mem_counts: dict = {}
    mem_total = 0
    try:
        from memory.db import list_memories
        _, mem_total, mem_counts = list_memories(None, 0, 1)
    except Exception as e:
        log.debug(f"[mobile] widgets memory: {e}")

    pc_dev = None
    for d in proto_devices.devices():
        if d.get("kind") == "pc":
            if pc_dev is None or (d.get("online") and not pc_dev.get("online")):
                pc_dev = d

    return {
        "type": "widgets_data",
        "schedule": schedule_out,
        "memory": {"total": mem_total, "counts": mem_counts},
        "pc": pc_dev,
        "status": proto_devices.status(today),
    }


async def _widgets_data(websocket, data: dict, ctx: dict) -> dict:
    return await asyncio.to_thread(_build_widgets_snapshot)


async def _voice_audio(websocket, data: dict, ctx: dict) -> dict:
    """Принять записанное с телефона аудио (base64), распознать речь и запустить ход Сакуры."""
    raw_b64 = data.get("audio")
    if not raw_b64 or not isinstance(raw_b64, str):
        raise V2Error("bad_request", "audio: нужна base64-строка аудио")
    try:
        audio_bytes = base64.b64decode(raw_b64, validate=True)
    except Exception as e:
        raise V2Error("bad_request", f"audio: некорректный base64 ({e})") from e
    if not audio_bytes or len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise V2Error("bad_request", "audio: пустой или слишком большой файл")

    mime = str(data.get("mime_type") or "audio/mp4").split(";")[0].strip().lower()
    if mime == "audio/x-m4a":
        mime = "audio/mp4"
    if mime not in _ALLOWED_MIME:
        mime = "audio/mp4"

    from sakura_core.llm import transcribe_audio
    transcript = await transcribe_audio(audio_bytes, mime)
    if not transcript:
        return {"type": "voice_audio_ok", "transcript": ""}

    device_id = str(data.get("device_id") or "phone")
    speak = data.get("speak") is not False

    from sakura_core import chat_hooks
    turn_id = voice_turns.new_turn_id()
    msg, created = await chat_hooks.record(
        "user", "voice", transcript, device=device_id,
        meta={"turn_id": turn_id}, push=False,
    )
    if msg is not None and created:
        await chat_hooks.push_message(msg)

    from adapters.ws import handle_voice_command
    turn_data = {
        "type": "voice_command",
        "device_id": device_id,
        "text": transcript,
        "channel": "voice",
        "active_window": str(data.get("active_window") or ""),
        "context": [],
        "_chat_msg_id": msg["id"] if msg else None,
        "speak": speak,
    }
    voice_turns.start(
        device_id, websocket,
        lambda: handle_voice_command(websocket, turn_data, ctx),
        turn_id=turn_id,
        speak=speak,
    )
    return {"type": "voice_audio_ok", "transcript": transcript, "turn_id": turn_id}


proto_v2.register("remote_command", _remote_command)
proto_v2.register("widgets_data", _widgets_data)
proto_v2.register("voice_audio", _voice_audio)
