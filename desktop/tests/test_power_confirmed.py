"""Выключение, перезагрузка, сон: подтверждение спрашивает сервер (вопрос kind=confirm), клиент
исполняет команду с confirmed: true сразу, без своего «Разрешить?», на любом ПК; bye — до исполнения;
shutdown — с /t 0 и без отсчёта; process.kill и файлы по-прежнему спрашивают."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from desktop.core import agent as agent_mod
from desktop.core import config, control
from desktop.core.chat_turns import ChatTurns
from desktop.core.platform import windows


class WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


class Asker:
    def __init__(self):
        self.asked = []

    async def ask(self, action, arg):
        self.asked.append(action)
        return False


def _agent(device="mostech", monkeypatch=None):
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a._ws = WS()
    a.media = None
    a.confirmations = Asker()
    events = []
    a.bus = SimpleNamespace(emit=lambda ev, **k: events.append((ev, k)))
    a.events = events
    return a


def _recv_command(a, cmd):
    """Команда приходит так же, как от сервера — через _recv_loop."""
    class It:
        def __init__(self):
            self.m = [json.dumps(cmd)]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.m:
                raise StopAsyncIteration
            return self.m.pop(0)
    sent = a._ws

    async def go():
        a._ws = It()
        a._ws.send = sent.send
        await a._recv_loop()
        await asyncio.sleep(0.05)
        for t in list(agent_mod.spawn.__globals__["_tasks"]):
            await t
    asyncio.run(go())
    a._ws = sent


@pytest.mark.parametrize("device", ["pc", "laptop", "mostech"])
@pytest.mark.parametrize("action,flag", [("system.shutdown", "/s"), ("system.restart", "/r")])
def test_confirmed_shutdown_runs_now_without_own_question(monkeypatch, device, action, flag):
    monkeypatch.setattr(config, "DEVICE_ID", device)
    a = _agent()
    with patch.object(windows.subprocess, "Popen") as popen:
        _recv_command(a, {"type": "command", "id": "c1", "action": action, "confirmed": True})
    assert a.confirmations.asked == []                         # своего «Разрешить?» нет
    args = popen.call_args[0][0]
    assert args[:2] == ["shutdown", flag] and args[args.index("/t") + 1] == "0"
    kinds = [m["type"] for m in a._ws.sent]
    assert kinds == ["bye", "command_result"]                  # bye — до исполнения
    assert a._ws.sent[0]["reason"] == "shutdown"
    assert a._ws.sent[1]["ok"] is True
    assert not [e for e, _ in a.events if e == "power_pending"]  # ни отсчёта, ни тоста


def test_confirmed_sleep_runs_without_question_and_says_bye(monkeypatch):
    a = _agent()
    slept = []
    monkeypatch.setattr(control.registry.Ctx, "default",
                        staticmethod(lambda: SimpleNamespace(platform=SimpleNamespace(power=slept.append))))
    _recv_command(a, {"type": "command", "id": "c2", "action": "power.sleep", "confirmed": True})
    assert a.confirmations.asked == [] and slept == ["sleep"]
    assert [m["type"] for m in a._ws.sent] == ["bye", "command_result"]
    assert a._ws.sent[0]["reason"] == "sleep"


def test_dangerous_without_confirmed_still_asks(monkeypatch):
    a = _agent()
    for action in ("process.kill", "files.delete", "power.sleep"):
        _recv_command(a, {"type": "command", "id": "c3", "action": action, "arg": "x"})
    assert a.confirmations.asked == ["process.kill", "files.delete", "power.sleep"]
    assert all(m["type"] == "command_result" and m["ok"] is False for m in a._ws.sent)  # отказ, bye не было


def test_shutdown_called_with_t0_by_default():
    assert config.SHUTDOWN_DELAY_S == 0
    assert windows.power_command("shutdown")[:4] == ["shutdown", "/s", "/t", "0"]
    assert windows.power_command("restart")[:4] == ["shutdown", "/r", "/t", "0"]


def test_confirm_question_is_chat_message_with_kind_confirm():
    out = []
    t = ChatTurns(out.append, device="pc")
    t.reply("Выключить игровой компьютер? Да или нет?", kind="confirm")
    assert out[-1]["message"]["kind"] == "confirm"           # без хода — всё равно вопрос, не proactive


def test_confirm_question_shown_even_with_server_chat(monkeypatch):
    from desktop.core.service import CoreService
    svc = CoreService.__new__(CoreService)
    svc.link = SimpleNamespace(proto=2)
    sent = []
    svc._emit = sent.append
    svc._chat_emit({"type": "chat_message", "message": {"role": "assistant", "kind": "llm", "text": "x"}})
    svc._chat_emit({"type": "chat_message", "message": {"role": "assistant", "kind": "confirm", "text": "Да или нет?"}})
    assert [e["message"]["kind"] for e in sent] == ["confirm"]
