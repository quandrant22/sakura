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
_plan_cancel: dict[str, bool] = {}       # master_key → True если отмена
_last_command_ts: float = 0.0   # время последней выполненной команды
_current_track: dict = {}       # текущий играющий трек (из агента)
