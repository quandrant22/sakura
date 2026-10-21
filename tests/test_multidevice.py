"""Несколько ПК: одно активное устройство, треки по устройствам,
secure_devices, presence вместо mood_update, KNOWN_DEVICES из DEVICES.

Run: python -m pytest tests/test_multidevice.py -q
"""

import asyncio
import json

import pytest

import config
import modules.mood_broadcast as mood_broadcast
import modules.state as st
import sakura_core.proto_v2 as pv2
from modules import device_manager, presence_sync as ps
from sakura_core import proto_devices, secure_policy

PCS = ("pc", "laptop", "mostech")


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(ps, "_now", lambda: t["now"])
    monkeypatch.setattr(st, "device_tracks", {})
    ps.reset()
    yield t
    ps.reset()


def ping(dev, idle=None, **extra):
    data = {"type": "ping", "active_window": "x", **extra}
    if idle is not None:
        data["input_idle_s"] = idle
    ps.update(dev, data)


# ── активное устройство ───────────────────────────────────────────

def test_pings_without_input_do_not_move_active(clock):
    """Три ПК шлют ping каждые 5 с, ввода ни на одном нет: активное одно и то же,
    порядок пингов не важен."""
    ping("laptop", idle=1)                  # последний ввод был на ноуте
    assert ps.get_active_device() == "laptop"
    start = clock["now"]
    seen = set()
    for i in range(60):
        clock["now"] += 5
        order = PCS[i % 3:] + PCS[:i % 3]   # пингуют по кругу, каждый первым
        for d in order:
            ping(d, idle=1 + clock["now"] - start + (0 if d == "laptop" else 50))
            seen.add(ps.get_active_device())
    assert seen == {"laptop"}


def test_input_on_other_pc_switches(clock):
    ping("pc", idle=1)
    ping("laptop", idle=200)
    assert ps.get_active_device() == "pc"
    clock["now"] += 40                      # pc молчит 41 с
    ping("pc", idle=41)
    ping("laptop", idle=3)                  # на ноуте только что ввод
    assert ps.get_active_device() == "laptop"


def test_switch_thresholds(clock):
    ping("pc", idle=10)
    ping("laptop", idle=4)                  # на pc всего 10 с — рано
    assert ps.get_active_device() == "pc"
    clock["now"] += 25
    ping("pc", idle=35)
    ping("laptop", idle=6)                  # на новом >5 с — мало
    assert ps.get_active_device() == "pc"
    ping("laptop", idle=5)
    assert ps.get_active_device() == "laptop"


def test_voice_or_text_switches_immediately(clock):
    ping("pc", idle=0)
    ps.note_input("mostech")
    assert ps.get_active_device() == "mostech"
    ping("pc", idle=0)                      # ввод на pc — но на mostech ввод только что был
    assert ps.get_active_device() == "mostech"


def test_legacy_without_input_idle(clock):
    ping("pc")
    ping("laptop")
    first = ps.get_active_device()
    assert first in ("pc", "laptop")
    for _ in range(10):                     # пинги без input_idle_s не двигают активное
        clock["now"] += 5
        ping("pc"); ping("laptop"); ping("mostech")
    assert ps.get_active_device() == first


def test_offline_active_falls_back(clock):
    ping("pc", idle=1)
    ping("laptop", idle=60)
    ps.set_offline("pc")
    assert ps.get_active_device() == "laptop"


# ── треки ─────────────────────────────────────────────────────────

def track(artist, title, status="играет", **kw):
    return {"artist": artist, "title": title, "status": status, **kw}


def test_tracks_are_per_device_and_replaced_whole(clock):
    st.set_device_track("pc", track("A", "one", album="alb"), now=clock["now"])
    st.set_device_track("laptop", track("B", "two"), now=clock["now"])
    assert st.device_track("pc", clock["now"])["title"] == "one"
    assert st.device_track("laptop", clock["now"])["title"] == "two"
    st.set_device_track("pc", track("C", "three"), now=clock["now"])
    assert "album" not in st.device_track("pc", clock["now"])


def test_prompt_track_active_then_freshest_playing(clock):
    n = clock["now"]
    st.set_device_track("pc", track("A", "pc-song"), now=n - 30)
    st.set_device_track("laptop", track("B", "laptop-song"), now=n - 10)
    assert st.prompt_track("pc", n)["title"] == "pc-song"          # активный играет
    st.set_device_track("pc", track("A", "pc-song", status="пауза"), now=n - 5)
    assert st.prompt_track("pc", n)["title"] == "laptop-song"      # у активного тишина
    st.set_device_track("mostech", track("C", "old"), now=n - 90)
    assert st.prompt_track("pc", n)["title"] == "laptop-song"      # старше 60 с не берём
    assert st.prompt_track("pc", n + 100) == {}                    # всё протухло
    st.set_device_track("pc", track("A", "pc-song", status="пауза"), now=n + 99)
    assert st.prompt_track("pc", n + 100)["status"] == "пауза"


def test_update_current_track_by_device(clock):
    from sakura_core.ws_protocol import update_current_track
    update_current_track({"device_id": "pc", "current_track": track("A", "one")})
    update_current_track({"device_id": "laptop", "current_track": track("B", "two")})
    assert st.device_tracks["pc"]["track"]["title"] == "one"
    assert st.device_tracks["laptop"]["track"]["title"] == "two"


# ── secure_devices ────────────────────────────────────────────────

