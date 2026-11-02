"""Связка агента браузера: маршрутизация browser.do/cancel/resume в Agent, запрет js_exec,
транзит ext:<действие 3.2.0>, extension_server (args, upload_fetch, версия и ID расширения),
Настройки → «Расширение браузера»."""
import asyncio
import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from desktop.core import agent as agent_module
from desktop.core import browser

CORE = Path(__file__).resolve().parents[1] / "core"


class FakeWS:
    def __init__(self, messages=()):
        self._messages = [json.dumps(m) for m in messages]
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, data):
        self.sent.append(json.loads(data))


class FakeBA:
    def __init__(self):
        self.calls = []

    def start(self, task_id, goal, start_url=None):
        self.calls.append(("start", task_id, goal, start_url))
        return True

    def cancel(self, task_id):
        self.calls.append(("cancel", task_id))
        return True

    def resume(self, task_id, local=True):
        self.calls.append(("resume", task_id, local))
        return True

    def cancel_all(self):
        self.calls.append(("cancel_all",))


def _agent(messages=(), master=True):
    a = agent_module.Agent.__new__(agent_module.Agent)
    a.bus = SimpleNamespace(events=[], emit=lambda e, **k: a.bus.events.append((e, k)))
    a._ws = FakeWS(messages)
    a._state = "idle"
    a._state_since = 0.0
    a._turn_gen = 0
    a._state_lock = threading.Lock()
    a._abort_flag = False
    a.media = None
    a.server_link = SimpleNamespace(handle=lambda d: False, master=master, online=True)
    a.browser_agent = FakeBA()
    return a


def test_browser_messages_route_to_browser_agent():
    a = _agent([
        {"type": "browser.do", "task_id": "t1", "goal": "заполни форму", "start_url": "https://f.example/"},
        {"type": "browser.resume", "task_id": "t1"},
        {"type": "browser.cancel", "task_id": "t1"},
    ])
    asyncio.run(a._recv_loop())
    assert a.browser_agent.calls == [("start", "t1", "заполни форму", "https://f.example/"),
                                     ("resume", "t1", False), ("cancel", "t1")]


def test_browser_do_as_command_acks_with_command_result():
    a = _agent([{"type": "command", "id": "c1", "action": "browser.do",
                 "arg": json.dumps({"task_id": "t2", "goal": "пройди тест"})}])
    asyncio.run(a._recv_loop())
    assert a.browser_agent.calls == [("start", "t2", "пройди тест", None)]
    res = [m for m in a._ws.sent if m["type"] == "command_result"]
    assert res[0]["id"] == "c1" and res[0]["status"] == "done"


def test_browser_do_refused_for_non_master_and_without_task_id():
    a = _agent(master=False)
    assert a._browser_message("browser.do", {"task_id": "t", "goal": "g"})["status"] == "unsupported"
    assert _agent()._browser_message("browser.do", {"goal": "g"})["status"] == "failed"
    assert a.browser_agent.calls == []


def test_abort_all_cancels_browser_tasks():
    a = _agent([{"type": "command", "id": "c1", "action": "abort_all"}])
    asyncio.run(a._recv_loop())
    assert ("cancel_all",) in a.browser_agent.calls


def test_browser_agent_needs_server_link():
    a = _agent()
    a.browser_agent = None
    a.server_link = None
    assert a._browser_message("browser.do", {"task_id": "t"})["status"] == "unsupported"


def test_real_browser_agent_is_built_lazily(monkeypatch):
    a = _agent()
    a.browser_agent = None
    a.uploads = None
    ba = a._browser()
    assert ba is a._browser()
    assert a.uploads is not None


@pytest.mark.parametrize("action", ["ext:js_exec:alert(1)", "ext:js_exec_url:example.com"])
def test_js_exec_not_forwarded(monkeypatch, action):
    sent = []

    async def send_command(*a, **k):
        sent.append(a)
        return {"ok": True}

    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: True, send_command=send_command))
    a = _agent()
    asyncio.run(a._run_command(action, "c1"))
    res = [m for m in a._ws.sent if m["type"] == "command_result"][0]
    assert res["status"] == "unsupported" and "JS" in res["detail"]
    assert sent == []


