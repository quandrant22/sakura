"""Работа без сервера: локальный разбор фраз и выполнение без очереди на сервер."""
import asyncio
from types import SimpleNamespace

import pytest

from desktop.core import offline_intent as OI

TRIG = [
    {"id": "music.play_pause", "phrase": "пауза", "confirm": False},
    {"id": "music.next", "phrase": "следующий трек", "confirm": False},
    {"id": "screenshot.run", "phrase": "сделай скриншот", "confirm": False},
    {"id": "window.minimize", "phrase": "сверни окно", "confirm": False},
    {"id": "power.lock", "phrase": "заблокируй компьютер", "confirm": True},
]


@pytest.mark.parametrize("text,expected", [
    ("Сакура, громкость 30", ("system.volume", "30")),
    ("звук на 150", ("system.volume", "100")),
    ("открой блокнот", ("open.app", "блокнот")),
    ("пауза", ("music.play_pause", "")),
    ("Сакура, следующий трэк", ("music.next", "")),          # нечёткое — безопасное
    ("сделай скриншот!", ("screenshot.run", "")),
    ("заблокируй компьютер", ("power.lock", "")),            # разрушительное — только точно
    ("заблокируй компютер", None),                           # и не по похожей фразе
    ("какая завтра погода", None),                           # вопрос к модели
])
def test_match(text, expected):
    assert OI.OfflineIntents(TRIG).match(text) == expected


def test_real_registry_loads_safe_domains_only():
    trig = OI.load_triggers()
    assert trig and all(t["id"].startswith(OI.DOMAINS) for t in trig)
    assert not any(t["id"].startswith(("system.shutdown", "system.restart", "files.delete")) for t in trig)


def _agent(run_result):
    from desktop.core import agent as agent_mod
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    events, queued, runs = [], [], []
    a.bus = SimpleNamespace(emit=lambda ev, **k: events.append((ev, k)))
    a._set_state = lambda s: None
    a._offline_intents = OI.OfflineIntents(TRIG)

    async def run_command(action, cmd_id, arg="", confirmed=False):
        runs.append((action, arg))
        await a._send_result(cmd_id, run_result)
    a._run_command = run_command
    a._ws = None
    a.send_threadsafe = lambda *x, **k: queued.append(x)
    return a, events, queued, runs


def test_offline_command_runs_locally_once_and_is_not_queued():
    a, events, queued, runs = _agent({"ok": True, "status": "done", "detail": "громкость 30%"})

    async def go():
        a._loop = asyncio.get_running_loop()
        a.submit_user_text("громкость 30", source="ui")
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert runs == [("system.volume", "30")] and queued == []
    replies = [k for ev, k in events if ev == "sakura_text"]
    assert replies == [{"text": "Готово: громкость 30%. (офлайн-режим)", "kind": "template"}]


def test_offline_question_needs_server():
    a, events, queued, runs = _agent({})

    async def go():
        a._loop = asyncio.get_running_loop()
        a.submit_user_text("расскажи анекдот", source="mic")
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert runs == [] and queued == []
    assert [k["text"] for ev, k in events if ev == "sakura_text"] == [OI.REPLY_NEED_SERVER]