class WS:
    def __init__(self, transport=None):
        self.sent, self.transport = [], transport

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def ask(secure, monkeypatch, device="laptop", flag=True):
    monkeypatch.setattr(pv2, "connection_secure", lambda w: secure)
    monkeypatch.setattr(config, "PRIVATE_REQUIRES_SECURE", flag)
    ws = WS()
    asyncio.run(pv2.handle(ws, {"type": "secure_devices", "request_id": "r1",
                                "device_id": device}, {}))
    return ws.sent[-1]


def test_secure_devices_refused_without_secure_channel(monkeypatch):
    r = ask(False, monkeypatch)
    assert (r["type"], r["code"]) == ("error", "secure_channel_required")
    # даже с PRIVATE_REQUIRES_SECURE=0 это закрыто
    r = ask(False, monkeypatch, flag=False)
    assert r["code"] == "secure_channel_required"


def test_secure_devices_master_only(monkeypatch):
    assert ask(True, monkeypatch, device="phone")["code"] == "not_master"


def test_secure_devices_list_has_no_secrets(monkeypatch):
    monkeypatch.setattr(config, "SECURE_CHANNEL", "optional")
    reg = secure_policy.context().registry
    d1 = reg.add(b"\x01" * 32, name="Ноутбук", id_hint="laptop")
    reg.add(b"\x02" * 32, name="Рабочий", id_hint="mostech")
    reg.revoke("mostech")
    monkeypatch.setitem(st.connected_devices, "laptop", WS(transport="noise"))
    r = ask(True, monkeypatch)
    assert r["type"] == "secure_devices"
    by = {d["device_id"]: d for d in r["devices"]}
    assert set(by["laptop"]) == {"device_id", "name", "fingerprint", "paired_at", "last_seen",
                                 "online", "secure_now", "revoked", "current"}
    assert by["laptop"]["current"] and by["laptop"]["online"] and by["laptop"]["secure_now"]
    assert len(by["laptop"]["fingerprint"]) == 16
    assert by["mostech"]["revoked"] and not by["mostech"]["online"] and not by["mostech"]["current"]
    blob = json.dumps(r)
    assert d1["pub"] not in blob and "psk" not in blob.lower() and "pub" not in blob


# ── presence вместо mood_update ───────────────────────────────────

def test_proto2_gets_presence_proto1_gets_flag_only(monkeypatch):
    v2, v1 = WS(), WS()
    monkeypatch.setattr(st, "device_proto", {"pc": 2})
    devs = {"pc": v2, "laptop": v1}
    asyncio.run(ps.broadcast_transfer({"from": "laptop", "to": "pc"}, devs, {"valence": 0.5}))
    assert v2.sent == [{"type": "presence", "event": "arrival", "from": "laptop", "to": "pc"}]
    assert v1.sent == [{"type": "mood_update", "params": {"is_departure": True}}]
    assert not any(m["type"] == "mood_update" for m in v2.sent)
    v2.sent.clear(); v1.sent.clear()
    asyncio.run(ps.broadcast_transfer({"from": "pc", "to": "laptop"}, devs))
    assert v2.sent == [{"type": "presence", "event": "departure", "from": "pc", "to": "laptop"}]
    assert v1.sent == [{"type": "mood_update", "params": {"is_arrival": True}}]


def test_transfer_reported_once(clock):
    ping("pc", idle=0)
    devs = {"pc": object(), "laptop": object()}
    assert ps.check_device_transfer(devs) == {"from": "", "to": "pc"}
    assert ps.check_device_transfer(devs) is None
    ps.note_input("laptop")
    assert ps.check_device_transfer(devs) == {"from": "pc", "to": "laptop"}


def test_mood_broadcast_off_by_default(monkeypatch):
    assert config.MOOD_BROADCAST is False
    ws = WS()
    asyncio.run(mood_broadcast.broadcast_mood({"pc": ws}))
    assert ws.sent == []
    monkeypatch.setattr(config, "MOOD_BROADCAST", True)
    asyncio.run(mood_broadcast.broadcast_mood({"pc": ws}))
    assert ws.sent and ws.sent[0]["type"] == "mood_update"


# ── KNOWN_DEVICES ─────────────────────────────────────────────────

def test_known_devices_from_config(monkeypatch):
    assert list(device_manager.KNOWN_DEVICES) == ["pc", "laptop", "mostech", "phone"]
    k = device_manager.build_known_devices(["pc", "tablet"])
    assert list(k) == ["pc", "tablet"] and k["tablet"]["name"] == "tablet"


def test_unknown_device_id_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(device_manager, "DEVICES_FILE", str(tmp_path / "d.json"))
    device_manager.update_device("mystery", active_window="w")
    device_manager.update_device("mostech", active_window="w")
    assert device_manager.device_name("mystery") == "mystery"
    assert "mystery" in device_manager.get_device_status()
    assert "Рабочий ноутбук" in device_manager.get_device_status()
    monkeypatch.setattr(ps, "get_active_device", lambda: "mystery")
    assert "mystery" in device_manager.get_device_context()
    assert proto_devices._name("mystery") == "mystery"


def test_phone_never_becomes_active(clock):
    ping("phone")
    assert ps.get_active_device() is None
    ping("pc", idle=100)
    ping("phone", idle=0)
    assert ps.get_active_device() == "pc"
    ps.note_input("phone")                  # голос/текст с телефона активным ПК не делает
    assert ps.get_active_device() == "pc"