def test_ext_agent_action_passthrough_with_json_args(monkeypatch):
    calls = []

    async def send_command(action, arg="", timeout=8.0, args=None):
        calls.append((action, args))
        return {"ok": True, "status": "done", "detail": "2 вкладки", "data": [{"tab_id": 1}], "observe": {"x": 1}}

    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: True, send_command=send_command))
    a = _agent()
    asyncio.run(a._run_command("ext:tabs.list", "c1"))
    asyncio.run(a._run_command('ext:page.act:{"tab_id": 3, "ref": "f0:e1", "op": "click"}', "c2"))
    asyncio.run(a._run_command("ext:page.act:not-json", "c3"))
    assert calls == [("tabs.list", {}), ("page.act", {"tab_id": 3, "ref": "f0:e1", "op": "click"})]
    r1, r2, r3 = [m for m in a._ws.sent if m["type"] == "command_result"]
    assert r1["status"] == "done" and r1["detail"] == "2 вкладки" and r1["ext"]["data"] == [{"tab_id": 1}]
    assert "observe" not in r2["ext"]
    assert r3["status"] == "failed"


def test_ext_agent_action_status_mapping(monkeypatch):
    async def send_command(action, arg="", timeout=8.0, args=None):
        return {"ok": False, "status": "stale", "detail": "снимок устарел"}

    monkeypatch.setitem(sys.modules, "desktop.core.extension_server",
                        SimpleNamespace(is_connected=lambda: True, send_command=send_command))
    res, raw = asyncio.run(browser.ext_agent_action("page.act", {}))
    assert res == {"ok": False, "status": "failed", "detail": "снимок устарел"}
    assert raw["status"] == "stale"
    res, _ = asyncio.run(browser.ext_agent_action("js_exec", {}))
    assert res["status"] == "unsupported"


def test_browser_tabs_list_in_command_pack():
    from desktop.core import hands
    hands._command_registry = None
    m = hands.match_voice_command("какие вкладки открыты")
    assert m and m["command_id"] == "browser_tabs_list" and (m["action"], m["args"]) == ("ext", "tabs.list")


# ── extension_server ────────────────────────────────────────────────

