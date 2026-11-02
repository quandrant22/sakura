"""server/browser-step: метрики задачи browser agent.

Одна строка в лог на задачу и блок в отчёте: итог, шаги, вызовы навигатора и
решателя по моделям, 429/500/503, ожидание лимитера, медиана и p90 задержки,
время. Только числа и имена моделей — без кадров и текстов страниц.

Run: python -m pytest tests/test_browser_metrics.py -q
"""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

import config
from sakura_core import browser_step as bs
from sakura_core import browser_task as bt
from sakura_core import llm
from sakura_core import rate_limiter as rl

PAGE_SECRET = "PAGE_TEXT_SECRET_77"
JPEG = b"\xff\xd8\xff\xe0" + b"METRICFRAME" * 10


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"{code} {'RESOURCE_EXHAUSTED' if code == 429 else 'INTERNAL'}")
        self.code = code
        self.details = {"error": {"details": []}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "TASKS_DIR", tmp_path / "browser_tasks")
    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    monkeypatch.setattr(config, "BROWSER_SUMMARIZE_EVERY", 0)
    monkeypatch.setattr(bs, "_loaded", True)
    import modules.ws_auth as wa
    monkeypatch.setattr(wa, "is_master_device", lambda d: True)
    bt.reset()
    sent = []

    async def tg_send(text):
        sent.append(text)
        return SimpleNamespace(message_id=1)

    async def tg_edit(msg, text):
        return True

    async def orb(text):
        return None

    monkeypatch.setattr(bs, "tg_send", tg_send)
    monkeypatch.setattr(bs, "tg_edit", tg_edit)
    monkeypatch.setattr(bs, "orb", orb)
    yield sent
    bt.reset()
    bs._locks.clear()


def _obs():
    return {"snapshot_id": "s", "window_id": 1, "tab_id": 1, "url": "https://ex.com/",
            "title": "T", "text": PAGE_SECRET,
            "elements": [{"ref": f"f0:e{i}", "role": "button", "name": f"b{i}",
                          "enabled": True, "in_viewport": True} for i in range(6)]}


def _fc(tool, **args):
    args.setdefault("note", "делаю шаг")
    return SimpleNamespace(function_calls=[SimpleNamespace(name=tool, args=args)], text=None,
                           usage_metadata=None)


def test_percentile_nearest_rank():
    assert bs._pct([], 50) is None
    assert bs._pct([5.0], 90) == 5.0
    vals = [float(i) for i in range(1, 11)]
    assert bs._pct(vals, 50) == 5.0 and bs._pct(vals, 90) == 9.0
    assert bs._pct([3.0, 1.0, 2.0], 50) == 2.0


def test_recorder_counts_calls_errors_waits():
    task = bt.BrowserTask(task_id="m1", goal="g")
    nav, solver = bs.recorder(task, "nav"), bs.recorder(task, "solver")
    nav("call", model="gemma-4-26b-a4b-it", latency=2.5, ok=True, code="")
    nav("call", model="gemma-4-26b-a4b-it", latency=1.0, ok=False, code="429")
    nav("call", model="gemma-4-26b-a4b-it", latency=1.0, ok=False, code="INTERNAL")
    solver("call", model="gemma-4-31b-it", latency=7.0, ok=True, code="")
    solver("call", model="gemma-4-31b-it", latency=0.5, ok=False, code="UNAVAILABLE")
    nav("wait", seconds=4.0)
    s = bs.metrics_summary(task)
    assert s["nav"] == {"gemma-4-26b-a4b-it": 3} and s["solver"] == {"gemma-4-31b-it": 2}
    assert s["errors"] == {"429": 1, "500": 1, "503": 1}
    assert s["wait_s"] == 4.0 and s["calls_ok"] == 2
    assert s["lat_median_s"] == 2.5 and s["lat_p90_s"] == 7.0


def test_generate_agent_emits_events(monkeypatch):
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock)
    script = {"a": [ApiError(429), ApiError(500)], "b": []}

    async def raw(model, contents, timeout=None, **cfg):
        if script[model]:
            raise script[model].pop(0)
        return SimpleNamespace(text="ok", usage_metadata=None)

    async def sleep(s):
        clock.t += s

    monkeypatch.setattr(llm, "generate_raw", raw)
    events = []
    asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim, inline_wait=100,
                                   sleep=sleep, on_event=lambda k, **d: events.append((k, d))))
    calls = [(d["model"], d["ok"], d["code"]) for k, d in events if k == "call"]
    assert calls == [("a", False, "429"), ("a", False, "500"), ("a", True, "")]
    assert [round(d["seconds"]) for k, d in events if k == "wait"] == [4, 5]


