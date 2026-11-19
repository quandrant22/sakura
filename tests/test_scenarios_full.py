"""Сценарии: каталог для конструктора, проверка, сборка из фразы, голосовая
команда и автозапуск (время, устройства, приложения).

Run: python -m pytest tests/test_scenarios_full.py -q
"""

import asyncio
import datetime as dt
import json
import time

import pytest

import modules.state as st
import sakura_core.proto_v2 as pv2
from sakura_core import scenario_triggers as trig
from sakura_core import scenarios

MASTER = "laptop"


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def reply(kind, **fields):
    ws = WS()
    orig = pv2.connection_secure
    pv2.connection_secure = lambda w: True
    try:
        asyncio.run(pv2.handle(ws, {"type": kind, "request_id": "r1", "device_id": MASTER, **fields},
                               {"_register_command": lambda a, d: "c1"}))
    finally:
        pv2.connection_secure = orig
    return [m for m in ws.sent if m.get("request_id") == "r1"][-1]


NOTIFY = [{"type": "notify", "value": "Привет"}]


# ── каталог и проверка ────────────────────────────────────────────

def test_catalog_lists_registry_commands_with_params_and_danger():
    cat = reply("scenario_catalog")
    assert cat["type"] == "scenario_catalog"
    by_id = {a["id"]: a for a in cat["actions"]}
    assert by_id["music.play_track"]["param"]["required"] is True
    assert by_id["music.play_track"]["group"] == "Музыка"
    assert by_id["music.wave"]["param"] is None and by_id["music.wave"]["title"]
    assert by_id["system.shutdown"]["confirm"] is True
    assert all(a["title"] and a["group"] for a in cat["actions"])
    groups = [a["group"] for a in cat["actions"]]
    assert groups.index("Музыка") < groups.index("Код"), "популярные группы — выше"


def test_validation_param_time_days_and_messages():
    with pytest.raises(scenarios.ScenarioError) as e:
        scenarios.save({"name": "x", "actions": [{"type": "action", "value": "music.play_track"}]})
    assert "Действие 1" in e.value.message
    s = scenarios.save({"name": "Трек", "conditions": [{"type": "time", "value": "7:05 – 08:00", "days": [4, 0, 0]}],
                        "actions": [{"type": "action", "value": "music.play_track", "arg": " Кино "}]})
    assert s["conditions"] == [{"type": "time", "value": "07:05-08:00", "days": [0, 4]}]
    assert s["actions"] == [{"type": "action", "value": "music.play_track", "arg": "Кино"}]
    # старый формат «id:параметр» понимается
    old = scenarios.save({"name": "Старый", "actions": [{"type": "action", "value": "music.play_track:Кино"}]})
    assert old["actions"][0] == {"type": "action", "value": "music.play_track", "arg": "Кино"}
    every = scenarios.save({"name": "Все дни", "conditions": [{"type": "time", "value": "08:00",
                                                                "days": [0, 1, 2, 3, 4, 5, 6]}], "actions": NOTIFY})
    assert "days" not in every["conditions"][0], "все семь дней = каждый день"
    for bad in ({"type": "time", "value": "25:00"}, {"type": "time", "value": "08:00", "days": [7]},
                {"type": "app_started", "value": "  "}, {"type": "phrase", "value": "!!"}):
        with pytest.raises(scenarios.ScenarioError):
            scenarios.save({"name": "x", "conditions": [bad], "actions": NOTIFY})


