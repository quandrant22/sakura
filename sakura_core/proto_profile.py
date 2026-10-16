"""Протокол v2, порция 3: профиль Мастера (profile_get / profile_set).

  profile_get                         → profile {profile}
  profile_set {любые из name, address_as, quiet_hours, voice, tone,
               notifications}         → profile {profile}

Хранение — PROFILE_PATH (memory/profile_v2.json, права 600); применяется
на лету: tone → TTS_TONE, voice → TTS_VOICE озвучки; quiet_hours — для
шлюза проактива (get_quiet_hours), name/address_as — get_profile(). При
старте сохранённое применяется снова. Пуш profile — всем master с proto 2.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading

import config
from sakura_core import proto_v2
from sakura_core.proto_v2 import V2Error
from sakura_core.tones import TONE_FROM_ID, TONE_IDS

log = logging.getLogger("sakura.profile")

DEFAULTS = {"name": "Мастер", "address_as": "вы", "quiet_hours": "",
            "voice": "", "tone": "", "notifications": {"telegram": True, "sound": True}}
_QUIET = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
_VOICE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,23}$")
_lock = threading.Lock()


def _path() -> str:
    return getattr(config, "PROFILE_PATH", "memory/profile_v2.json")


def _read() -> dict:
    import json
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}
    out = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    return out


def _write(profile: dict) -> None:
    import json
    import os
    import tempfile
    d = os.path.dirname(os.path.abspath(_path()))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".profile-", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, _path())


def get_profile() -> dict:
    with _lock:
        return _read()


def get_quiet_hours() -> tuple[str, str] | None:
    q = get_profile().get("quiet_hours") or ""
    return tuple(q.split("-")) if _QUIET.match(q) else None


def _effective(profile: dict) -> dict:
    """Профиль для клиента: пустые tone/voice — текущие значения озвучки."""
    import modules.tts_server as tts
    out = dict(profile)
    out["tone"] = profile.get("tone") or TONE_IDS.get(tts.TTS_TONE, "neutral")
    out["voice"] = profile.get("voice") or tts.TTS_VOICE
    return out


def apply(profile: dict) -> None:
    """На лету: тон и голос озвучки."""
    import modules.tts_server as tts
    if profile.get("tone") in TONE_FROM_ID:
        tts.TTS_TONE = TONE_FROM_ID[profile["tone"]]
    if profile.get("voice"):
        tts.TTS_VOICE = profile["voice"]


def validate(patch: dict) -> dict:
    out = {}
    for k, v in patch.items():
        if k in ("name", "address_as"):
            if not isinstance(v, str) or not v.strip() or len(v) > 40:
                raise V2Error("bad_request", f"{k}: строка 1–40 символов")
            out[k] = v.strip()
        elif k == "quiet_hours":
            if not isinstance(v, str) or (v and not _QUIET.match(v)):
                raise V2Error("bad_request", "quiet_hours: ЧЧ:ММ-ЧЧ:ММ или пусто")
            out[k] = v
        elif k == "voice":
            if not isinstance(v, str) or not _VOICE.match(v):
                raise V2Error("bad_request", "voice: имя голоса латиницей")
            out[k] = v
        elif k == "tone":
            if v not in TONE_FROM_ID:
                raise V2Error("bad_request", f"tone: одно из {', '.join(sorted(TONE_FROM_ID))}")
            out[k] = v
        elif k == "notifications":
            if not isinstance(v, dict) or not all(isinstance(x, bool) for x in v.values()) \
                    or not set(v) <= {"telegram", "sound"}:
                raise V2Error("bad_request", "notifications: {telegram, sound} — true/false")
            out[k] = v
    return out


def set_profile(patch: dict) -> dict:
    with _lock:
        profile = {**_read(), **patch}
        _write(profile)
    apply(profile)
    return profile


def apply_saved() -> None:
    try:
        apply(get_profile())
    except Exception as e:
        log.debug(f"[profile] применение при старте: {type(e).__name__}")


async def _profile_get(ws, data, ctx):
    return {"type": "profile", "profile": _effective(await asyncio.to_thread(get_profile))}


async def _profile_set(ws, data, ctx):
    fields = {k: data[k] for k in DEFAULTS if k in data}
    if not fields:
        raise V2Error("bad_request", "нет полей профиля")
    patch = validate(fields)
    profile = _effective(await asyncio.to_thread(set_profile, patch))
    log.info(f"[profile] изменены поля: {', '.join(sorted(patch))} ({data.get('device_id')})")
    await proto_v2.broadcast({"type": "profile", "profile": profile})
    return {"type": "profile", "profile": profile}


proto_v2.register("profile_get", _profile_get)
proto_v2.register("profile_set", _profile_set)
apply_saved()
