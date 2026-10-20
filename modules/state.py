"""Mutable shared state for the Sakura server.

Imported by both main.py and modules/ws_handlers.py to avoid circular imports.
All dicts are module-level singletons — import by reference, never reassign.
"""

from __future__ import annotations

connected_devices: dict = {}
# device_id → версия протокола из register (2 — настольный клиент v2)
device_proto: dict[str, int] = {}
_pending_event_check: dict = {}   # device_id → True если ждём скриншот для event-тика
_pending_describe: dict = {}      # device_id → True если ждём скриншот для описания
_pending_commands: dict[str, dict] = {}  # cmd_id → {"action", "device", "ts", "status"}
_pending_clarify: dict[str, dict] = {}   # master_key → {"text", "main", "alt", "ts"}
_last_executed: dict[str, dict] = {}     # master_key → {"text", "action", "ts"}
_pending_plan: dict[str, dict] = {}      # master_key → {"text", "plan", "ts"}
_pending_system: dict[str, dict] = {}    # master_key → {"action", "device", "ts"} — подтверждение опасных system:* команд, TTL 60с
_plan_cancel: dict[str, bool] = {}       # master_key → True если отмена
_last_command_ts: float = 0.0   # время последней выполненной команды
# Трек — отдельно по устройствам; новая запись заменяет старую целиком.
# device_id → {"track": dict, "ts": monotonic времени приёма}
device_tracks: dict[str, dict] = {}
TRACK_MAX_AGE_S = 60.0          # старше — агент перестал сообщать, трек не считаем

# ── Прерывание долгой озвучки (полный список ачивок и др.) ───────────
# key = device_id (голос) или "tg" (телеграм-канал).
_tts_reading: dict[str, bool] = {}  # key → True, идёт многочастная озвучка
_tts_stop: dict[str, bool] = {}     # key → True, просят остановить чтение


def tts_reading_start(key: str) -> None:
    _tts_reading[key or "laptop"] = True


def tts_reading_end(key: str) -> None:
    _tts_reading.pop(key or "laptop", None)
    _tts_stop.pop(key or "laptop", None)


def tts_is_reading(key: str) -> bool:
    return bool(_tts_reading.get(key or "laptop"))


def tts_request_stop(key: str) -> None:
    """Попросить активное чтение остановиться («стоп», «хватит»)."""
    _tts_stop[key or "laptop"] = True


def tts_request_stop_anywhere() -> int:
    """Стоп для ВСЕХ активных чтений (например, «стоп» из Telegram,
    где неизвестно, на каком устройстве идёт озвучка).
    → сколько активных чтений было."""
    keys = [k for k, v in _tts_reading.items() if v]
    for k in keys:
        _tts_stop[k] = True
    return len(keys)


def tts_stop_requested(key: str) -> bool:
    return bool(_tts_stop.get(key or "laptop"))


# ── Подтверждение/отмена опасных системных команд ─────────────────────
def check_confirmation(text: str) -> str | None:
    """Общий strict parser для v3-сессий и legacy pending-команд."""
    from sakura_core.session import check_confirmation as _check_confirmation

    return _check_confirmation(text)


# ── Треки по устройствам ─────────────────────────────────────────────

def _track_playing(track: dict | None) -> bool:
    return bool(track and track.get("title") and track.get("status") == "играет")


def set_device_track(device_id: str, track: dict, now: float | None = None) -> None:
    """Запись целиком (не merge): поля прежнего трека не переживают новый."""
    import time
    device_tracks[device_id or "laptop"] = {
        "track": dict(track), "ts": time.monotonic() if now is None else now}


def device_track(device_id: str | None, now: float | None = None) -> dict:
    """Свежий трек устройства или {}."""
    import time
    rec = device_tracks.get(device_id or "")
    if not rec:
        return {}
    t = time.monotonic() if now is None else now
    return rec["track"] if t - rec["ts"] <= TRACK_MAX_AGE_S else {}


def prompt_track(active: str | None = None, now: float | None = None) -> dict:
    """Трек для промпта: активного ПК; если там тишина — самый свежий играющий
    трек любого ПК не старше TRACK_MAX_AGE_S; иначе (пауза) трек активного."""
    import time
    t = time.monotonic() if now is None else now
    if active is None:
        try:
            from modules.presence_sync import get_active_device
            active = get_active_device()
        except Exception:
            active = None
    own = device_track(active, t)
    if _track_playing(own):
        return own
    best, best_ts = {}, None
    for rec in list(device_tracks.values()):
        if t - rec["ts"] <= TRACK_MAX_AGE_S and _track_playing(rec["track"]) \
                and (best_ts is None or rec["ts"] > best_ts):
            best, best_ts = rec["track"], rec["ts"]
    return best or (own if own.get("title") else {})
