"""Исправления по сквозному прогону desktop на тестовом инстансе (28.10).

Run: python -m pytest tests/test_browser_e2e_fixes.py -q
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

import config
from sakura_core import browser_step as bs
from sakura_core import browser_task as bt


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "TASKS_DIR", tmp_path / "browser_tasks")
    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    monkeypatch.setattr(bs, "_loaded", True)
    bt.reset()

    async def quiet(*a, **k):
        return SimpleNamespace(message_id=1)

    monkeypatch.setattr(bs, "tg_send", quiet)
    monkeypatch.setattr(bs, "orb", quiet)
    ws = WS()
    import modules.state as st
    monkeypatch.setattr(st, "connected_devices", {"pc": ws})
    yield ws
    bt.reset()


# ── продолжение после перезапуска ядра desktop ───────────────────────

def test_reconnect_sends_resume_for_active_tasks(env):
    running = bt.new_task("форма", device_id="pc")
    running.step = 31
    running.pending["intake_step"] = 31
    captcha = bt.new_task("тест", device_id="pc")
    captcha.state, captcha.pause_kind = "paused", "captcha"
    quota = bt.new_task("квота", device_id="pc")
    quota.state, quota.pause_kind, quota.resume_at = "paused", "quota", 9e9
    other = bt.new_task("чужая", device_id="laptop")
    done = bt.new_task("готово", device_id="pc")
    bt.finish(done, "done")
    assert asyncio.run(bs.on_device_registered("pc")) == 2
    assert env.sent == [
        {"type": "browser.do", "task_id": running.task_id, "goal": "форма", "resume": True},
        {"type": "browser.do", "task_id": captcha.task_id, "goal": "тест", "resume": True}]
    assert "intake_step" not in running.pending           # шаг 0 от desktop — новый шаг
    assert other.task_id not in {m["task_id"] for m in env.sent}


def test_reconnect_noop_when_agent_off(env, monkeypatch):
    bt.new_task("форма", device_id="pc")
    monkeypatch.setattr(config, "BROWSER_AGENT", False)
    assert asyncio.run(bs.on_device_registered("pc")) == 0 and env.sent == []


def test_register_triggers_resume(env, monkeypatch):
    """proto_v2.on_register master-устройства → browser.do resume его задачам."""
    import sakura_core.proto_v2 as pv2
    task = bt.new_task("тест", device_id="pc")
    monkeypatch.setattr(config, "PROTO_V2", True)
    monkeypatch.setattr(pv2, "_is_master", lambda d: True)

    async def run():
        await pv2.on_register(env, {"type": "register", "device_id": "pc", "proto": 2})
        await asyncio.sleep(0.05)
    asyncio.run(run())
    types = [m["type"] for m in env.sent]
    assert types[0] == "registered"
    assert {"type": "browser.do", "task_id": task.task_id, "goal": "тест", "resume": True} in env.sent


def test_resumed_step_zero_continues_from_checkpoint(env, monkeypatch):
    """После resume desktop шлёт step 0 с page_observe: сервер продолжает с шага 32."""
    from sakura_core import llm
    task = bt.new_task("тест", device_id="pc")
    task.step = 31
    task.pending["intake_step"] = 31
    asyncio.run(bs.on_device_registered("pc"))

    async def nav(contents, **kw):
        return llm.AgentResponse("gemma", SimpleNamespace(
            function_calls=[SimpleNamespace(name="page_observe", args={"note": "смотрю"})],
            text=None), 1)

    monkeypatch.setattr(llm, "generate_agent", nav)
    obs = {"snapshot_id": "s", "window_id": 9, "tab_id": 1, "url": "https://ex.com/",
           "elements": [{"ref": f"f0:e{i}", "role": "button", "name": "b"} for i in range(6)]}
    asyncio.run(bs.handle_step(env, {"request_id": "r", "task_id": task.task_id, "step": 0,
                                     "observation": obs}))
    assert env.sent[-1]["action"]["tool"] == "page_observe" and task.step == 32