def test_broken_recorder_does_not_break_call(monkeypatch):
    async def raw(model, contents, timeout=None, **cfg):
        return SimpleNamespace(text="ok", usage_metadata=None)

    def boom(kind, **data):
        raise RuntimeError("метрика")

    monkeypatch.setattr(llm, "generate_raw", raw)
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None)
    assert asyncio.run(llm.generate_agent(["x"], chain=("a",), limiter=lim, on_event=boom)).model == "a"


def test_task_metrics_logged_once_and_in_report(env, monkeypatch, caplog):
    """Сквозной путь: навигатор через настоящий generate_agent (429 на шаге 2,
    квота для desktop), done → одна строка [browser-metrics] и блок в отчёте."""
    caplog.set_level(logging.INFO)
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=1000, path=None, clock=clock)
    monkeypatch.setattr(rl, "_limiter", lim)
    replies = [_fc("page_observe"), ApiError(429), _fc("done", summary="готово")]

    async def raw(model, contents, timeout=None, **cfg):
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm, "generate_raw", raw)
    original = llm.generate_agent

    async def no_inline_wait(*a, **kw):          # блок 4 с → сразу wait на desktop
        return await original(*a, inline_wait=1, **kw)

    monkeypatch.setattr(llm, "generate_agent", no_inline_wait)
    task = bt.new_task("цель", device_id="pc")
    ws = WS()

    async def step(n, frames=()):
        data = {"request_id": f"r{n}", "task_id": task.task_id, "step": n, "observation": _obs(),
                "frames": [{"frame_id": "f", "kind": "page", "mime": "image/jpeg",
                            "data_b64": __import__("base64").b64encode(JPEG).decode()}
                           for _ in frames]}
        if n > 1:
            data["last_result"] = {"ok": True, "status": "done"}
        await bs.handle_step(ws, data)
        return ws.sent[-1]

    async def run():
        outs = [await step(1, frames=[1])]
        outs.append(await step(2))              # 429 → блок 4 с → wait на desktop
        clock.t += 5
        outs.append(await step(2))              # повтор шага → done
        return outs
    outs = asyncio.run(run())
    assert outs[1] == {"type": "browser_step", "request_id": "r2", "task_id": task.task_id,
                       "status": "wait", "retry_after": 4}
    assert outs[2]["status"] == "done"
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[browser-metrics]")]
    assert len(lines) == 1
    line = lines[0]
    assert f"task={task.task_id} итог=done шагов=2" in line
    assert "nav=gemma-4-26b-a4b-it:3" in line and "solver=—" in line
    assert "429=1 500=0 503=0" in line and "ожидание_лимитера=4.0с" in line
    assert "вызовов_ок=2" in line and "время=" in line and "активно=" in line
    assert PAGE_SECRET not in caplog.text and "METRICFRAME" not in caplog.text
    report = env[-1]
    assert "Метрики: вызовов навигатора 3 (gemma-4-26b-a4b-it:3), решателя 0" in report
    assert "ошибки 429×1" in report and "ожидание лимитера 4.0 с" in report


def test_metrics_survive_checkpoint(env):
    task = bt.new_task("цель", device_id="pc")
    bs.recorder(task, "solver")("call", model="gemma-4-31b-it", latency=3.0, ok=True, code="")
    task.metrics["wait_s"] = 12.0
    bt.checkpoint(task)
    raw = (bt.TASKS_DIR / f"{task.task_id}.json").read_text(encoding="utf-8")
    assert json.loads(raw)["metrics"]["calls"] == {"solver:gemma-4-31b-it": 1}
    bt.reset()
    restored = bt.get(task.task_id)
    assert bs.metrics_summary(restored)["solver"] == {"gemma-4-31b-it": 1}
    assert restored.metrics["wait_s"] == 12.0


def test_cancel_logs_metrics(env, caplog):
    caplog.set_level(logging.INFO)
    task = bt.new_task("цель", device_id="pc")
    asyncio.run(bs.cancel(task, "остановлено"))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[browser-metrics]")]
    assert len(lines) == 1 and "итог=cancelled шагов=0" in lines[0]
