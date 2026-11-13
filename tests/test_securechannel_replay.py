"""securechannel: анти-повтор IK_INIT (закрытие ProVerif ik Q7, securechannel/replay.py).

Модульно: кэш эфемерных ключей (дубликат, TTL, ограничение размера) и окно ts.
Интеграционно (настоящий websockets-сервер): записанный легитимный IK_INIT,
пересланный повторно, получает молчаливый отказ 4408 в дедлайн; устаревший ts —
тоже; свежие подключения того же устройства продолжают работать.
Run: python -m pytest tests/test_securechannel_replay.py -q
"""

import json
import time

import pytest
import websockets

from securechannel.client import connect_session
from securechannel.frames import FrameType, encode_frame
from securechannel.handshake import Handshake, generate_keypair
from securechannel.keys import ServerKeys
from securechannel.limits import HandshakeLimiter
from securechannel.pairing import PairingManager
from securechannel.registry import DeviceRegistry
from securechannel.replay import (
    E_LEN,
    TS_WINDOW_S,
    TTL_S,
    ReplayCache,
    ephemeral_of,
    ts_is_fresh,
)
from securechannel.server import SecureContext
from tests.test_securechannel_server import TIMEOUT, closed_with, do_pair, serve


@pytest.fixture
def ctx(tmp_path):
    d = str(tmp_path / "secure")
    return SecureContext(ServerKeys.load_or_create(d), DeviceRegistry.open(d), PairingManager(),
                         limiter=HandshakeLimiter(), timeout=TIMEOUT)

pytest.importorskip("noise")


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ── модульно ──────────────────────────────────────────────────────

def test_cache_rejects_duplicate_and_expires_after_ttl():
    clk = FakeClock()
    c = ReplayCache(ttl=10.0, clock=clk)
    e = b"\x01" * E_LEN
    assert c.check_and_add(e) is True
    assert c.check_and_add(e) is False          # повтор в пределах TTL
    clk.t += 9.9
    assert c.check_and_add(e) is False
    clk.t += 0.2                                 # TTL истёк
    assert c.check_and_add(e) is True


def test_cache_is_bounded_and_evicts_oldest():
    clk = FakeClock()
    c = ReplayCache(ttl=100.0, max_entries=3, clock=clk)
    keys = [bytes([i]) * E_LEN for i in range(5)]
    for k in keys:
        assert c.check_and_add(k)
        clk.t += 1
    assert len(c) == 3
    assert c.check_and_add(keys[-1]) is False   # свежие остались
    assert c.check_and_add(keys[0]) is True     # самый старый вытеснен


def test_ts_window_and_ttl_relation():
    now = 1_000_000.0
    assert ts_is_fresh(now, now=now)
    assert ts_is_fresh(now - TS_WINDOW_S, now=now)
    assert not ts_is_fresh(now - TS_WINDOW_S - 1, now=now)
    assert not ts_is_fresh(now + TS_WINDOW_S + 1, now=now)
    assert not ts_is_fresh(None, now=now) and not ts_is_fresh("1", now=now)
    assert not ts_is_fresh(True, now=now)
    assert ts_is_fresh(None, now=now, window=0)          # проверка выключена
    # TTL покрывает весь интервал, в котором сообщение проходит окно свежести.
    assert TTL_S >= 2 * TS_WINDOW_S


def test_ephemeral_is_the_cleartext_prefix_of_ik_init(ctx):
    m1 = Handshake.ik_initiator(generate_keypair()[0], ctx.keys.current[1]).write(b"{}")
    assert ephemeral_of(m1) == m1[:E_LEN] and len(ephemeral_of(m1)) == 32
    assert ephemeral_of(b"short") is None


# ── интеграционно ─────────────────────────────────────────────────

def test_replayed_ik_init_is_silently_rejected_fresh_sessions_work(ctx):
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        server_pub = info["server_pub_bytes"]
        # Легитимное сообщение 1, «записанное» атакующим.
        ident = json.dumps({"v": 1, "device_id": info["device_id"], "ts": time.time()}).encode()
        m1 = Handshake.ik_initiator(priv, server_pub).write(ident)
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(encode_frame(FrameType.IK_INIT, m1))
            first = await ws.recv()                    # оригинал принят: пришёл IK_RESP
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(encode_frame(FrameType.IK_INIT, m1))   # ПОВТОР
            replay = await closed_with(ws)
        async with websockets.connect(uri, max_size=None) as ws:  # честный клиент: новый e
            c = await connect_session(ws, priv, server_pub, device_id=info["device_id"])
            await c.send(json.dumps({"ping": 1}))
            echo = json.loads(await c.recv())
        return first, replay, echo
    first, (code, waited, got), echo = serve(ctx, sc)
    assert isinstance(first, (bytes, bytearray)) and first[:2] == b"SK"
    assert code == 4408 and got == [] and waited >= TIMEOUT - 0.08   # как любой другой отказ
    assert echo["echo"] == {"ping": 1}


def test_stale_ts_is_rejected(ctx):
    async def sc(uri):
        priv, info = await do_pair(uri, ctx)
        old = time.time() - TS_WINDOW_S - 60
        ident = json.dumps({"v": 1, "device_id": info["device_id"], "ts": old}).encode()
        m1 = Handshake.ik_initiator(priv, info["server_pub_bytes"]).write(ident)
        async with websockets.connect(uri, max_size=None) as ws:
            await ws.send(encode_frame(FrameType.IK_INIT, m1))
            return await closed_with(ws)
    code, _, got = serve(ctx, sc)
    assert code == 4408 and got == []
