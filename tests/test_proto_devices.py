"""Протокол v2, ядро и порция 2 (устройства и статус) — через настоящий ws_handler.

Контракт: формы devices / status совпадают с фикстурами мок-сервера
(tests/fixtures/proto_v2, копия из feat/desktop-rewrite) по полям и типам.

Run: python -m pytest tests/test_proto_devices.py -q
"""

import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest
import websockets

import adapters.ws as wh
import config
import modules.presence_sync as presence
import modules.state as st
import modules.tts_server as tts
import sakura_core.ws_protocol as proto
from modules import device_manager, rituals
from modules.ws_auth import _WS_SECRET, MAX_WS_MESSAGE_SIZE
from sakura_core import proto_devices as pd

FIX = Path(__file__).parent / "fixtures" / "proto_v2"
MASTER, MASTER2, GUEST = "laptop", "pc", "phone"     # conftest: MASTER_DEVICES=laptop,pc


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def assert_shape(sample, actual, where=""):
    for k, v in sample.items():
        assert k in actual, f"{where}: нет поля {k!r}"
        if v is None or actual[k] is None:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert isinstance(actual[k], (int, float)) and not isinstance(actual[k], bool), (where, k)
        else:
            assert isinstance(actual[k], type(v)), (where, k, type(actual[k]))
        if isinstance(v, dict):
            assert_shape(v, actual[k], f"{where}.{k}")


# ── стенд ──────────────────────────────────────────────────────────