def _ext_server():
    spec = importlib.util.spec_from_file_location("extension_server_wiring", CORE / "extension_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ExtSocket:
    """Сокет расширения: Origin, входящие сообщения по очереди, исходящие — в sent."""

    def __init__(self, incoming, origin="chrome-extension://abcdefghijklmnopabcdefghijklmnop"):
        self.request = SimpleNamespace(headers={"Origin": origin})
        self.incoming = asyncio.Queue()
        for m in incoming:
            self.incoming.put_nowait(m)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self.incoming.get()
        if m is None:
            raise StopAsyncIteration
        return json.dumps(m)

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def close(self, *a, **k):
        pass


def test_extension_server_status_args_and_upload(monkeypatch, tmp_path):
    from desktop.core.upload_store import UploadStore

    monkeypatch.delenv("SAKURA_EXTENSION_ID", raising=False)
    mod = _ext_server()
    folder = tmp_path / "up"
    folder.mkdir()
    (folder / "a.txt").write_bytes(b"hello")
    store = UploadStore(str(folder))
    token = store.issue("a.txt")
    mod.set_upload_store(store)
    notified = []
    mod.set_status_listener(lambda: notified.append(mod.get_status()["version"]))

    async def scenario():
        ws = ExtSocket([{"type": "extension_ready", "version": "3.2.0"},
                        {"type": "upload_fetch", "id": "u1", "file_token": token},
                        {"type": "upload_fetch", "id": "u2", "file_token": token}])
        handler = asyncio.ensure_future(mod._handler(ws))
        for _ in range(20):
            await asyncio.sleep(0.01)
        st = mod.get_status()
        # Команда с args — в том же цикле; ответ расширения разрешает ожидание.
        cmd = asyncio.ensure_future(mod.send_command("page.observe", "", timeout=2, args={"tab_id": 5}))
        for _ in range(10):
            await asyncio.sleep(0.01)
        out = ws.sent[-1]
        await ws.incoming.put({"type": "extension_result", "id": out["id"], "result": {"ok": True, "status": "done"}})
        result = await cmd
        await ws.incoming.put(None)
        await handler
        return ws, st, out, result

    ws, st, out, result = asyncio.run(scenario())
    assert st == {"connected": True, "pending": 0, "version": "3.2.0",
                  "extension_id": "abcdefghijklmnopabcdefghijklmnop"}
    assert ws.sent[0]["type"] == "sakura_hello"
    # Два запроса одного токена обрабатываются параллельно: файл получает ровно один.
    ups = [m for m in ws.sent if m.get("type") == "upload_data"]
    good = [m for m in ups if m["ok"]]
    bad = [m for m in ups if not m["ok"]]
    assert len(good) == 1 and len(bad) == 1
    assert {k: v for k, v in good[0].items() if k != "id"} == {
        "type": "upload_data", "ok": True, "name": "a.txt", "mime": "text/plain", "size": 5, "data_b64": "aGVsbG8="}
    assert "недействителен" in bad[0]["error"]   # токен одноразовый
    assert out["action"] == "page.observe" and out["args"] == {"tab_id": 5}
    assert result == {"ok": True, "status": "done"}
    assert notified[-1] is None and "3.2.0" in notified    # подключение, версия, отключение
    assert mod.is_connected() is False and mod.get_status()["version"] is None
    assert not hasattr(mod, "send_command_with_code")


def test_upload_fetch_without_store_is_refused(monkeypatch):
    monkeypatch.delenv("SAKURA_EXTENSION_ID", raising=False)
    mod = _ext_server()

    async def scenario():
        ws = ExtSocket([{"type": "upload_fetch", "id": "u1", "file_token": "x"}])
        h = asyncio.ensure_future(mod._handler(ws))
        for _ in range(10):
            await asyncio.sleep(0.01)
        await ws.incoming.put(None)
        await h
        return ws

    up = [m for m in asyncio.run(scenario()).sent if m.get("type") == "upload_data"][0]
    assert up["ok"] is False


# ── Настройки → «Расширение браузера» ──────────────────────────────

def test_extension_keys_validation(tmp_path):
    from desktop.core import envfile as E

    env = tmp_path / ".env"
    env.write_text("WS_TOKEN=x\n", encoding="utf-8")
    E.set_secret(str(env), "SAKURA_EXTENSION_ID", "abcdefghijklmnopabcdefghijklmnop")
    E.set_secret(str(env), "BROWSER_UPLOAD_DIR", str(tmp_path))
    E.set_secret(str(env), "SAKURA_EXTENSION_ID", "")   # снять закрепление
    text = env.read_text(encoding="utf-8")
    assert "SAKURA_EXTENSION_ID=\n" in text and f"BROWSER_UPLOAD_DIR={tmp_path}" in text
    for key, bad in (("SAKURA_EXTENSION_ID", "not-an-id"), ("BROWSER_UPLOAD_DIR", "relative\\dir"),
                     ("BROWSER_UPLOAD_DIR", str(tmp_path / "missing"))):
        with pytest.raises(E.SecretError):
            E.set_secret(str(env), key, bad)
    with pytest.raises(E.SecretError):
        E.set_secret(str(env), "DEVICE_ID", "")   # пустое — только для ключей расширения


class ResumeBA(FakeBA):
    def __init__(self, paused=()):
        super().__init__()
        self.tasks = {t: object() for t in paused}

    def start(self, task_id, goal, start_url=None, step=1):
        self.calls.append(("start", task_id, goal, start_url, step))
        return True


def test_browser_do_resume_paused_task_resumes_without_echo():
    a = _agent([{"type": "browser.do", "task_id": "t1", "goal": "g", "resume": True}])
    a.browser_agent = ResumeBA(paused=["t1"])
    asyncio.run(a._recv_loop())
    assert a.browser_agent.calls == [("resume", "t1", False)]


def test_browser_do_resume_unknown_task_restarts_at_step_zero():
    a = _agent([{"type": "browser.do", "task_id": "t9", "goal": "пройди тест", "resume": True}])
    a.browser_agent = ResumeBA()
    asyncio.run(a._recv_loop())
    assert a.browser_agent.calls == [("start", "t9", "пройди тест", None, 0)]
    assert a._browser_message("browser.do", {"task_id": "t9", "goal": "g"})["status"] == "done"
    assert a.browser_agent.calls[-1] == ("start", "t9", "g", None, 1)


def test_step_timeout_passed_to_server_request(monkeypatch):
    from desktop.core import config
    seen = {}

    async def request(msg, timeout=None):
        seen["timeout"] = timeout
        return {}

    monkeypatch.setattr(config, "BROWSER_STEP_TIMEOUT", 360.0)
    a = _agent()
    a.browser_agent = None
    a.uploads = None
    a.server_link = SimpleNamespace(handle=lambda d: False, master=True, online=True, request=request)
    ba = a._browser()
    asyncio.run(ba._request({"type": "browser_step"}))
    assert seen["timeout"] == 360.0
