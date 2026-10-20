"""Протокол v2, порции 3–4: память, профиль, сценарии + приватные классы и
кадры экрана только по защищённому каналу.

Run: python -m pytest tests/test_proto_rest.py -q
"""

import asyncio
import base64
import json
import logging

import pytest

import config
import modules.tts_server as tts
import sakura_core.proto_v2 as pv2
from sakura_core import computer_use, proto_profile, scenarios, vision_request

MASTER = "laptop"


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def call(kind, secure=True, **fields):
    ws = WS()
    data = {"type": kind, "request_id": "r1", "device_id": MASTER, **fields}
    orig = pv2.connection_secure
    pv2.connection_secure = lambda w: secure
    try:
        asyncio.run(pv2.handle(ws, data, {"_register_command": lambda a, d: "c1"}))
    finally:
        pv2.connection_secure = orig
    return ws.sent


def reply(kind, **fields):
    out = [m for m in call(kind, **fields) if m.get("request_id") == "r1"]
    assert out, kind
    return out[-1]


# ── память ────────────────────────────────────────────────────────

@pytest.fixture
def memory(monkeypatch):
    from memory import db
    db.set_write_gate(True)
    monkeypatch.setattr(db, "_embed", lambda *a, **k: None)
    conn = db._conn()
    conn.execute("DELETE FROM master_memory")
    for cat, text in (("preferences", "Любит лоу-фай по утрам"), ("facts", "Работает из дома по средам"),
                      ("facts", "Пьёт чай без сахара")):
        conn.execute("INSERT INTO master_memory (category, text) VALUES (?, ?)", (cat, text))
    conn.commit()
    db._cache_clear()
    return db


def test_memory_list_search_update_delete(memory, caplog):
    caplog.set_level(logging.INFO)
    r = reply("memory_list", limit=10)
    assert r["type"] == "memory_items" and r["total"] == 3
    assert r["counts"] == {"preferences": 1, "facts": 2}
    item = r["items"][0]
    assert set(item) == {"id", "category", "text", "ts"} and item["id"].startswith("m")
    assert reply("memory_list", category="facts")["total"] == 2
    found = reply("memory_search", q="чай")["items"]
    assert [i["text"] for i in found] == ["Пьёт чай без сахара"]
    up = reply("memory_update", id=found[0]["id"], text="Пьёт зелёный чай")
    assert up["items"][0]["text"] == "Пьёт зелёный чай"
    assert "зелёный" not in caplog.text, "журнал изменений без текстов"
    assert reply("memory_delete", id=found[0]["id"])["items"] == []
    assert reply("memory_list")["total"] == 2
    assert reply("memory_delete", id=found[0]["id"])["code"] == "not_found"
    assert reply("memory_update", id="m1", text="")["code"] == "bad_request"
    assert reply("memory_search", q=" ")["code"] == "bad_request"
    assert reply("memory_delete", id="x1")["code"] == "bad_request"


# ── профиль ───────────────────────────────────────────────────────

def test_profile_get_set_applies_live():
    p = reply("profile_get")["profile"]
    assert set(p) == {"name", "address_as", "quiet_hours", "voice", "tone", "notifications"}
    assert p["voice"] == tts.TTS_VOICE
    sent = call("profile_set", tone="warm", voice="Leda", quiet_hours="23:00-07:00",
                name="Хозяин", notifications={"telegram": True, "sound": False})
    r = [m for m in sent if m.get("request_id") == "r1"][0]["profile"]
    assert (r["tone"], r["voice"], r["quiet_hours"], r["name"]) == ("warm", "Leda", "23:00-07:00", "Хозяин")
    assert tts.TTS_TONE == "тепло" and tts.TTS_VOICE == "Leda", "применено на лету"
    assert proto_profile.get_quiet_hours() == ("23:00", "07:00")
    for bad in ({"tone": "loud"}, {"quiet_hours": "25:00-07:00"}, {"voice": "Лида"},
                {"name": ""}, {"notifications": {"push": True}}, {}):
        assert reply("profile_set", **bad)["code"] == "bad_request", bad


