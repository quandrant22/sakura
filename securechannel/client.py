"""Клиентская сторона securechannel/1 — эталон для desktop/core и тестов.

    conn = await connect_session(ws, device_priv, server_pub, device_id="mostech")
    await conn.send(json.dumps({"type": "register", ...}))
    reply = await conn.recv()

    info = await pair(ws, words, device_priv, expected_server_pub=qr_pub,
                      name="Ноутбук", kind="pc", device_id_hint="mostech")
    # info = {"device_id", "server_pub", "server_fp"}; дальше — connect_session
"""

from __future__ import annotations

import asyncio
import json
import time

from securechannel.channel import SecureChannel
from securechannel.frames import FrameType, InnerType, decode_frame, encode_frame
from securechannel.handshake import Handshake, HandshakeError
from securechannel.keys import unb64url
from securechannel.pairing import words_to_psk
from securechannel.server import SecureConnection

CLIENT_TIMEOUT_S = 10.0


async def _recv_frame(ws, timeout: float):
    return decode_frame(await asyncio.wait_for(ws.recv(), timeout))


async def connect_session(ws, device_priv: bytes, server_pub: bytes, *, device_id: str,
                          backend: str = "lib", timeout: float = CLIENT_TIMEOUT_S) -> SecureConnection:
    hs = Handshake.ik_initiator(device_priv, server_pub, backend=backend)
    ident = json.dumps({"v": 1, "device_id": device_id, "ts": time.time()}).encode()
    await ws.send(encode_frame(FrameType.IK_INIT, hs.write(ident)))
    ftype, body = await _recv_frame(ws, timeout)
    if ftype != FrameType.IK_RESP:
        raise HandshakeError(f"ожидался IK_RESP, пришёл {ftype.name}")
    params = json.loads(hs.read(body) or b"{}")
    send, recv = hs.split()
    ch = SecureChannel(send, recv, rekey_messages=int(params.get("rekey_messages") or 10_000),
                       rekey_seconds=float(params.get("rekey_seconds") or 3600))
    conn = SecureConnection(ws, ch, device_id)
    conn.session = params.get("session")
    return conn


async def pair(ws, words: str, device_priv: bytes, *, expected_server_pub: bytes | None = None,
               name: str = "устройство", kind: str = "pc", device_id_hint: str = "",
               backend: str = "lib", timeout: float = CLIENT_TIMEOUT_S) -> dict:
    """Спаривание по 8 словам (и ключу сервера из QR, если есть)."""
    psk = words_to_psk(words)
    hs = Handshake.xx_initiator(device_priv, psk, backend=backend)
    await ws.send(encode_frame(FrameType.XX_1, hs.write(b"")))
    ftype, body = await _recv_frame(ws, timeout)
    if ftype != FrameType.XX_2:
        raise HandshakeError(f"ожидался XX_2, пришёл {ftype.name}")
    hs.read(body)
    if expected_server_pub is not None and hs.remote_static != expected_server_pub:
        raise HandshakeError("ключ сервера не совпадает с QR — возможна подмена")
    info = json.dumps({"v": 1, "name": name, "kind": kind, "device_id_hint": device_id_hint})
    await ws.send(encode_frame(FrameType.XX_3, hs.write(info.encode())))
    send, recv = hs.split()
    ch = SecureChannel(send, recv)
    raw = await asyncio.wait_for(ws.recv(), timeout)
    events = ch.open(raw)          # не расшифровалось → PSK не совпал (IntegrityError)
    for inner, data in events:
        if inner == InnerType.PAIRED:
            paired = json.loads(data)
            server_pub = unb64url(paired["server_pub"])
            if server_pub != hs.remote_static:
                raise HandshakeError("PAIRED: ключ сервера не тот, что в рукопожатии")
            paired["server_pub_bytes"] = server_pub
            return paired
    raise HandshakeError("нет кадра PAIRED")