def test_save_returns_warnings_toggle_and_stats_survive_edit():
    r = reply("scenario_save", scenario={"name": "Кнопка", "actions": NOTIFY})
    assert any("Условий нет" in w for w in r["warnings"])
    sid = r["scenario"]["id"]
    danger = reply("scenario_save", scenario={"name": "Отбой", "conditions": [{"type": "time", "value": "23:00"}],
                                              "actions": [{"type": "action", "value": "system.shutdown"}]})
    assert any("опасные" in w for w in danger["warnings"])
    scenarios.note_run(sid, "ok")
    off = reply("scenario_toggle", id=sid, enabled=False)
    assert off["scenario"]["enabled"] is False
    edited = reply("scenario_save", scenario={"id": sid, "name": "Кнопка 2", "enabled": False, "actions": NOTIFY,
                                              "run_count": 999, "last_status": "подделка"})["scenario"]
    assert edited["run_count"] == 1 and edited["last_status"] == "ok", "статистику клиент не перезаписывает"
    assert reply("scenario_toggle", id="нет")["code"] == "not_found"


def test_voice_command_finds_scenario_by_name():
    s = scenarios.save({"name": "Вечер дома", "actions": NOTIFY})
    assert scenarios.match_command("Запусти сценарий вечер дома")[1]["id"] == s["id"]
    assert scenarios.match_command("сакура, выполни сценарий вечер")[1]["id"] == s["id"]
    assert scenarios.match_command("запусти сценарий космос") == (True, None)
    assert scenarios.match_command("включи музыку") == (False, None)


def test_run_records_result_and_refuses_second_run(monkeypatch):
    from sakura_core import voice_turns
    monkeypatch.setattr(voice_turns, "broadcast_reply", lambda *a, **k: asyncio.sleep(0))
    s = scenarios.save({"name": "Раз", "actions": NOTIFY})
    events = []

    async def emit(e):
        events.append(e)
    asyncio.run(scenarios.run(s, emit=emit, device_ws=None, device_id=MASTER, register_command=None))
    saved = scenarios.get(s["id"])
    assert saved["last_status"] == "ok" and saved["run_count"] == 1 and s["id"] not in scenarios.running
    assert events[0]["detail"] == "уведомление" and events[-1]["status"] == "done"
    scenarios.running.add(s["id"])
    try:
        assert reply("scenario_run", id=s["id"])["code"] == "busy"
    finally:
        scenarios.running.discard(s["id"])


# ── из фразы ──────────────────────────────────────────────────────

def test_from_text_finds_time_days_and_actions():
    sc, warn = scenarios.from_text("Создай сценарий: по будням в 7:30 включи мою волну, подожди 5 "
                                   "и напиши мне в телеграм доброе утро")
    assert sc["conditions"] == [{"type": "time", "value": "07:30", "days": [0, 1, 2, 3, 4]}]
    types = [a["type"] for a in sc["actions"]]
    assert types == ["action", "pause", "telegram"], (sc, warn)
    assert sc["actions"][2]["value"] == "доброе утро"
    assert sc["name"].startswith("По будням")
    scenarios.validate(sc)


def test_from_text_phrase_app_evening_and_track_param():
    sc, _ = scenarios.from_text("когда я скажу «поехали», включи трек Кино группа крови")
    assert sc["conditions"] == [{"type": "phrase", "value": "поехали"}]
    assert sc["actions"] == [{"type": "action", "value": "music.play_track", "arg": "Кино группа крови"}]
    sc, _ = scenarios.from_text("когда я запущу Steam, включи мою волну")
    assert sc["conditions"] == [{"type": "app_started", "value": "Steam"}]
    sc, warn = scenarios.from_text("вечером скажи пора отдыхать")
    assert sc["conditions"] == [{"type": "time", "value": "21:00"}]
    assert sc["actions"] == [{"type": "notify", "value": "пора отдыхать"}]
    assert any("21:00" in w for w in warn)
    sc, warn = scenarios.from_text("включи мою волну")
    assert sc["conditions"] == [] and any("условие не нашла" in w for w in warn)


# ── автозапуск ────────────────────────────────────────────────────

@pytest.fixture
def fired(monkeypatch):
    calls = []

    async def fake_fire(s, trigger, device_id=None):
        calls.append((s["id"], trigger, device_id))
        return "r1"
    monkeypatch.setattr(trig, "fire", fake_fire)
    monkeypatch.setattr(st, "connected_devices", {})    # другие тесты оставляют устройства онлайн
    trig.reset(now=time.monotonic() - 1000)    # стартовая пауза уже прошла
    yield calls
    trig.reset()


