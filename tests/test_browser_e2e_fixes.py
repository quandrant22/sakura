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


# ── ошибка заполнения в конвейере теста ──────────────────────────────

ORDER_ROWS = {"index": 6, "kind": "order", "text": "Порядок событий", "ref": "f0:e60",
              "rows": [{"ref": "f0:e61", "name": "Обед"}, {"ref": "f0:e62", "name": "Пробуждение"}],
              "options": [{"name": "1"}, {"name": "2"}], "has_media": False}
PAIRS = [{"row_ref": "f0:e61", "option_text": "2"}, {"row_ref": "f0:e62", "option_text": "1"}]


def _quiz_env(monkeypatch, solve_answers):
    from sakura_core import llm

    async def gen(contents, **kw):
        if kw.get("response_schema") is not None:
            return llm.AgentResponse("gemma-4-31b-it", SimpleNamespace(
                text=json.dumps({"reasoning": "r", "answer": solve_answers.pop(0)}),
                function_calls=None), 1)
        return llm.AgentResponse("gemma-4-26b-a4b-it", SimpleNamespace(
            function_calls=[SimpleNamespace(name="page_observe", args={"note": "смотрю"})],
            text=None), 1)

    monkeypatch.setattr(llm, "generate_agent", gen)
    from sakura_core import quiz_solver
    monkeypatch.setattr(quiz_solver, "needs_crop", lambda q: False)   # кадр вопроса здесь не нужен


def _obs():
    return {"snapshot_id": "s", "window_id": 9, "tab_id": 1, "url": "https://quiz/",
            "elements": [{"ref": f"f0:e{i}", "role": "button", "name": "b"} for i in range(6)]}


def _quiz_steps(env, task, results):
    async def run():
        outs = []
        for n, res in enumerate(results, 1):
            await bs.handle_step(env, {"request_id": f"r{n}", "task_id": task.task_id, "step": n,
                                       "observation": _obs(), "last_result": res,
                                       "frames": []})
            outs.append(env.sent[-1])
        return outs
    return asyncio.run(run())


@pytest.mark.parametrize("error", [
    {"ok": False, "status": "error", "detail": "заполнено 0 из 1",
     "data": {"fields": [{"ref": "f0:e60", "status": "error", "detail": "не поле ввода"}]}},
    {"ok": False, "status": "error", "detail": "кадр недоступен"},          # без полей
    {"ok": False, "status": "error", "detail": "x",
     "data": {"fields": [{"ref": "f9:e1", "status": "error"}]}},             # поля не сопоставились
])
def test_fill_error_retries_then_failed_with_reason(env, monkeypatch, error):
    _quiz_env(monkeypatch, [{"pairs": PAIRS}])
    task = bt.new_task("тест", device_id="pc")
    task.pending["await"] = "questions"
    outs = _quiz_steps(env, task, [{"ok": True, "status": "done", "questions": [ORDER_ROWS]},
                                   error, error])
    assert outs[0]["action"]["tool"] == "page_fill_form"       # первая попытка
    assert outs[1]["action"]["tool"] == "page_fill_form"       # повтор
    assert outs[2]["action"]["tool"] == "page_observe"         # дальше — навигатор
    entry = task.answers[0]
    assert entry["status"] == "failed" and entry["reason"]
    report = bs.report(task, "итог")
    assert "Вопрос 6: " in report and f"(не вписан: {entry['reason']})" in report


def test_fill_ok_still_filled_or_verified(env, monkeypatch):
    _quiz_env(monkeypatch, [{"pairs": PAIRS}])
    task = bt.new_task("тест", device_id="pc")
    task.pending["await"] = "questions"
    _quiz_steps(env, task, [{"ok": True, "status": "done", "questions": [ORDER_ROWS]},
                            {"ok": True, "status": "done", "detail": "заполнено 1 из 1"}])
    assert task.answers[0]["status"] == "filled" and "reason" not in task.answers[0]


# ── петля навигатора ─────────────────────────────────────────────────

def _fill_nav(monkeypatch, seen):
    from sakura_core import llm

    async def gen(contents, **kw):
        seen.append("\n".join(p.text for p in contents if getattr(p, "text", None)))
        return llm.AgentResponse("gemma-4-26b-a4b-it", SimpleNamespace(
            function_calls=[SimpleNamespace(name="page_fill_form", args={
                "fields": [{"ref": "f0:e1", "value": "1"}], "note": "заполняю вопрос 6"})],
            text=None), 1)

    monkeypatch.setattr(llm, "generate_agent", gen)


def test_loop_guard_hints_then_fails(env, monkeypatch):
    """Прогон 28.10: навигатор 15+ раз подряд повторял page_fill_form с error."""
    seen = []
    _fill_nav(monkeypatch, seen)
    task = bt.new_task("форма", device_id="pc")
    err = {"ok": False, "status": "error", "detail": "не поле ввода"}

    async def run():
        outs = []
        for n in range(1, 11):
            await bs.handle_step(env, {"request_id": f"r{n}", "task_id": task.task_id, "step": n,
                                       "observation": _obs(),
                                       "last_result": err if n > 1 else None, "frames": []})
            outs.append(env.sent[-1])
        return outs
    outs = asyncio.run(run())
    assert "уже 3 раз" not in seen[2] and "уже 3 раз за последние шаги вернул error" in seen[3]
    fail = next(i for i, o in enumerate(outs) if o.get("status") == "fail")
    assert fail == 8                                       # 8-я неудача подряд → fail
    assert outs[fail]["reason"].startswith("зациклилась: page_fill_form 8 раз")
    assert task.state == "fail"


def test_loop_guard_counts_failures_not_successes():
    task = bt.BrowserTask(task_id="t", goal="g")
    for n, (tool, st) in enumerate([("page_fill_form", "error"), ("page_forms", "done"),
                                    ("page_fill_form", "error"), ("page_forms", "done"),
                                    ("page_fill_form", "stale")], 1):
        task.steps.append({"n": n, "tool": tool, "status": st, "note": ""})
    assert bs.loop_guard(task) == ("page_fill_form", 3, "stale")
    task.steps = [{"n": 1, "tool": "page_act", "status": "done", "note": ""}]
    assert bs.loop_guard(task) is None
