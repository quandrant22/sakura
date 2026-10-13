"""feat/pc-control п.3: computer.do и computer_step (COMPUTER_USE, по умолчанию выкл).

Run: python -m pytest tests/test_computer_use.py -q
"""

import asyncio
import base64
import json
import logging

import pytest

import config
import sakura_core.bridge as br
from sakura_core import computer_use as cu
from sakura_core.executor import Executor
from sakura_core.registry import load
from sakura_core.router import Router

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100
B64 = base64.b64encode(JPEG).decode()


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def _step(monkeypatch=None, **over):
    data = {"type": "computer_step", "request_id": "s1", "device_id": "laptop",
            "goal": "открой почту", "history": [], "screenshot": B64, **over}
    ws = WS()
    asyncio.run(cu.handle(ws, data))
    return ws.sent[-1]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(config, "COMPUTER_USE", True)


@pytest.fixture
def model(monkeypatch):
    import sakura_core.llm as llm
    seen = {}

    async def _gen(contents, **kw):
        seen["mime"] = contents[0].inline_data.mime_type
        seen["prompt"] = contents[1].text
        seen["chain"] = kw.get("chain")
        return seen.get("answer", '{"type": "click", "target": "Входящие", "reason": "открыть почту"}')
    monkeypatch.setattr(llm, "generate", _gen)
    return seen


# ── выключено по умолчанию ─────────────────────────────────────────

def test_off_by_default():
    assert config.COMPUTER_USE is False
    assert "computer.do" not in {d.id for d in br._declarations}, "при выключенном — не в роутере"
    assert "computer.do" in {d.id for d in load()}


def test_step_unsupported_when_off():
    r = _step()
    assert r["type"] == "error" and r["code"] == "unsupported"


# ── декларация и подтверждение ─────────────────────────────────────

async def _no_llm(text, catalog):
    return None


def test_computer_do_asks_then_sends_goal_confirmed(monkeypatch):
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    decls = load()
    d = next(x for x in decls if x.id == "computer.do")
    assert (d.executor, d.confirm, d.reversible) == ("agent", True, False)
    router = Router(declarations=decls, llm_classify=_no_llm)
    executor = Executor(session=router.session, declarations=decls)
    monkeypatch.setattr(br, "get_router", lambda: router)
    monkeypatch.setattr(br, "get_executor", lambda: executor)
    ws = WS()
    said = []

    async def speak(p, listen=None):
        said.append(p)
    asyncio.run(br.v3_fast_path("сделай на компьютере открой почту и найди письмо от банка",
                                data={}, device_ws=ws, device_id="laptop",
                                register_command=lambda a, dev: "c1", speak=speak,
                                source="laptop"))
    assert said == [d.confirm_prompt] and ws.sent == []
    dec = asyncio.run(router.route("да", None, source="laptop"))
    asyncio.run(br.execute_decision(dec, device_ws=ws, device_id="laptop",
                                    register_command=lambda a, dev: "c1", text="да",
                                    source="laptop"))
    assert ws.sent == [{"type": "command", "action": "computer.do", "id": "c1",
                        "arg": "открой почту и найди письмо от банка", "confirmed": True}]


# ── computer_step ──────────────────────────────────────────────────

def test_step_returns_one_action(on, model, caplog):
    caplog.set_level(logging.INFO)
    r = _step(history=[{"type": "click", "target": "Пуск", "result": "done"}])
    assert r == {"type": "computer_step", "request_id": "s1",
                 "action": {"type": "click", "target": "Входящие", "text": "",
                            "reason": "открыть почту"}}
    assert model["mime"] == "image/jpeg" and model["chain"] == config.VISION_MODEL_CHAIN
    assert "открой почту" in model["prompt"] and "1. click Пуск" in model["prompt"]
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert B64[:12] not in logged and "шаг 2/20 → click" in logged


@pytest.mark.parametrize("over,code", [
    ({"device_id": "phone"}, "not_master"),
    ({"goal": ""}, "bad_request"),
    ({"history": "не список"}, "bad_request"),
    ({"screenshot": ""}, "bad_request"),
    ({"screenshot": "!!!не base64"}, "bad_request"),
    ({"screenshot": base64.b64encode(b"\x89PNG\r\n\x1a\n...").decode()}, "bad_request"),
    ({"screenshot": base64.b64encode(b"\xff\xd8\xff" + b"0" * (400 * 1024)).decode()}, "bad_request"),
])
def test_step_rejects(on, model, over, code):
    r = _step(**over)
    assert r["type"] == "error" and r["code"] == code


def test_step_limit_20(on, model):
    r = _step(history=[{"type": "click"}] * 20)
    assert r["action"]["type"] == "fail" and "20" in r["action"]["reason"]
    assert "prompt" not in model, "после лимита модель не зовётся"


def test_frame_exactly_400kb_accepted(on, model):
    frame = b"\xff\xd8\xff" + b"0" * (400 * 1024 - 3)
    r = _step(screenshot=base64.b64encode(frame).decode())
    assert r["type"] == "computer_step"


@pytest.mark.parametrize("raw,kind", [
    ('{"type": "done", "reason": "почта открыта"}', "done"),
    ('Вот: {"type": "TYPE", "target": "Поиск", "text": "банк"}', "type"),
    ('{"type": "rm -rf"}', "fail"),
    ("не json", "fail"),
    ('{"type": "key", "text": "ctrl+s"}', "key"),
])
def test_parse_action(raw, kind):
    a = cu.parse_action(raw)
    assert a["type"] == kind and set(a) == {"type", "target", "text", "reason"}


def test_model_failure_is_fail_action(on, monkeypatch):
    import sakura_core.llm as llm

    async def _boom(*a, **k):
        raise RuntimeError("503")
    monkeypatch.setattr(llm, "generate", _boom)
    r = _step()
    assert r["action"]["type"] == "fail"
