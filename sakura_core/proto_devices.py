"""Протокол v2, порция 2: устройства и статус (без личного текста чата —
выкатывается без шифрования).

  devices_request  → devices {devices: [Device]}
  status_request   → status {tone, mode, context, quote}
  пуш device_update {device}  — изменилось состояние устройства
  пуш status {tone, mode, context, quote} — изменился статус

Device (desktop/tools/fixtures/devices.json):
  {"id", "name", "kind": pc|phone|tablet|headphones|other, "online",
   "last_seen", "focus", "stats": {"cpu", "ram", "gpu", "battery",
   "charging", "wifi", "signal"}}
stats — последние из heartbeat (register/ping: system_info), focus — из
присутствия (presence_sync.get_active_device). Хранится в памяти процесса.

status: tone — TTS_TONE (id: neutral, warm, dry, serious, quiet, cheerful),
mode — по присутствию и окну (normal | game | call | away), context —
что делает Мастер (категория активного окна, без заголовка), quote —
цитата дня из data/quotes.json.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from pathlib import Path

import modules.state as st
from sakura_core import proto_v2

log = logging.getLogger(__name__)

QUOTES_FILE = Path(__file__).resolve().parent.parent / "data" / "quotes.json"
STATS_KEYS = ("cpu", "ram", "gpu", "battery", "charging", "wifi", "signal")
# device_update по нагрузке — при скачке не меньше этого или раз в минуту.
LOAD_STEP = 10
PUSH_EVERY_S = 60.0

from sakura_core.tones import TONE_IDS  # noqa: E402
CONTEXT_BY_CATEGORY = {"call": "Созвон", "game": "Игра", "code": "Работа с кодом",
                       "browser": "Браузер", "media": "Музыка или видео",
                       "other": "Работа за компьютером"}
MODE_BY_CATEGORY = {"game": "game", "call": "call"}

_devices: dict[str, dict] = {}       # device_id → {stats, last_seen, name, kind, window}
_last_pushed: dict[str, tuple[dict, float]] = {}
_last_status: dict | None = None


# ── устройство ─────────────────────────────────────────────────────

def _kind(device_id: str, hint: str | None = None) -> str:
    if hint in ("pc", "phone", "tablet", "headphones", "other"):
        return hint
    d = device_id.lower()
    if "phone" in d or "tel" in d:
        return "phone"
    if "tab" in d or "pad" in d:
        return "tablet"
    if "head" in d or "buds" in d or "pods" in d:
        return "headphones"
    return "pc"


def _name(device_id: str, hint: str | None = None) -> str:
    if hint:
        return str(hint)[:40]
    from modules.device_manager import KNOWN_DEVICES
    known = KNOWN_DEVICES.get(device_id)
    return known["name"] if known else device_id


def _stats(system_info: dict | None) -> dict:
    si = system_info if isinstance(system_info, dict) else {}
    out = {}
    for k in STATS_KEYS:
        v = si.get(k)
        if k == "charging" and v is None and "plugged" in si:
            v = si.get("plugged")
        out[k] = v
    if not any(v is not None for v in out.values()):
        return {}
    return out


def _focused() -> str | None:
    try:
        from modules.presence_sync import get_active_device
        return get_active_device()
    except Exception as e:
        log.debug(f"[v2] присутствие: {type(e).__name__}: {e}")
        return None


def device(device_id: str, focus_id: str | None = None) -> dict:
    """Device протокола v2."""
    info = _devices.get(device_id, {})
    return {
        "id": device_id,
        "name": _name(device_id, info.get("name")),
        "kind": _kind(device_id, info.get("kind")),
        "online": device_id in st.connected_devices,
        "last_seen": float(info.get("last_seen") or 0.0) or None,
        "focus": device_id == focus_id,
        "stats": dict(info.get("stats") or {}),
    }


def devices() -> list[dict]:
    focus = _focused()
    ids = sorted(set(_devices) | set(st.connected_devices))
    return [device(i, focus) for i in ids]


def _significant(old: dict | None, new: dict) -> bool:
    if old is None:
        return True
    for k in ("online", "focus", "name", "kind"):
        if old.get(k) != new.get(k):
            return True
    os_, ns = old.get("stats") or {}, new.get("stats") or {}
    for k in ("battery", "charging", "wifi", "signal"):
        if os_.get(k) != ns.get(k):
            return True
    for k in ("cpu", "ram", "gpu"):
        a, b = os_.get(k), ns.get(k)
        if (a is None) != (b is None):
            return True
        if a is not None and b is not None and abs(float(a) - float(b)) >= LOAD_STEP:
            return True
    return False


async def push_device(device_id: str, *, force: bool = False) -> None:
    focus = await asyncio.to_thread(_focused)
    d = device(device_id, focus)
    prev = _last_pushed.get(device_id)
    now = time.monotonic()
    if not force and prev is not None and not _significant(prev[0], d) \
            and now - prev[1] < PUSH_EVERY_S:
        return
    _last_pushed[device_id] = (d, now)
    await proto_v2.broadcast({"type": "device_update", "device": d})


# ── статус ─────────────────────────────────────────────────────────

def _quote(today: dt.date | None = None) -> str:
    try:
        quotes = json.loads(QUOTES_FILE.read_text(encoding="utf-8")).get("quotes") or []
    except Exception as e:
        log.debug(f"[v2] цитаты: {type(e).__name__}: {e}")
        return ""
    if not quotes:
        return ""
    day = (today or dt.date.today()).toordinal()
    return str(quotes[day % len(quotes)])


def status(today: dt.date | None = None) -> dict:
    from modules.tts_server import TTS_TONE
    tone = TONE_IDS.get((TTS_TONE or "").strip().lower(), "neutral")
    focus = _focused()
    masters_online = [d for d in st.connected_devices if proto_v2._is_master(d)]
    if not masters_online:
        mode, context = "away", "Мастер не за компьютером"
    else:
        window = (_devices.get(focus or "", {}) or {}).get("window") or ""
        from sakura_core.prompt import _window_category
        category = _window_category(window) if window else "other"
        mode = MODE_BY_CATEGORY.get(category, "normal")
        context = CONTEXT_BY_CATEGORY.get(category, CONTEXT_BY_CATEGORY["other"])
    return {"tone": tone, "mode": mode, "context": context, "quote": _quote(today)}


async def push_status(*, force: bool = False) -> None:
    global _last_status
    s = await asyncio.to_thread(status)
    if not force and s == _last_status:
        return
    _last_status = s
    await proto_v2.broadcast({"type": "status", **s})


# ── точки входа ────────────────────────────────────────────────────

async def on_heartbeat(device_id: str | None, data: dict) -> None:
    """register / ping: последние stats и окно, пуши при изменениях.
    Ошибка здесь не мешает обработке heartbeat."""
    if not device_id:
        return
    try:
        info = _devices.setdefault(device_id, {})
        info["last_seen"] = time.time()
        if data.get("system_info") is not None:
            info["stats"] = _stats(data.get("system_info"))
        if data.get("active_window") is not None:
            info["window"] = str(data.get("active_window") or "")
        for src, dst in (("device_name", "name"), ("device_kind", "kind")):
            if data.get(src):
                info[dst] = data[src]
        await push_device(device_id)
        await push_status()
    except Exception as e:
        log.debug(f"[v2] heartbeat {device_id}: {type(e).__name__}: {e}")


async def on_disconnect(device_id: str | None) -> None:
    if not device_id:
        return
    try:
        _devices.setdefault(device_id, {})["last_seen"] = time.time()
        await push_device(device_id, force=True)
        await push_status()
    except Exception as e:
        log.debug(f"[v2] отключение {device_id}: {type(e).__name__}: {e}")


# ── запросы ────────────────────────────────────────────────────────

async def _devices_request(websocket, data: dict, ctx: dict) -> dict:
    return {"type": "devices", "devices": await asyncio.to_thread(devices)}


async def _status_request(websocket, data: dict, ctx: dict) -> dict:
    return {"type": "status", **await asyncio.to_thread(status)}


def secure_devices() -> list[dict]:
    """Реестр securechannel для master: без ключей и PSK."""
    from sakura_core import secure_policy
    if secure_policy.mode() == "off":
        return []
    out = []
    for d in secure_policy.context().registry.list():
        ws = st.connected_devices.get(d["id"])
        out.append({
            "device_id": d["id"],
            "name": d.get("name"),
            "fingerprint": str(d.get("fp") or "").replace(" ", "")[:16],
            "paired_at": d.get("created"),
            "last_seen": d.get("last_seen"),
            "online": ws is not None,
            "secure_now": ws is not None and getattr(ws, "transport", None) == "noise",
            "revoked": bool(d.get("revoked")),
        })
    return out


async def _secure_devices(websocket, data: dict, ctx: dict) -> dict:
    # Всегда только secure — независимо от PRIVATE_REQUIRES_SECURE.
    if not proto_v2.connection_secure(websocket):
        raise proto_v2.V2Error("secure_channel_required", "нужен защищённый канал")
    me = data.get("device_id")
    devs = await asyncio.to_thread(secure_devices)
    for d in devs:
        d["current"] = d["device_id"] == me
    return {"type": "secure_devices", "devices": devs}


proto_v2.register("devices_request", _devices_request)
proto_v2.register("status_request", _status_request)
proto_v2.register("secure_devices", _secure_devices)