def test_time_trigger_once_per_minute_and_respects_days(fired):
    a = scenarios.save({"name": "Будни", "conditions": [{"type": "time", "value": "07:30", "days": [0, 1, 2, 3, 4]}],
                        "actions": NOTIFY})
    b = scenarios.save({"name": "Диапазон", "conditions": [{"type": "time", "value": "07:30-09:00"}], "actions": NOTIFY})
    scenarios.save({"name": "Выкл", "enabled": False, "conditions": [{"type": "time", "value": "07:30"}],
                    "actions": NOTIFY})
    monday = dt.datetime(2026, 11, 16, 7, 30, 5)
    asyncio.run(trig.check_time(monday))
    asyncio.run(trig.check_time(monday.replace(second=40)))
    assert sorted(x[0] for x in fired) == sorted([a["id"], b["id"]]), "раз в минуту, выключенный — нет"
    fired.clear()
    asyncio.run(trig.check_time(dt.datetime(2026, 11, 21, 7, 30)))       # суббота
    assert [x[0] for x in fired] == [b["id"]]
    fired.clear()
    asyncio.run(trig.check_time(dt.datetime(2026, 11, 16, 7, 31)))
    assert fired == []


def test_device_triggers_ignore_short_reconnects_and_startup(fired, monkeypatch):
    monkeypatch.setattr(trig, "OFFLINE_S", 0.05)
    on = scenarios.save({"name": "Телефон пришёл", "conditions": [{"type": "device_connected", "value": "phone"}],
                         "actions": NOTIFY})
    off = scenarios.save({"name": "Кто-то ушёл", "conditions": [{"type": "device_disconnected", "value": ""}],
                          "actions": NOTIFY})

    async def scenario():
        await trig.on_device_connected("phone", was_online=True)          # уже был онлайн
        await trig.on_device_disconnected("phone")
        await trig.on_device_connected("phone", was_online=False)         # вернулся сразу — переподключение
        await asyncio.sleep(0.1)
        assert fired == []
        await trig.on_device_disconnected("phone")
        await asyncio.sleep(0.1)                                          # пропал надолго
        assert fired == [(off["id"], "device_disconnected", None)]
        await trig.on_device_connected("phone", was_online=False)
        assert fired[-1] == (on["id"], "device_connected", "phone")
        await trig.on_device_connected("laptop", was_online=False)        # не тот
        assert len(fired) == 2
    asyncio.run(scenario())
    fired.clear()
    trig.reset()                                                          # только что стартовали
    asyncio.run(trig.on_device_connected("phone", was_online=False))
    assert fired == []


def test_app_trigger_fires_on_rising_edge_with_cooldown(fired):
    s = scenarios.save({"name": "Steam", "conditions": [{"type": "app_started", "value": "steam"}], "actions": NOTIFY})

    async def go():
        await trig.on_window(MASTER, "Steam — Library")       # первый замер — только запомнить
        assert fired == []
        await trig.on_window(MASTER, "Discord")
        await trig.on_window(MASTER, "Steam — Store")
        assert fired == [(s["id"], "app_started", MASTER)]
        await trig.on_window(MASTER, "Discord")
        await trig.on_window(MASTER, "Steam")                  # в пределах паузы
        assert len(fired) == 1
        trig._app_last_fire.clear()
        await trig.on_window(MASTER, "Counter-Strike 2", game=True)
        assert len(fired) == 1
        await trig.on_window(MASTER, "Steam", game=True)      # начатая игра — сразу
        assert len(fired) == 2
    asyncio.run(go())


