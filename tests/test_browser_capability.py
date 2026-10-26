"""server/browser-step S9/S10: капабилити browser.task / browser.stop и гейт моста.

Run: python -m pytest tests/test_browser_capability.py -q
"""

import asyncio
import json

import config
import sakura_core.bridge as br
from sakura_core.registry import load


def test_registry_and_bridge_gate(monkeypatch):
    decls = {d.id: d for d in load()}
    assert decls["browser.task"].param.name == "goal"
    monkeypatch.setattr(config, "BROWSER_AGENT", False)
    assert not {"browser.task", "browser.stop"} & {d.id for d in br._gate(load())}
    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    monkeypatch.setattr(config, "BROWSER_CONFIRM_SENSITIVE", False)
    gated = {d.id: d for d in br._gate(load())}
    assert gated["browser.task"].confirm is False and "browser.stop" in gated
    monkeypatch.setattr(config, "BROWSER_CONFIRM_SENSITIVE", True)
    assert {d.id: d for d in br._gate(load())}["browser.task"].confirm is True


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


async def _no_llm(text, catalog):
    return None


def test_phrase_starts_task_and_stop_cancels(monkeypatch, tmp_path):
    """«сделай в браузере …» → browser.do на ПК; «останови задачу» → browser.cancel."""
    import modules.state as st
    import modules.ws_auth as wa
    from sakura_core import browser_step as bs
    from sakura_core import browser_task as bt
    from sakura_core.executor import Executor
    from sakura_core.router import Router

    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    monkeypatch.setattr(config, "BROWSER_CONFIRM_SENSITIVE", False)
    monkeypatch.setattr(bt, "TASKS_DIR", tmp_path)
    monkeypatch.setattr(wa, "is_master_device", lambda d: True)

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(bs, "tg_send", quiet)
    monkeypatch.setattr(bs, "orb", quiet)
    bt.reset()
    decls = br._gate(load())
    router = Router(declarations=decls, llm_classify=_no_llm)
    executor = Executor(session=router.session, declarations=decls)
    monkeypatch.setattr(br, "get_router", lambda: router)
    monkeypatch.setattr(br, "get_executor", lambda: executor)
    ws = WS()
    monkeypatch.setattr(st, "connected_devices", {"pc": ws})
    said = []

    async def speak(p, listen=None):
        said.append(p)

    async def run(text):
        await br.v3_fast_path(text, data={}, device_ws=ws, device_id="pc",
                              register_command=lambda a, dev: "c1", speak=speak, source="pc")
    asyncio.run(run("сделай в браузере запишись к врачу на сайте клиники"))
    assert said[-1].startswith("Начинаю в браузере")
    msg = ws.sent[-1]
    assert msg["type"] == "browser.do" and msg["goal"] == "запишись к врачу на сайте клиники"
    asyncio.run(run("останови задачу"))
    assert said[-1] == "Остановила задачу в браузере."
    assert ws.sent[-1] == {"type": "browser.cancel", "task_id": msg["task_id"]}
    bt.reset()
