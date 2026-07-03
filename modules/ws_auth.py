"""
modules/ws_auth.py — аутентификация WebSocket-соединений.

Каждое входящее сообщение проверяется по токену из .env (WS_SECRET).
Деструктивные команды (wipe памяти) — только от master-устройств.
"""

import hmac
import logging
import os

log = logging.getLogger("sakura.ws_auth")

_WS_SECRET: str = os.getenv("WS_SECRET", "").strip()

_MASTER_DEVICES: set[str] = set(
    d.strip() for d in os.getenv("MASTER_DEVICES", "laptop,pc").split(",") if d.strip()
)

# Только реально деструктивные операции требуют master-устройства.
# apps_list убран — это безопасная операция (список приложений).
DESTRUCTIVE_COMMANDS = frozenset({
    "voice_command",   # голосовые команды (включая «протокол чистый лист»)
})


def validate_secret_on_startup() -> None:
    if not _WS_SECRET:
        raise RuntimeError(
            "WS_SECRET не задан в .env. "
            "Сгенерируй: python generate_token.py"
        )
    if len(_WS_SECRET) < 16:
        raise RuntimeError(
            f"WS_SECRET слишком короткий ({len(_WS_SECRET)} символов). Минимум 16."
        )
    log.info(f"WS-аутентификация активна. Master-устройства: {_MASTER_DEVICES}")


def check_token(data: dict) -> bool:
    """Проверяет токен. Устойчив к пробелам и переносам строк."""
    incoming = str(data.get("token", "")).strip()
    if not incoming:
        return False
    return hmac.compare_digest(incoming.encode(), _WS_SECRET.encode())


def is_master_device(device_id: str | None) -> bool:
    return bool(device_id and device_id.strip() in _MASTER_DEVICES)


async def reject(websocket, reason: str = "unauthorized") -> None:
    import websockets as _ws
    peer = getattr(websocket, "remote_address", "unknown")
    log.warning(f"[ws_auth] ОТКЛОНЕНО {peer}: {reason}")
    await websocket.close(code=4401, reason=reason)