@pytest.fixture
def server(monkeypatch):
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(st, "device_proto", {})
    monkeypatch.setattr(pd, "_devices", {})
    monkeypatch.setattr(pd, "_last_pushed", {})
    monkeypatch.setattr(pd, "_last_status", None)
    monkeypatch.setattr(config, "PROTO_V2", True)
    monkeypatch.setattr(device_manager, "set_device_offline", lambda d: None)
    monkeypatch.setattr(presence, "set_offline", lambda d: None)
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    monkeypatch.setattr(proto, "watcher_update", lambda *a, **k: None)
    monkeypatch.setattr(proto, "track_rec_activity", lambda *a, **k: None)
    monkeypatch.setattr(proto, "check_device_transfer", lambda *a, **k: None)
    monkeypatch.setattr(proto, "check_pc_health", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_comment_music", lambda: False)

    async def _no_game(*a, **k):
        return None
    monkeypatch.setattr(proto, "get_current_game", _no_game)
    focus = {"id": MASTER}
    monkeypatch.setattr(presence, "get_active_device", lambda: focus["id"])
    monkeypatch.setattr(tts, "TTS_TONE", "тепло")
    yield focus
    st.connected_devices.clear()
    st.connected_devices.update(saved)


class Client:
    def __init__(self, ws, device):
        self.ws, self.device, self.inbox, self._n = ws, device, [], 0

    async def send(self, msg, rid=True):
        if rid:
            self._n += 1
            msg = {"request_id": f"r{self._n}", **msg}
        await self.ws.send(json.dumps({"token": _WS_SECRET, "device_id": self.device, **msg}))
        return msg.get("request_id")

    async def wait(self, pred, timeout=3.0):
        for i, m in enumerate(self.inbox):
            if pred(m):
                return self.inbox.pop(i)
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            m = json.loads(await asyncio.wait_for(self.ws.recv(), max(0.01, end - loop.time())))
            if pred(m):
                return m
            self.inbox.append(m)

    async def request(self, msg):
        rid = await self.send(msg)
        return await self.wait(lambda m: m.get("request_id") == rid)

    async def silent(self, pred, timeout=0.3):
        try:
            await self.wait(pred, timeout)
        except asyncio.TimeoutError:
            return True
        return False


async def connect(uri, device, proto_v=2, **reg):
    ws = await websockets.connect(uri, max_size=None)
    c = Client(ws, device)
    msg = {"type": "register", **reg}
    if proto_v:
        msg["proto"] = proto_v
    await c.send(msg, rid=False)
    if proto_v:
        await c.wait(lambda m: m.get("type") == "registered")
    return c


def run(scenario):
    async def _go():
        async with websockets.serve(wh.ws_handler, "127.0.0.1", 0,
                                    max_size=MAX_WS_MESSAGE_SIZE, ping_interval=None) as srv:
            port = srv.sockets[0].getsockname()[1]
            return await asyncio.wait_for(scenario(f"ws://127.0.0.1:{port}"), 15)
    return asyncio.run(_go())


def kind(k):
    return lambda m: m.get("type") == k


# ── регистрация и ошибки ядра ──────────────────────────────────────

def test_registered_and_old_client(server):
    async def sc(uri):
        new = await connect(uri, MASTER)
        old = await connect(uri, MASTER2, proto_v=None)
        await new.send({"type": "ping", "system_info": {"cpu": 50}}, rid=False)
        return await old.silent(lambda m: True, 0.4)
    assert run(sc), "старому клиенту (без proto) ничего нового не приходит"


def test_errors_not_master_unsupported_and_disabled(server, monkeypatch):
    async def sc(uri):
        g = await connect(uri, GUEST)
        e1 = await g.request({"type": "devices_request"})
        m = await connect(uri, MASTER)
        e2 = await m.request({"type": "history_request"})       # приватное, без защиты
        return e1, e2
    e1, e2 = run(sc)
    assert (e1["type"], e1["code"]) == ("error", "not_master")
    assert (e2["type"], e2["code"]) == ("error", "secure_channel_required")

    monkeypatch.setattr(config, "PROTO_V2", False)

    async def sc2(uri):
        m = await connect(uri, MASTER, proto_v=None)
        await m.send({"type": "register", "proto": 2}, rid=False)
        e = await m.request({"type": "status_request"})
        return e, [x for x in m.inbox if x.get("type") == "registered"]
    e, regs = run(sc2)
    assert e["code"] == "unsupported" and regs == []


# ── devices ────────────────────────────────────────────────────────

def test_devices_contract_stats_focus(server):
    async def sc(uri):
        m = await connect(uri, MASTER, system_info={"cpu": 23, "ram": 61, "battery": 80,
                                                    "plugged": True, "cpu_temp": 55})
        phone = await connect(uri, "phone", proto_v=None,
                              system_info={"battery": 78, "plugged": False,
                                           "wifi": "Home", "signal": 3})
        r = await m.request({"type": "devices_request"})
        return r
    r = run(sc)
    sample = fixture("devices")["devices"]
    assert r["type"] == "devices"
    by = {d["id"]: d for d in r["devices"]}
    assert set(by) == {MASTER, "phone"}
    for d in r["devices"]:
        assert_shape(sample[0], d, f"Device {d['id']}")
    lap, ph = by[MASTER], by["phone"]
    assert lap["online"] and lap["focus"] and not ph["focus"]
    assert lap["kind"] == "pc" and ph["kind"] == "phone"
    assert lap["stats"] == {"cpu": 23, "ram": 61, "gpu": None, "battery": 80,
                            "charging": True, "wifi": None, "signal": None}
    assert ph["stats"]["wifi"] == "Home" and ph["stats"]["charging"] is False
    assert isinstance(lap["last_seen"], float)


def test_device_update_pushes_only_to_v2_masters(server):
    async def sc(uri):
        a = await connect(uri, MASTER)
        b = await connect(uri, MASTER2)
        old = await connect(uri, "laptop2", proto_v=None)        # не master и не v2
        g = await connect(uri, GUEST)                            # v2, но не master
        await a.wait(kind("device_update"))                      # свои апдейты
        for c in (a, b, g):
            c.inbox.clear()
        await b.send({"type": "ping", "system_info": {"cpu": 90, "ram": 40}}, rid=False)
        up = await a.wait(lambda m: m.get("type") == "device_update"
                          and m["device"]["id"] == MASTER2 and m["device"]["stats"].get("cpu") == 90)
        guest_silent = await g.silent(kind("device_update"))
        old_silent = await old.silent(lambda m: True)
        await b.ws.close()
        off = await a.wait(lambda m: m.get("type") == "device_update"
                           and m["device"]["id"] == MASTER2 and not m["device"]["online"])
        return up, guest_silent, old_silent, off
    up, guest_silent, old_silent, off = run(sc)
    assert_shape(fixture("devices")["devices"][0], up["device"], "device_update")
    assert guest_silent and old_silent
    assert off["device"]["online"] is False


def test_small_load_change_is_throttled(server):
    async def sc(uri):
        a = await connect(uri, MASTER, system_info={"cpu": 20})
        await a.wait(kind("device_update"))       # пуш регистрации (cpu 20)
        await a.send({"type": "ping", "system_info": {"cpu": 24}}, rid=False)
        small = await a.silent(kind("device_update"))
        await a.send({"type": "ping", "system_info": {"cpu": 70}}, rid=False)
        big = await a.wait(kind("device_update"))
        await a.send({"type": "ping", "system_info": {"cpu": 70, "battery": 40}}, rid=False)
        batt = await a.wait(kind("device_update"))
        return small, big, batt
    small, big, batt = run(sc)
    assert small, "скачок нагрузки меньше 10 — без пуша"
    assert big["device"]["stats"]["cpu"] == 70
    assert batt["device"]["stats"]["battery"] == 40


def test_focus_change_pushes(server):
    focus = server

    async def sc(uri):
        a = await connect(uri, MASTER)
        await connect(uri, MASTER2)
        await asyncio.sleep(0.1)
        a.inbox.clear()
        focus["id"] = MASTER2
        await a.send({"type": "ping"}, rid=False)
        return await a.wait(lambda m: m.get("type") == "device_update"
                            and m["device"]["id"] == MASTER and m["device"]["focus"] is False)
    assert run(sc)["device"]["online"]


# ── status ─────────────────────────────────────────────────────────

def test_status_contract_and_values(server):
    async def sc(uri):
        a = await connect(uri, MASTER, active_window="Visual Studio Code — main.py")
        r = await a.request({"type": "status_request"})
        return r
    r = run(sc)
    assert_shape(fixture("status"), r, "status")
    assert r["type"] == "status" and r["tone"] == "warm"
    assert r["mode"] == "normal" and r["context"]
    assert r["quote"] in json.loads(pd.QUOTES_FILE.read_text(encoding="utf-8"))["quotes"]


def test_status_mode_game_and_push(server, monkeypatch):
    import modules.window_watcher as ww
    monkeypatch.setattr(ww, "_classify_window", lambda w, *a: "game" if "Hades" in w else "other")

    async def sc(uri):
        a = await connect(uri, MASTER, active_window="Блокнот")
        first = await a.request({"type": "status_request"})
        a.inbox.clear()
        await a.send({"type": "ping", "active_window": "Hades II"}, rid=False)
        pushed = await a.wait(kind("status"))
        return first, pushed
    first, pushed = run(sc)
    assert first["mode"] == "normal"
    assert (pushed["mode"], pushed["context"]) == ("game", "Игра")
    assert "request_id" not in pushed, "пуш без request_id"


def test_status_away_without_masters(server):
    st.connected_devices.clear()
    s = pd.status()
    assert (s["mode"], s["context"]) == ("away", "Мастер не за компьютером")


def test_quote_of_the_day_is_stable_and_rotates():
    q1 = pd._quote(dt.date(2026, 10, 13))
    assert q1 == pd._quote(dt.date(2026, 10, 13))
    quotes = json.loads(pd.QUOTES_FILE.read_text(encoding="utf-8"))["quotes"]
    assert len(quotes) >= 20 and q1 in quotes
    assert pd._quote(dt.date(2026, 10, 14)) != q1


@pytest.mark.parametrize("ru,en", [("нейтрально", "neutral"), ("тепло", "warm"),
                                   ("сухо-иронично", "dry"), ("серьёзно", "serious"),
                                   ("тихо", "quiet"), ("бодро", "cheerful"), ("?", "neutral")])
def test_tone_ids(monkeypatch, ru, en):
    monkeypatch.setattr(tts, "TTS_TONE", ru)
    assert pd.status()["tone"] == en


def test_heartbeat_error_does_not_break_ping(server, monkeypatch):
    def _boom():
        raise RuntimeError("presence db")
    monkeypatch.setattr(presence, "get_active_device", _boom)

    async def sc(uri):
        a = await connect(uri, MASTER)
        await a.send({"type": "ping", "system_info": {"cpu": 1}}, rid=False)
        return await a.request({"type": "devices_request"})
    r = run(sc)
    assert r["type"] == "devices" and r["devices"][0]["focus"] is False