def test_profile_file_is_600_and_reapplied(tmp_path):
    import os
    import stat
    proto_profile.set_profile({"tone": "serious"})
    assert stat.S_IMODE(os.stat(config.PROFILE_PATH).st_mode) == 0o600
    tts.TTS_TONE = "нейтрально"
    proto_profile.apply_saved()
    assert tts.TTS_TONE == "серьёзно"


# ── сценарии ──────────────────────────────────────────────────────

SAFE = {"name": "Утро", "conditions": [{"type": "phrase", "value": "доброе утро сакура"}],
        "actions": [{"type": "action", "value": "music.wave"}, {"type": "pause", "value": "0"},
                    {"type": "notify", "value": "Доброе утро!"}]}
DANGER = {"name": "Отбой", "conditions": [{"type": "time", "value": "23:00-07:00"}],
          "actions": [{"type": "action", "value": "system.shutdown"}]}


def test_scenario_crud_and_validation():
    s = reply("scenario_save", scenario=SAFE)["scenario"]
    assert s["id"] and s["enabled"] and not s["builtin"]
    assert reply("scenario_get", id=s["id"])["scenario"]["name"] == "Утро"
    assert [x["id"] for x in reply("scenarios_list")["scenarios"]] == [s["id"]]
    edited = reply("scenario_save", scenario={**SAFE, "id": s["id"], "name": "Утро 2"})["scenario"]
    assert edited["name"] == "Утро 2" and len(reply("scenarios_list")["scenarios"]) == 1
    for bad in ({"name": "", "actions": SAFE["actions"]},
                {"name": "x", "actions": []},
                {"name": "x", "actions": [{"type": "action", "value": "нет.такого"}]},
                {"name": "x", "actions": [{"type": "pause", "value": "999"}]},
                {"name": "x", "actions": [{"type": "action", "value": "music.wave"}] * 21},
                {"name": "x", "conditions": [{"type": "time", "value": "утром"}],
                 "actions": SAFE["actions"]}):
        assert reply("scenario_save", scenario=bad)["code"] == "bad_request", bad
    assert reply("scenario_delete", id=s["id"])["scenarios"] == []
    assert reply("scenario_get", id=s["id"])["code"] == "not_found"


def test_scenario_run_events_and_confirm(monkeypatch):
    sent_cmds = []

    class Dev:
        async def send(self, raw):
            sent_cmds.append(json.loads(raw))
    import modules.state as st
    monkeypatch.setitem(st.connected_devices, MASTER, Dev())
    from sakura_core import voice_turns
    monkeypatch.setattr(voice_turns, "broadcast_reply", lambda *a, **k: asyncio.sleep(0))
    safe = scenarios.save(SAFE)
    danger = scenarios.save(DANGER)

    async def go(sid, **kw):
        ws = WS()
        await pv2.handle(ws, {"type": "scenario_run", "request_id": "r1", "device_id": MASTER,
                              "id": sid, **kw}, {"_register_command": lambda a, d: "c1"})
        for _ in range(50):
            if any(e.get("status") == "done" for e in ws.sent):
                break
            await asyncio.sleep(0.02)
        return ws.sent
    orig = pv2.connection_secure
    pv2.connection_secure = lambda w: True
    try:
        ev = asyncio.run(go(safe["id"]))
        refused = asyncio.run(go(danger["id"]))
        sent_cmds.clear()
        confirmed = asyncio.run(go(danger["id"], confirm=True))
    finally:
        pv2.connection_secure = orig
    assert ev[0]["type"] == "scenario_run_started" and ev[0]["request_id"] == "r1"
    steps = [(e["step"], e["status"]) for e in ev if e["type"] == "scenario_event"]
    assert steps == [(0, "ok"), (1, "ok"), (2, "ok"), (3, "done")]
    assert refused[-1]["code"] == "confirm_required" and "system.shutdown" in refused[-1]["message"]
    assert any(c.get("type") == "command" for c in sent_cmds), "после confirm — команда агенту"
    assert [e["status"] for e in confirmed if e["type"] == "scenario_event"][-1] == "done"