def test_fire_skips_dangerous_and_deviceless(monkeypatch):
    pushed = []

    async def bc(e):
        pushed.append(e)
    monkeypatch.setattr(pv2, "broadcast", bc)
    monkeypatch.setattr(st, "connected_devices", {})
    danger = scenarios.save({"name": "Отбой", "conditions": [{"type": "time", "value": "23:00"}],
                             "actions": [{"type": "action", "value": "system.shutdown"}]})
    music = scenarios.save({"name": "Волна", "conditions": [{"type": "time", "value": "08:00"}],
                            "actions": [{"type": "action", "value": "music.wave"}]})
    assert asyncio.run(trig.fire(danger, "time")) is None
    assert asyncio.run(trig.fire(music, "time")) is None
    assert scenarios.get(danger["id"])["last_status"] == "skipped"
    assert "опасные" in scenarios.get(danger["id"])["last_detail"]
    assert scenarios.get(music["id"])["last_detail"] == "нет устройства онлайн"
    started = [e for e in pushed if e["type"] == "scenario_run_started"]
    assert started[0]["trigger"] == "по времени" and started[0]["name"] == "Отбой"
    assert any(e["type"] == "scenario_event" and "пропущен" in e["detail"] for e in pushed)


def test_fire_runs_on_device(monkeypatch):
    pushed, sent = [], []

    async def bc(e):
        pushed.append(e)

    class Dev:
        async def send(self, raw):
            sent.append(json.loads(raw))
    monkeypatch.setattr(pv2, "broadcast", bc)
    monkeypatch.setattr(st, "connected_devices", {MASTER: Dev()})
    s = scenarios.save({"name": "Волна", "conditions": [{"type": "app_started", "value": "steam"}],
                        "actions": [{"type": "action", "value": "music.wave"}]})

    async def go():
        rid = await trig.fire(s, "app_started", MASTER)
        for _ in range(50):
            if any(e.get("status") == "done" for e in pushed):
                break
            await asyncio.sleep(0.02)
        return rid
    assert asyncio.run(go())
    assert any(c.get("type") == "command" for c in sent), "команда ушла на устройство"
    assert scenarios.get(s["id"])["run_count"] == 1


# ── Telegram: /сценарии ───────────────────────────────────────────

class _Msg:
    def __init__(self):
        self.answers, self.edits = [], []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))
        return self

    async def edit_text(self, text):
        self.edits.append(text)


class _Cb:
    def __init__(self, data):
        self.data, self.message, self.alerts = data, _Msg(), []

    async def answer(self, text=None, show_alert=False):
        self.alerts.append(text)


def test_telegram_list_and_dangerous_needs_yes(monkeypatch):
    from adapters import commands
    calls = []

    async def fake_fire(s, trigger, device_id=None, *, confirmed=False):
        calls.append((s["id"], trigger, confirmed))
        return "r1"
    monkeypatch.setattr(trig, "fire", fake_fire)
    safe = scenarios.save({"name": "Утро <b>", "actions": NOTIFY})
    danger = scenarios.save({"name": "Отбой", "actions": [{"type": "action", "value": "system.shutdown"}]})
    msg = _Msg()
    asyncio.run(commands.cmd_scenarios_impl(msg))
    text, kb = msg.answers[0]
    assert "Утро &lt;b&gt;" in text, "имя экранировано для HTML"
    assert [b[0].callback_data for b in kb.inline_keyboard] == [f"scn:run:{safe['id']}", f"scn:run:{danger['id']}"]

    cb = _Cb(f"scn:run:{danger['id']}")
    asyncio.run(commands.cb_scenarios_impl(cb))
    assert calls == [] and "опасные" in cb.message.answers[0][0]
    yes = _Cb(f"scn:yes:{danger['id']}")
    asyncio.run(commands.cb_scenarios_impl(yes))
    assert calls == [(danger["id"], "telegram", True)]
    run = _Cb(f"scn:run:{safe['id']}")
    asyncio.run(commands.cb_scenarios_impl(run))
    assert calls[-1] == (safe["id"], "telegram", False) and run.alerts == ["Запускаю"]
    no = _Cb("scn:no:")
    asyncio.run(commands.cb_scenarios_impl(no))
    assert no.message.edits == ["Хорошо, не запускаю."]
