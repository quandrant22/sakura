"""Чистая память задач/нитей и реальное присутствие Мастера.

Run: python -m pytest tests/test_presence_memory.py -q
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

import config
import modules.state as st
from modules import context, presence_sync as ps, task_cleanup, tasks, threads

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tdir(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "TASKS_FILE", str(tmp_path / "tasks.json"))
    monkeypatch.setattr(tasks, "ARCHIVE_FILE", str(tmp_path / "tasks_archive.json"))
    return tmp_path


# ── задачи ────────────────────────────────────────────────────────

def test_plain_speech_does_not_create_task(tdir, monkeypatch):
    """«надо купить хлеб» в обычной речи — не задача."""
    import sakura_core.memory_tasks as mt
    monkeypatch.setattr(mt, "get_active_key", lambda: "k")
    monkeypatch.setattr("sakura_core.llm.get_client", lambda k: object())
    monkeypatch.setattr("sakura_core.llm.generate", AsyncMock(return_value="{}"))
    monkeypatch.setattr(mt, "_llm_generate", AsyncMock(return_value="{}"), raising=False)
    monkeypatch.setattr(mt, "mark_key_used", lambda k: None)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    asyncio.run(mt.extract_and_remember("надо купить хлеб, завтра в 10", "Ок."))
    assert tasks.load_tasks() == []
    assert not hasattr(tasks, "extract_tasks_from_text")


def test_explicit_remind_creates_task(tdir):
    from modules.voice_info import reminders_add, tasks_add
    text, ok = asyncio.run(tasks_add("завтра в 10 купить хлеб"))
    assert ok
    (t,) = tasks.load_tasks()
    assert t["text"] == "купить хлеб" and t["due_time"] == "10:00"
    assert t["due_date"] == str(datetime.now().date() + timedelta(days=1))
    # «напомни … завтра …» через напоминания (нет «через N минут») — тоже задача
    text, ok = asyncio.run(reminders_add("напомни мне завтра в 10 позвонить маме"))
    assert ok and [x["text"] for x in tasks.load_tasks()] == ["купить хлеб", "позвонить маме"]


def test_remind_phrase_routes_to_task_add(tdir, monkeypatch):
    from sakura_core.executor import ExecutionContext, get_handler
    from sakura_core.router import Router
    from tests.test_vps_arguments import _load_capabilities
    _load_capabilities()
    phrase = "напомни завтра в 10 купить хлеб"
    decision = asyncio.run(Router().route(phrase))
    assert decision.action == "task.add"
    answer = AsyncMock(return_value=("Ответ", True))
    monkeypatch.setattr("modules.voice_info.handle", answer)
    asyncio.run(get_handler(decision.action)(ExecutionContext(
        param=decision.param, extra={"text": phrase})))
    answer.assert_awaited_once_with("task:add", "завтра в 10 купить хлеб", phrase)


def test_stale_overdue_task_archived_and_not_in_prompt(tdir):
    now = datetime.now()
    old = str((now - timedelta(days=2)).date())
    fresh = str((now - timedelta(hours=1)).date())
    tasks.save_tasks([
        {"id": 1, "text": "старая", "due_date": old, "due_time": "10:00", "done": False, "notified": False},
        {"id": 2, "text": "сегодняшняя", "due_date": str(now.date()), "due_time": "23:59", "done": False, "notified": False},
        {"id": 3, "text": "напомненная", "due_date": str(now.date()), "due_time": "23:58", "done": False, "notified": True},
        {"id": 4, "text": "сделанная", "due_date": str(now.date()), "done": True, "notified": False},
        {"id": 5, "text": "без срока", "due_date": None, "done": False, "notified": False},
    ])
    ctx = tasks.get_tasks_context()
    assert "старая" not in ctx and "напомненная" not in ctx and "сделанная" not in ctx
    assert "сегодняшняя" in ctx and "без срока" in ctx
    arch = json.loads((tdir / "tasks_archive.json").read_text(encoding="utf-8"))
    assert [t["text"] for t in arch] == ["старая"]
    assert "старая" not in [t["text"] for t in tasks.load_tasks()]
    assert [t["id"] for t in tasks.get_due_tasks()] == []      # и не напоминается


# ── нити ──────────────────────────────────────────────────────────

def test_threads_off_by_default():
    assert config.THREADS is False
    threads.extract_threads("надо будет разобраться с VPS", "ок")
    assert threads.get_threads_context() == "" and threads.get_thread_recall() is None
    from memory.db import _conn
    threads._ensure_table()
    assert _conn().execute("SELECT COUNT(*) FROM conversation_threads").fetchone()[0] == 0


# ── очистка ───────────────────────────────────────────────────────

@pytest.fixture
def junk(tdir, monkeypatch):
    from memory.db import _conn
    threads._ensure_table()
    conn = _conn()
    conn.execute("DELETE FROM conversation_threads")
    conn.execute("INSERT INTO conversation_threads(topic, summary) VALUES ('надо купить хлеб', 'x')")
    conn.execute("INSERT INTO conversation_threads(topic, summary, closed) VALUES ('закрытая', 'y', 1)")
    conn.commit()
    tasks.save_tasks([{"id": 1, "text": "завтра надо " + "очень длинная задача " * 5, "done": False}])
    yield
    conn.execute("DELETE FROM conversation_threads")
    conn.commit()


def test_cleanup_backs_up_before_deleting(junk, tdir):
    root = tdir / "backup"
    seen = {}
    real_save = tasks.save_tasks

    def spy(data):
        # к моменту очистки копия уже на диске
        seen["backup_existed"] = any((p / "tasks.json").exists() for p in root.iterdir())
        real_save(data)
    tasks.save_tasks = spy
    try:
        res = task_cleanup.run(str(root))
    finally:
        tasks.save_tasks = real_save
    assert seen["backup_existed"]
    (d,) = list(root.iterdir())
    assert json.loads((d / "tasks.json").read_text(encoding="utf-8"))[0]["id"] == 1
    rows = json.loads((d / "conversation_threads.json").read_text(encoding="utf-8"))
    assert {r["topic"] for r in rows} == {"надо купить хлеб", "закрытая"}
    assert (res["tasks"], res["threads"]) == (1, 1)
    assert tasks.load_tasks() == []
    assert task_cleanup.preview() == {"tasks": [], "threads": []}


def test_cleanup_script_dry_run_changes_nothing(junk, tdir):
    before = tasks.load_tasks()
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, runpy; sys.argv=['cleanup_tasks.py','--dry-run']; "
         "import os; os.environ['MEMORY_DB_PATH']=os.environ['MEMORY_DB_PATH']; "
         "import modules.tasks as t; t.TASKS_FILE=%r; "
         "runpy.run_path(%r, run_name='__main__')" % (tasks.TASKS_FILE, os.path.join(ROOT, "scripts", "cleanup_tasks.py"))],
        capture_output=True, text=True, cwd=str(tdir), env={**os.environ, "PYTHONPATH": ROOT})
    assert "dry-run" in out.stdout, out.stderr
    assert "Задач: 1" in out.stdout and "Открытых нитей: 1" in out.stdout
    assert "надо купить хлеб" in out.stdout
    assert max(len(l) for l in out.stdout.splitlines() if l.startswith("  - ")) <= 4 + 40
    assert tasks.load_tasks() == before
    assert not (tdir / "memory").exists() and not (tdir / "backup").exists()
    assert task_cleanup.preview()["threads"] == ["надо купить хлеб"]


def test_forget_tasks_command_asks_then_cleans(junk, tdir, monkeypatch):
    from types import SimpleNamespace
    from adapters.commands import cb_forget_tasks_impl, cmd_forget_tasks_impl
    monkeypatch.setattr(task_cleanup, "BACKUP_ROOT", str(tdir / "b"))
    m = SimpleNamespace(answer=AsyncMock())
    asyncio.run(cmd_forget_tasks_impl(m))
    text = m.answer.await_args.args[0]
    assert "задач: 1" in text and "нитей: 1" in text and "Удалить?" in text
    assert [b.text for b in m.answer.await_args.kwargs["reply_markup"].inline_keyboard[0]] == ["Да", "Нет"]
    assert tasks.load_tasks()                                    # пока ничего не удалено
    cb = SimpleNamespace(data="forget_tasks:no", message=SimpleNamespace(edit_text=AsyncMock()),
                         answer=AsyncMock())
    asyncio.run(cb_forget_tasks_impl(cb))
    assert tasks.load_tasks()                                    # «Нет» — ничего не тронуто
    cb = SimpleNamespace(data="forget_tasks:yes", message=SimpleNamespace(edit_text=AsyncMock()),
                         answer=AsyncMock())
    asyncio.run(cb_forget_tasks_impl(cb))
    assert tasks.load_tasks() == [] and task_cleanup.preview()["threads"] == []
    assert (tdir / "b").exists() and "Копия" in cb.message.edit_text.await_args.args[0]


# ── присутствие ───────────────────────────────────────────────────

class WS:
    pass


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 5000.0}
    monkeypatch.setattr(ps, "_now", lambda: t["now"])
    monkeypatch.setattr(ps, "_wall", lambda: 1_800_000_000.0 + t["now"])
    ps.reset()
    monkeypatch.setattr(st, "connected_devices", {})
    yield t
    ps.reset()


def online(*devs):
    st.connected_devices.clear()
    for d in devs:
        st.connected_devices[d] = WS()


def ping(dev, idle=None):
    data = {"type": "ping"}
    if idle is not None:
        data["input_idle_s"] = idle
    ps.update(dev, data)


def test_presence_at_pc_and_away(clock):
    online("pc")
    ping("pc", idle=120)
    p = ps.get_master_presence()
    assert (p["state"], p["device"]) == ("at_pc", "pc")
    clock["now"] += 780                     # ввода не было 15 мин
    ping("pc", idle=900)
    p = ps.get_master_presence()
    assert p["state"] == "away_from_pc" and p["device"] == "pc" and 890 < p["idle_s"] < 910


def test_presence_no_pc_is_pcs_off_and_bye_is_immediate(clock):
    assert ps.get_master_presence()["state"] == "pcs_off"
    online("phone")                         # телефон — не ПК
    assert ps.get_master_presence()["state"] == "pcs_off"
    online("pc")
    ping("pc", idle=1)
    assert ps.get_master_presence()["state"] == "at_pc"
    ps.mark_bye("pc", "shutdown")           # сокет ещё в connected_devices
    p = ps.get_master_presence()
    assert (p["state"], p["device"], p["reason"]) == ("pcs_off", "pc", "shutdown")
    assert p["since"] is not None
    ping("pc", idle=1)                      # вернулся
    assert ps.get_master_presence()["state"] == "at_pc"


def test_presence_at_work_on_mostech(clock):
    online("pc", "mostech")
    ping("pc", idle=300)
    ping("mostech", idle=2)
    p = ps.get_master_presence()
    assert (p["state"], p["device"]) == ("at_work", "mostech")


def test_presence_legacy_client_uses_voice_time(clock):
    online("laptop")
    ping("laptop")                          # input_idle_s нет
    assert ps.get_master_presence()["state"] == "at_pc"
    clock["now"] += 700
    ping("laptop")
    assert ps.get_master_presence()["state"] == "away_from_pc"
    ps.note_input("laptop")                 # голос/текст
    assert ps.get_master_presence()["state"] == "at_pc"


def test_bye_handler_marks_offline(clock, monkeypatch):
    from modules import device_manager
    import sakura_core.ws_protocol as wp
    from sakura_core import proto_devices
    monkeypatch.setattr(device_manager, "set_device_offline", lambda d, r=None: None)
    monkeypatch.setattr(proto_devices, "push_device", AsyncMock())
    monkeypatch.setattr(proto_devices, "push_status", AsyncMock())
    online("laptop")
    ping("laptop", idle=1)
    asyncio.run(wp.handle_bye(None, {"type": "bye", "device_id": "laptop", "reason": "sleep"}, {}))
    p = ps.get_master_presence()
    assert (p["state"], p["reason"]) == ("pcs_off", "sleep")
    asyncio.run(wp.handle_bye(None, {"type": "bye", "device_id": "phone", "reason": "exit"}, {}))
    assert not ps.is_bye("phone")           # не master — игнор


# ── промпт ────────────────────────────────────────────────────────

def fake_presence(monkeypatch, **p):
    base = {"state": "at_pc", "device": "pc", "idle_s": 30.0, "since": None, "reason": None}
    monkeypatch.setattr(ps, "get_master_presence", lambda *a, **k: {**base, **p})
    monkeypatch.setattr(context, "get_devices_snapshot", lambda: {
        "pc": {"online": True, "active_window": "Cyberpunk 2077"}})
    monkeypatch.setattr(context, "get_active_device", lambda: "pc")


def test_prompt_phrases(monkeypatch):
    d = context.describe_presence
    assert d({"state": "at_pc", "device": "pc"}) == "Мастер за игровым ПК"
    assert d({"state": "away_from_pc", "device": "laptop", "idle_s": 1500}) == \
        "Мастер отошёл от ноутбука 25 мин назад"
    assert d({"state": "at_work", "device": "mostech"}) == "Мастер на работе за рабочим ноутбуком"
    ts = datetime.now().replace(hour=23, minute=10, second=0).timestamp()
    assert d({"state": "pcs_off", "since": ts, "reason": "shutdown"}) == "Все компьютеры выключены с 23:10"


def test_playing_not_detected_when_away(monkeypatch):
    fake_presence(monkeypatch)
    assert "играет" in context.build_context_block()            # за ПК — игра в окне
    fake_presence(monkeypatch, state="away_from_pc", idle_s=1500.0)
    block = context.build_context_block()
    assert "играет" not in block and "Cyberpunk" not in block
    assert "Мастер отошёл от игрового ПК 25 мин назад" in block
    assert "Он не у компьютера. Голосом на ПК не говори — если пишешь, то в Telegram" in block
    ctx = context.get_full_context()
    assert ctx["master"]["is_gaming"] is False and ctx["master"]["activity"] == "unknown"


def test_pcs_off_prompt_uses_schedule_only_as_fallback(monkeypatch):
    fake_presence(monkeypatch, state="pcs_off", device=None, idle_s=None,
                  since=datetime.now().timestamp() - 60)
    block = context.build_context_block()
    assert "Все компьютеры выключены с" in block and "по расписанию" in block
    assert "Он не у компьютера" in block and "играет" not in block


# ── куда уходят проактив и напоминания ───────────────────────────

def test_pc_shutdown_is_not_an_alarm():
    from modules.proactive import get_fact_trigger
    old = (datetime.now() - timedelta(hours=2)).isoformat()
    for dev in ("pc", "laptop", "mostech"):
        assert get_fact_trigger({dev: {"online": False, "last_seen": old}})[0] != "monitor_device"


def test_reminder_goes_to_telegram_not_pc_when_pcs_off(clock, monkeypatch):
    import modules.tts_server as tts
    from sakura_core.callbacks import make_reminder_cb
    sent_tg, spoken = AsyncMock(), AsyncMock()
    ws = WS()
    monkeypatch.setattr(ps, "get_master_presence", lambda *a, **k: {"state": "pcs_off"})

    async def go():
        cb = await make_reminder_cb(lambda: (ws, "pc"), spoken, sent_tg, lambda: "спокойная")
        await cb("Напоминание: позвонить маме")
        # реальная озвучка проактива — гейт внутри stream_tts_to_device
        sends = []

        class S:
            async def send(self, raw):
                sends.append(raw)
        await tts.stream_tts_to_device("Напоминаю", S(), "pc", literal=True, reply_kind="proactive")
        from sakura_core import voice_turns
        n = await voice_turns.broadcast_reply("Напоминаю", "proactive")
        return sends, n
    sends, n = asyncio.run(go())
    sent_tg.assert_awaited_once()                     # Telegram — да
    assert sends == [] and n == 0                     # на ПК — ни голоса, ни reply


def test_reminder_still_spoken_when_at_pc(clock, monkeypatch):
    from sakura_core import voice_turns
    monkeypatch.setattr(ps, "get_master_presence", lambda *a, **k: {"state": "at_pc"})
    online("pc")
    sent = []

    class S:
        async def send(self, raw):
            sent.append(json.loads(raw))
    st.connected_devices["pc"] = S()
    assert asyncio.run(voice_turns.broadcast_reply("Напоминаю", "proactive")) == 1