def test_scenario_stops_on_error(monkeypatch):
    from sakura_core import bridge

    class Ex:
        async def execute(self, action, ctx, param=None):
            raise RuntimeError("агент недоступен")
    monkeypatch.setattr(bridge, "get_executor", lambda: Ex())
    s = scenarios.save({"name": "x", "actions": [{"type": "action", "value": "music.wave"},
                                                 {"type": "notify", "value": "не дойдёт"}]})
    events = []

    async def emit(e):
        events.append(e)
    asyncio.run(scenarios.run(s, emit=emit, device_ws=None, device_id=MASTER, register_command=None))
    assert [(e["step"], e["status"]) for e in events] == [(0, "error"), (1, "done")]
    assert "остановлено" in events[-1]["detail"]


def test_scenario_phrase_and_from_text():
    s = scenarios.save(SAFE)
    assert scenarios.match_phrase("Доброе утро, Сакура!")["id"] == s["id"]
    assert scenarios.match_phrase("доброе утро") is None
    scenarios.save({**SAFE, "id": s["id"], "enabled": False})
    assert scenarios.match_phrase("доброе утро сакура") is None
    prev = reply("scenario_from_text", text="включи мою волну, подожди 5 и сделай скриншот, и что-то непонятное")
    assert prev["type"] == "scenario_preview"
    acts = prev["scenario"]["actions"]
    assert {"type": "pause", "value": "5"} in acts
    assert any(a["type"] == "action" for a in acts)
    assert any("не понято" in w for w in prev["warnings"])
    assert reply("scenario_from_text", text="")["code"] == "bad_request"


def test_builtin_cannot_be_deleted():
    s = scenarios.save({**SAFE, "id": "focus", "builtin": True})
    with pytest.raises(scenarios.ScenarioError):
        scenarios.delete(s["id"])


# ── приватные классы и кадры экрана без защиты ────────────────────

@pytest.mark.parametrize("kind", ["memory_list", "profile_get", "history_request", "chat_send"])
def test_private_kinds_denied_without_secure(kind):
    r = [m for m in call(kind, secure=False) if m.get("request_id") == "r1"][-1]
    assert r["code"] == "secure_channel_required" and r["hint"]


def test_non_private_kinds_work_without_secure():
    assert reply("scenarios_list", secure=False)["type"] == "scenarios"


def test_privacy_gate_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "PRIVATE_REQUIRES_SECURE", False)
    assert reply("profile_get", secure=False)["type"] == "profile"


def test_connection_secure_without_policy_module_is_false():
    class Plain:
        remote_address = ("127.0.0.1", 1)
    try:
        import sakura_core.secure_policy  # noqa: F401
        pytest.skip("модуль политики есть (ветка securechannel) — проверяется там")
    except ImportError:
        assert pv2.connection_secure(Plain()) is False
    class Noise:
        secure = True
    assert pv2.connection_secure(Noise()) is True


def test_vision_and_computer_step_need_secure(monkeypatch):
    monkeypatch.setattr(pv2, "connection_secure", lambda ws: False)
    ws = WS()
    img = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 10).decode()
    asyncio.run(vision_request.handle(ws, {"request_id": "v", "device_id": MASTER, "image": img}))
    assert ws.sent[-1]["code"] == "secure_channel_required"
    monkeypatch.setattr(config, "COMPUTER_USE", True)
    asyncio.run(computer_use.handle(ws, {"request_id": "c", "device_id": MASTER, "goal": "x",
                                         "history": [], "screenshot": img}))
    assert ws.sent[-1]["code"] == "secure_channel_required"


def test_computer_step_off_by_default():
    ws = WS()
    asyncio.run(computer_use.handle(ws, {"request_id": "c", "device_id": MASTER}))
    assert ws.sent[-1]["code"] == "unsupported"
