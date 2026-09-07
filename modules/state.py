"""Mutable shared state for the Sakura server.

Imported by both main.py and modules/ws_handlers.py to avoid circular imports.
All dicts are module-level singletons — import by reference, never reassign.
"""

from __future__ import annotations

connected_devices: dict = {}
_pending_event_check: dict = {}   # device_id → True если ждём скриншот для event-тика
_pending_describe: dict = {}      # device_id → True если ждём скриншот для описания
_pending_commands: dict[str, dict] = {}  # cmd_id → {"action", "device", "ts", "status"}
_pending_clarify: dict[str, dict] = {}   # master_key → {"text", "main", "alt", "ts"}
_last_executed: dict[str, dict] = {}     # master_key → {"text", "action", "ts"}
_pending_plan: dict[str, dict] = {}      # master_key → {"text", "plan", "ts"}
_pending_system: dict[str, dict] = {}    # master_key → {"action", "device", "ts"} — подтверждение опасных system:* команд, TTL 60с
_plan_cancel: dict[str, bool] = {}       # master_key → True если отмена
_last_command_ts: float = 0.0   # время последней выполненной команды
_current_track: dict = {}       # текущий играющий трек (из агента)

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
