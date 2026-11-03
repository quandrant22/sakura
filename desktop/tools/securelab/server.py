"""Учебный сервер securechannel/1 для тестов и стенда атак (не продукт; сервер Сакуры — securechannel/ на VPS).

Режимы off | optional | required (PROTOCOL.md §1), сеанс IK, спаривание XXpsk3 с PSK из 8 слов, реестр
устройств в памяти, единое поведение при любой ошибке рукопожатия (молчание до дедлайна, затем 4408),
лимиты рукопожатий с одного адреса, эхо сообщений приложения (ответ «echo» с тем же request_id).
python -m desktop.tools.securelab.server --port 8799 --mode optional
"""
import argparse
import asyncio
import collections
import json
import time

import websockets

from desktop.core.securechannel.channel import IntegrityError, SecureChannel
from desktop.core.securechannel.frames import FrameError, FrameType, InnerType, decode_frame, encode_frame, encode_inner
from desktop.core.securechannel.keys import fingerprint
from desktop.core.securechannel.noise import HandshakeState, NoiseError, generate_keypair
from desktop.core.securechannel.pairing import b64u, words_to_psk

PRO_IK = b"sakura-securechannel/1\x00session"
PRO_XX = b"sakura-securechannel/1\x00pair"


class LabServer:
    def __init__(self, mode="optional", token="lab-token", deadline=5.0, per_ip_minute=30, per_ip_parallel=4,
                 rekey_messages=10000, rekey_seconds=3600):
        self.mode = mode
        self.token = token
        self.deadline = deadline
        self.priv, self.pub = generate_keypair()
        self.devices: dict[bytes, dict] = {}
        self.psk: bytes | None = None
        self.pair_attempts = 0
        self.per_ip_minute, self.per_ip_parallel = per_ip_minute, per_ip_parallel
        self.rekey_messages, self.rekey_seconds = rekey_messages, rekey_seconds
        self._recent = collections.defaultdict(collections.deque)
        self._parallel = collections.Counter()
        self.log: list[dict] = []  # журнал без ключей и текстов

    def start_pairing(self, words: str) -> None:
        self.psk = words_to_psk(words)
        self.pair_attempts = 0

    def add_device(self, pub: bytes, device_id: str) -> None:
        self.devices[pub] = {"id": device_id, "revoked": None}

    def revoke(self, device_id: str) -> None:
        for d in self.devices.values():
            if d["id"] == device_id:
                d["revoked"] = time.time()

    def _limit(self, ip: str) -> bool:
        now = time.monotonic()
        q = self._recent[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_ip_minute or self._parallel[ip] >= self.per_ip_parallel:
            return False
        q.append(now)
        return True

    async def handler(self, ws):
        ip = (ws.remote_address or ("?",))[0]
        try:
            first = await ws.recv()
        except websockets.ConnectionClosed:
            return
        if isinstance(first, str):
            if self.mode == "required":
                self.log.append({"transport": "ws", "result": 4412})
                await ws.close(4412, "secure_required")
                return
            await self._plain(ws, first)
            return
        if self.mode == "off":
            await ws.close(4400, "noise disabled")
            return
        if not self._limit(ip):
            self.log.append({"transport": "noise", "result": 4429})
            await ws.close(4429, "rate_limited")
            return
        self._parallel[ip] += 1
        t0 = time.monotonic()
        try:
            conn = await self._handshake(ws, first)
        except (NoiseError, FrameError, ValueError, KeyError, IndexError, asyncio.TimeoutError,
                websockets.ConnectionClosed):
            conn = None
        finally:
            self._parallel[ip] -= 1
        if conn is None:
            # любая ошибка рукопожатия: молчание до дедлайна, затем 4408 — пути неразличимы по времени
            await asyncio.sleep(max(0.0, self.deadline - (time.monotonic() - t0)))
            self.log.append({"transport": "noise", "result": 4408})
            try:
                await ws.close(4408, "handshake_failed")
            except websockets.ConnectionClosed:
                pass
            return
        if conn == "paired":
            return
        await self._serve_secure(ws, *conn)

    async def _handshake(self, ws, first: bytes):
        ftype, body = decode_frame(first)
        if ftype == FrameType.IK_INIT:
            hs = HandshakeState("IK", False, PRO_IK, s_priv=self.priv)
            ident = json.loads(hs.read(body))
            dev = self.devices.get(hs.remote_static)
            if dev is None or dev["revoked"]:
                raise ValueError("unknown device")
            resp = {"v": 1, "session": "%016x" % (int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF),
                    "rekey_messages": self.rekey_messages, "rekey_seconds": self.rekey_seconds,
                    "server_time": time.time()}
            await ws.send(encode_frame(FrameType.IK_RESP, hs.write(json.dumps(resp).encode())))
            send, recv = hs.split()
            self.log.append({"transport": "noise", "secure": True, "device_id": dev["id"],
                             "fp": fingerprint(hs.remote_static), "result": "ok", "ts_client": bool(ident.get("ts"))})
            return SecureChannel(send, recv, self.rekey_messages, self.rekey_seconds), dev["id"]
        if ftype == FrameType.XX_1:
            if self.psk is None or self.pair_attempts >= 5:
                raise ValueError("no pairing")
            self.pair_attempts += 1
            hs = HandshakeState("XXpsk3", False, PRO_XX, s_priv=self.priv, psk=self.psk)
            hs.read(body)
            await ws.send(encode_frame(FrameType.XX_2, hs.write(b"")))
            ftype, body = decode_frame(await asyncio.wait_for(ws.recv(), self.deadline))
            if ftype != FrameType.XX_3:
                raise ValueError("order")
            info = json.loads(hs.read(body))
            device_id = info.get("device_id_hint") or f"dev{len(self.devices) + 1}"
            self.add_device(hs.remote_static, device_id)
            self.psk = None
            send, recv = hs.split()
            ch = SecureChannel(send, recv)
            paired = {"device_id": device_id, "server_pub": b64u(self.pub), "server_fp": fingerprint(self.pub)}
            await ws.send(ch._seal_inner(encode_inner(InnerType.PAIRED, 0, json.dumps(paired).encode())))
            self.log.append({"transport": "noise", "pairing": True, "device_id": device_id, "result": "paired"})
            await ws.close(1000, "paired")
            return "paired"
        raise ValueError("bad first frame")

    async def _serve_secure(self, ws, ch: SecureChannel, device_id: str):
        try:
            async for data in ws:
                if isinstance(data, str):
                    await ws.close(4400, "text in secure")
                    return
                try:
                    items = ch.open(data)
                except (IntegrityError, FrameError):
                    self.log.append({"transport": "noise", "result": 4409})
                    await ws.close(4409, "integrity")
                    return
                for inner, payload in items:
                    if inner == InnerType.DATA:
                        msg = json.loads(payload)
                        reply = {"type": "echo", "request_id": msg.get("request_id"), "device_id": device_id,
                                 "secure": True, "size": len(payload)}
                        for frame in ch.seal(json.dumps(reply)):
                            await ws.send(frame)
                    elif inner == InnerType.PING:
                        await ws.send(ch._seal_inner(encode_inner(InnerType.PONG, 0, payload)))
        except websockets.ConnectionClosed:
            pass

    async def _plain(self, ws, first: str):
        msgs = [first]
        try:
            while True:
                for raw in msgs:
                    msg = json.loads(raw)
                    if msg.get("token") != self.token:
                        await ws.close(4401, "unauthorized")
                        return
                    if str(msg.get("type", "")).startswith(("chat_", "history_", "memory_", "profile_")):
                        await ws.send(json.dumps({"type": "error", "request_id": msg.get("request_id"),
                                                  "code": "secure_channel_required"}))
                    else:
                        await ws.send(json.dumps({"type": "echo", "request_id": msg.get("request_id"),
                                                  "secure": False}))
                msgs = [await ws.recv()]
        except websockets.ConnectionClosed:
            pass

    async def serve(self, host="127.0.0.1", port=0):
        return await websockets.serve(self.handler, host, port, max_size=None)


async def _main(port: int, mode: str):
    srv = LabServer(mode=mode)
    server = await srv.serve(port=port)
    print(f"securelab: ws://127.0.0.1:{port} mode={mode} server_fp={fingerprint(srv.pub)}")
    await server.wait_closed()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--mode", default="optional", choices=["off", "optional", "required"])
    a = ap.parse_args()
    asyncio.run(_main(a.port, a.mode))
