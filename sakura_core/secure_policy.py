"""Политика защищённого канала для WebSocket (docs/security/PROTOCOL.md §1, §5.1).

  SECURE_CHANNEL=off       — только старый протокол (JSON + token);
                 optional  — и Noise, и токен;
                 required  — только Noise (текст → закрытие 4412).

Соединение secure, если оно аутентифицировано Noise ИЛИ адрес источника
(из сокета, не из заголовков) — loopback или адрес интерфейса самого
сервера (клиенты, пришедшие через локальный xray/VPN).

Приватные классы сообщений (чат, история, память, профиль, кадры экрана)
при PRIVATE_REQUIRES_SECURE=1 обслуживаются только на secure-соединениях.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time

import config

log = logging.getLogger("sakura.securechannel")

MODES = ("off", "optional", "required")
PRIVATE_PREFIXES = ("chat_", "history_", "memory_", "profile_")
PRIVATE_TYPES = frozenset({"vision_request", "computer_step"})
SECURE_HINT = ("приватные данные — только по защищённому каналу: подключитесь "
               "через Noise (SECURE_CHANNEL) или VPN")

_ctx = None
_ctx_lock = threading.Lock()
_local_cache: tuple[float, frozenset[str]] = (0.0, frozenset())
LOCAL_ADDR_TTL_S = 60.0


def mode() -> str:
    m = (getattr(config, "SECURE_CHANNEL", "off") or "off").strip().lower()
    return m if m in MODES else "off"


def context():
    """Ключ сервера, реестр, спаривание, лимиты — один на процесс."""
    global _ctx
    with _ctx_lock:
        if _ctx is None:
            from securechannel.keys import ServerKeys
            from securechannel.pairing import PairingManager
            from securechannel.registry import DeviceRegistry
            from securechannel.server import SecureContext
            d = config.SECURE_DIR
            _ctx = SecureContext(keys=ServerKeys.load_or_create(d),
                                 registry=DeviceRegistry.open(d),
                                 pairing=PairingManager(),
                                 backend=getattr(config, "SECURE_BACKEND", "lib"))
        return _ctx


def reset_context() -> None:
    global _ctx
    with _ctx_lock:
        _ctx = None


def _local_addresses() -> frozenset[str]:
    global _local_cache
    now = time.monotonic()
    if now - _local_cache[0] < LOCAL_ADDR_TTL_S and _local_cache[1]:
        return _local_cache[1]
    addrs = set()
    try:
        import psutil
        for entries in psutil.net_if_addrs().values():
            for a in entries:
                if a.family.name in ("AF_INET", "AF_INET6"):
                    addrs.add(a.address.split("%")[0])
    except Exception as e:
        log.debug(f"[secure] адреса интерфейсов: {type(e).__name__}")
    _local_cache = (now, frozenset(addrs))
    return _local_cache[1]


def peer_ip(websocket) -> str | None:
    addr = getattr(websocket, "remote_address", None)
    if isinstance(addr, tuple) and addr:
        return str(addr[0])
    return None


def is_local_peer(ip: str | None) -> bool:
    """loopback или адрес интерфейса этого сервера (не из заголовков)."""
    if not ip:
        return False
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.is_loopback:
        return True
    if getattr(a, "ipv4_mapped", None) is not None:
        a = a.ipv4_mapped
        if a.is_loopback:
            return True
    return str(a) in _local_addresses()


def is_private(msg_type: str | None) -> bool:
    t = msg_type or ""
    return t in PRIVATE_TYPES or t.startswith(PRIVATE_PREFIXES)


def requires_secure() -> bool:
    return bool(getattr(config, "PRIVATE_REQUIRES_SECURE", True))


def secure_error(request_id=None) -> dict:
    return {"type": "error", "request_id": request_id, "code": "secure_channel_required",
            "message": "нужен защищённый канал", "hint": SECURE_HINT}
