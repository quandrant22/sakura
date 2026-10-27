"""Цикл задачи агента браузера (desktop.core.browser_agent) с моками сервера и расширения:
полный цикл, paused/resume, wait, cancel, восстановление после обрыва связи и выгрузки
service worker, загрузка файла по токену, кадры вопросов."""
import asyncio
import copy

import pytest

from desktop.core import browser_agent as BA
from desktop.core.api.server import ApiError
from desktop.core.upload_store import UploadStore


class FakeExt:
    """Расширение: окно агента 7, вкладка 11; снимки s1, s2, …; кадр — «QUJD»."""

    def __init__(self):
        self.connected = True
        self.calls = []
        self.snap = 0
        self.script = {}          # action → список ответов (первые вызовы), дальше — по умолчанию

    async def __call__(self, action, args, timeout):
        self.calls.append((action, copy.deepcopy(args)))
        if not self.connected:
            return {"ok": False, "error": "Расширение не подключено"}
        queue = self.script.get(action)
        if queue:
            r = queue.pop(0)
            return r() if callable(r) else r
        return self.default(action, args)

    def observation(self):
        self.snap += 1
        return {"snapshot_id": f"s{self.snap}", "window_id": 7, "tab_id": 11, "elements": [], "text": "стр"}

    def default(self, action, args):
        ok = {"ok": True, "status": "done", "detail": ""}
        if action == "agent_window.open":
            return {**ok, "data": {"window_id": 7, "tab_id": 11}}
        if action == "page.observe":
            return {**ok, "data": self.observation()}
        if action == "page.shot":
            return {**ok, "data": {"mime": "image/jpeg", "data_b64": "QUJD", "width": 10, "height": 10, "bytes": 3}}
        if action in ("page.act", "page.fill_form", "page.upload", "page.scroll"):
            return {**ok, "detail": "сделано", "observe": self.observation()}
        if action == "tabs.new":
            return {**ok, "data": {"tab_id": 12, "window_id": 7}}
        if action == "tabs.list":
            return {**ok, "data": [{"tab_id": 11, "window_id": 7, "active": True}]}
        return ok

    def actions(self):
        return [a for a, _ in self.calls]


class FakeServer:
    """Сервер: на каждый browser_step — следующий ответ из сценария (dict, исключение или Future)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.steps = []
        self.sent = []
        self.online = True

    async def request(self, msg):
        self.steps.append(copy.deepcopy(msg))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, asyncio.Future):
            return await r
        return r

    async def send(self, msg):
        self.sent.append(msg)


def make(replies, ext=None, uploads=None, step_shot=True):
    ext = ext or FakeExt()
    server = FakeServer(replies)
    events, sleeps = [], []

    async def sleep(s):
        sleeps.append(s)
        await asyncio.sleep(0)

    agent = BA.BrowserAgent(request=server.request, send=server.send, ext=ext,
                            ext_connected=lambda: ext.connected, online=lambda: server.online,
                            uploads=uploads, emit=events.append, sleep=sleep, step_shot=step_shot)
    return agent, server, ext, events, sleeps


def act(tool, **args):
    return {"type": "browser_step", "action": {"tool": tool, "args": args}}


def run(coro):
    return asyncio.run(coro)


def test_full_cycle_until_done():
    async def scenario():
        agent, server, ext, events, _ = make([
            act("page_act", ref="f0:e3", action="click"),
            act("page_fill_form", fields=[{"ref": "f0:e5", "value": "Анна"}]),
            {"type": "browser_step", "status": "done", "summary": "форма отправлена"},
        ])
        assert agent.start("t1", "заполни анкету", "https://forms.example/")
        await agent.wait("t1")
        return server, ext, events, agent

    server, ext, events, agent = run(scenario())
    assert ext.calls[0] == ("agent_window.open", {"url": "https://forms.example/"})
    s1, s2, s3 = server.steps
    assert [s["step"] for s in server.steps] == [1, 2, 3]
    assert s1["type"] == "browser_step" and s1["task_id"] == "t1"
    assert "last_result" not in s1
    assert s1["observation"]["snapshot_id"] == "s1"
    assert s1["frames"] == [{"frame_id": "s1f1", "kind": "page", "mime": "image/jpeg", "data_b64": "QUJD"}]
    # Результат действия — без observe; observe уходит как observation следующего шага.
    assert s2["last_result"] == {"ok": True, "status": "done", "detail": "сделано"}
    assert s2["observation"]["snapshot_id"] == "s2"
    # Аргументы — по схеме сервера; snapshot_id — из последнего observation (адаптер).
    assert ("page.act", {"tab_id": 11, "snapshot_id": "s1", "ref": "f0:e3", "op": "click"}) in ext.calls
    assert ("page.fill_form", {"tab_id": 11, "snapshot_id": "s2", "values": {"f0:e5": "Анна"}}) in ext.calls
    assert s3["observation"]["snapshot_id"] == "s3"
    # Шот — окна агента по window_id (без активации вкладки).
    assert ("page.shot", {"window_id": 7, "mode": "plain"}) in ext.calls
    assert events[0]["state"] == "running"
    assert events[-1] == {"type": "browser_task", "task_id": "t1", "state": "done", "text": "форма отправлена",
                          "window_id": 7}
    assert agent.tasks == {}


def test_done_and_fail_as_tools_and_nested_status():
    done = BA.parse_reply({"action": {"tool": "done", "args": {"summary": "ок"}}})
    assert done == ("done", {"summary": "ок", "reason": ""})
    wait = BA.parse_reply({"status": {"type": "wait", "retry_after": 4}})
    assert wait == ("wait", {"type": "wait", "retry_after": 4})
    assert BA.parse_reply({"status": {"paused": {"reason": "капча"}}}) == ("paused", {"reason": "капча"})
    assert BA.parse_reply({"status": "fail", "reason": "нет доступа"})[0] == "fail"
    assert BA.parse_reply({})[0] == "unknown"

    async def scenario():
        agent, server, _, events, _ = make([act("fail", reason="сайт недоступен")])
        agent.start("t2", "цель")
        await agent.wait("t2")
        return events

    assert run(scenario())[-1]["state"] == "fail"


def test_wait_retry_after_resends_same_step():
    async def scenario():
        agent, server, ext, _, sleeps = make([
            {"status": "wait", "retry_after": 3},
            {"status": "done", "summary": ""},
        ])
        agent.start("t3", "цель")
        await agent.wait("t3")
        return server, ext, sleeps

    server, ext, sleeps = run(scenario())
    assert 3.0 in sleeps
    assert [s["step"] for s in server.steps] == [1, 1]
    # После ожидания — свежий снимок.
    assert [s["observation"]["snapshot_id"] for s in server.steps] == ["s1", "s2"]


def test_paused_waits_for_local_resume_and_reports_to_server():
    async def scenario():
        agent, server, ext, events, _ = make([
            {"status": "paused", "reason": "капча"},
            {"status": "done", "summary": "готово"},
        ])
        agent.start("t4", "цель")
        for _ in range(50):
            await asyncio.sleep(0)
        paused = [e for e in events if e["state"] == "paused"]
        assert paused and paused[0]["text"] == "капча"
        assert len(server.steps) == 1 and agent.tasks["t4"].paused
        assert not agent.resume("other")
        assert agent.resume("t4", local=True)
        await agent.wait("t4")
        return server, events

    server, events = run(scenario())
    assert server.sent == [{"type": "browser.resume", "task_id": "t4"}]
    step2 = server.steps[1]
    assert step2["step"] == 1
    assert step2["last_result"]["detail"] == "Мастер продолжил задачу"
    assert step2["observation"]["snapshot_id"] == "s2"   # продолжение с page.observe
    assert events[-1]["state"] == "done"


def test_resume_from_server_does_not_echo():
    async def scenario():
        agent, server, _, _, _ = make([{"status": "paused", "reason": ""}, {"status": "done"}])
        agent.start("t5", "цель")
        for _ in range(50):
            await asyncio.sleep(0)
        assert agent.resume("t5", local=False)
        await agent.wait("t5")
        return server

    assert run(scenario()).sent == []


def test_cancel_stops_pending_step():
    async def scenario():
        loop = asyncio.get_running_loop()
        never = loop.create_future()
        agent, server, ext, events, _ = make([never])
        agent.start("t6", "цель")
        for _ in range(20):
            await asyncio.sleep(0)
        assert len(server.steps) == 1
        assert agent.cancel("t6")
        await agent.wait("t6")
        assert not agent.cancel("t6")
        return server, ext, events, agent

    server, ext, events, agent = run(scenario())
    assert events[-1]["state"] == "cancelled"
    assert len(server.steps) == 1
    assert "page.act" not in ext.actions()
    assert agent.tasks == {}


def test_reconnect_after_server_drop_continues_with_observe():
    async def scenario():
        agent, server, ext, _, sleeps = make([
            ApiError("offline", "нет связи с сервером"),
            act("page_scroll", dy=500),
            {"status": "done"},
        ])
        polls = {"n": 0}

        def online():
            polls["n"] += 1
            return polls["n"] > 3

        agent._online = online
        agent.start("t7", "цель")
        await agent.wait("t7")
        return server, ext, sleeps

    server, ext, sleeps = run(scenario())
    assert [s["step"] for s in server.steps] == [1, 1, 2]
    assert [s["observation"]["snapshot_id"] for s in server.steps[:2]] == ["s1", "s2"]  # заново page.observe
    assert sleeps.count(BA.POLL) == 3


def test_server_timeout_retries_then_gives_up():
    async def scenario():
        agent, server, _, events, _ = make([ApiError("timeout", "нет ответа")] * BA.MAX_FAILURES)
        agent.start("t8", "цель")
        await agent.wait("t8")
        return server, events

    server, events = run(scenario())
    assert len(server.steps) == BA.MAX_FAILURES
    assert events[-1]["state"] == "fail" and "не отвечает" in events[-1]["text"]


def test_not_master_error_ends_task():
    async def scenario():
        agent, server, _, events, _ = make([ApiError("not_master", "только master")])
        agent.start("t9", "цель")
        await agent.wait("t9")
        return events

    assert "not_master" in run(scenario())[-1]["text"]


def test_service_worker_unload_waits_for_extension_and_retries():
    async def scenario():
        ext = FakeExt()
        polls = {"n": 0}

        def down_then_up():
            ext.connected = False
            return {"ok": False, "error": "Расширение не подключено"}

        ext.script["page.act"] = [down_then_up]
        agent, server, _, _, sleeps = make([act("page_act", ref="f0:e1", action="click"),
                                            {"status": "done"}], ext=ext)

        def connected():
            polls["n"] += 1
            if polls["n"] > 2:
                ext.connected = True
            return ext.connected

        agent._ext_connected = connected
        agent.start("t10", "цель")
        await agent.wait("t10")
        return server, ext

    server, ext = run(scenario())
    assert ext.actions().count("page.act") == 2       # команда не ушла — повтор после переподключения
    assert server.steps[1]["last_result"]["status"] == "done"


def test_extension_timeout_on_action_is_not_repeated():
    async def scenario():
        ext = FakeExt()
        ext.script["page.act"] = [{"ok": False, "error": "Тайм-аут расширения"}]
        agent, server, _, _, _ = make([act("page_act", ref="f0:e1", action="click"),
                                       {"status": "done"}], ext=ext)
        agent.start("t11", "цель")
        await agent.wait("t11")
        return server, ext

    server, ext = run(scenario())
    assert ext.actions().count("page.act") == 1
    lr = server.steps[1]["last_result"]
    assert lr["status"] == "error" and "могло не выполниться" in lr["detail"]
    assert server.steps[1]["observation"]["snapshot_id"] == "s2"   # продолжение с page.observe


def test_extension_never_returns_reports_to_server():
    async def scenario():
        ext = FakeExt()
        ext.connected = False
        agent, server, _, _, _ = make([{"status": "fail", "reason": "нет расширения"}], ext=ext)
        agent._ext_wait = 0
        agent.start("t12", "цель")
        await agent.wait("t12")
        return server

    step = run(scenario()).steps[0]
    assert step["observation"] is None
    assert step["last_result"]["ok"] is False and "окно агента не открыто" in step["last_result"]["detail"]


def test_upload_token_only_inside_folder(tmp_path):
    folder = tmp_path / "uploads"
    folder.mkdir()
    (folder / "cv.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.txt").write_text("x")
    store = UploadStore(str(folder))

    async def scenario():
        agent, server, ext, _, _ = make([
            act("page_upload", ref="f0:e4", file="cv.pdf"),
            act("page_upload", ref="f0:e4", file=str(tmp_path / "secret.txt")),
            {"status": "done"},
        ], uploads=store)
        agent.start("t13", "цель")
        await agent.wait("t13")
        return server, ext

    server, ext = run(scenario())
    uploads = [a for a in ext.calls if a[0] == "page.upload"]
    assert len(uploads) == 1
    token = uploads[0][1]["file_token"]
    assert "file" not in uploads[0][1] and uploads[0][1]["ref"] == "f0:e4"
    assert store.take(token)["name"] == "cv.pdf"
    refused = server.steps[2]["last_result"]
    assert refused["status"] == "error" and "вне папки" in refused["detail"]


def test_upload_without_folder_is_unsupported():
    async def scenario():
        agent, server, ext, _, _ = make([act("page_upload", ref="f0:e4", file="a.txt"), {"status": "done"}])
        agent.start("t14", "цель")
        await agent.wait("t14")
        return server, ext

    server, ext = run(scenario())
    assert server.steps[1]["last_result"]["status"] == "unsupported"
    assert "page.upload" not in ext.actions()


def test_questions_with_media_add_cropped_frames_and_shot_bytes_not_in_result():
    async def scenario():
        ext = FakeExt()
        ext.script["page.questions"] = [{"ok": True, "status": "done", "detail": "3 вопроса", "data": {"questions": [
            {"q_ref": "f0:e1", "index": 1, "has_media": True},
            {"q_ref": "f0:e2", "index": 2, "has_media": False},
            {"q_ref": "f0:e3", "index": 3, "has_media": True},
        ]}}]
        agent, server, _, _, _ = make([act("page_questions"), act("page_shot", mode="annotated"),
                                       {"status": "done"}], ext=ext)
        agent.start("t15", "цель")
        await agent.wait("t15")
        return server, ext

    server, ext = run(scenario())
    frames = server.steps[1]["frames"]
    assert [(f["kind"], f.get("q_index")) for f in frames] == [("question", 1), ("question", 3), ("page", None)]
    assert [f["frame_id"] for f in frames] == ["s2f1", "s2f2", "s2f3"]
    assert ("page.shot", {"tab_id": 11, "crop_ref": "f0:e1"}) in ext.calls
    shot = server.steps[2]["last_result"]
    assert "data_b64" not in shot["data"] and shot["data"]["width"] == 10
    assert [f["kind"] for f in server.steps[2]["frames"]] == ["page", "page"]


def test_tabs_new_switches_current_tab_and_unknown_tool():
    async def scenario():
        agent, server, ext, _, _ = make([act("tabs_new", url="https://b.example/"), act("page_observe"),
                                         act("rm_rf"), {"status": "done"}], step_shot=False)
        agent.start("t16", "цель")
        await agent.wait("t16")
        return server, ext

    server, ext = run(scenario())
    assert ("tabs.new", {"url": "https://b.example/", "window_id": 7, "active": True}) in ext.calls
    assert ("page.observe", {"tab_id": 12}) in ext.calls
    assert server.steps[3]["last_result"]["status"] == "unsupported"
    assert all(s["frames"] == [] for s in server.steps)


def test_duplicate_task_id_rejected():
    async def scenario():
        loop = asyncio.get_running_loop()
        agent, _, _, _, _ = make([loop.create_future()])
        assert agent.start("t17", "a")
        assert not agent.start("t17", "b")
        assert not agent.start("", "c")
        agent.cancel_all()
        await agent.wait("t17")

    run(scenario())


@pytest.mark.parametrize("retry_after,expected", [(None, 1.0), (0, 1.0), (10_000, 600.0)])
def test_wait_bounds(retry_after, expected):
    async def scenario():
        agent, _, _, _, sleeps = make([{"status": "wait", "retry_after": retry_after}, {"status": "done"}])
        agent.start("t18", "цель")
        await agent.wait("t18")
        return sleeps

    assert expected in run(scenario())


def test_fill_form_with_submit_ref_is_one_step_result():
    async def scenario():
        ext = FakeExt()
        agent, server, _, _, _ = make([
            act("page_fill_form", fields=[{"ref": "f0:e5", "value": "Анна"}, {"ref": "f0:e6", "checked": True}],
                submit_ref="f0:e9"),
            {"status": "done"},
        ], ext=ext)
        agent.start("t20", "цель")
        await agent.wait("t20")
        return server, ext

    server, ext = run(scenario())
    acts = [c for c in ext.calls if c[0] in ("page.fill_form", "page.act")]
    assert acts == [
        ("page.fill_form", {"tab_id": 11, "snapshot_id": "s1", "values": {"f0:e5": "Анна", "f0:e6": True}}),
        # клик по кнопке — в снимке после заполнения (s2)
        ("page.act", {"tab_id": 11, "snapshot_id": "s2", "ref": "f0:e9", "op": "click"}),
    ]
    assert len(server.steps) == 2                       # один результат шага на оба действия
    lr = server.steps[1]["last_result"]
    assert lr["status"] == "done" and "отправка" in lr["detail"]
    assert server.steps[1]["observation"]["snapshot_id"] == "s3"


def test_fill_form_failed_does_not_submit():
    async def scenario():
        ext = FakeExt()
        ext.script["page.fill_form"] = [{"ok": False, "status": "stale", "detail": "снимок устарел"}]
        agent, server, _, _, _ = make([
            act("page_fill_form", fields=[{"ref": "f0:e5", "value": "x"}], submit_ref="f0:e9"),
            {"status": "done"},
        ], ext=ext)
        agent.start("t21", "цель")
        await agent.wait("t21")
        return server, ext

    server, ext = run(scenario())
    assert "page.act" not in ext.actions()
    assert server.steps[1]["last_result"]["status"] == "stale"


def test_adapter_error_becomes_step_result_without_extension_call():
    async def scenario():
        agent, server, ext, _, _ = make([act("page_act", ref="f0:e1", action="type"), {"status": "done"}])
        agent.start("t22", "цель")
        await agent.wait("t22")
        return server, ext

    server, ext = run(scenario())
    assert "page.act" not in ext.actions()
    assert server.steps[1]["last_result"] == {"ok": False, "status": "error", "detail": "нет аргумента: text"}


def test_questions_moved_to_last_result_in_server_form():
    async def scenario():
        ext = FakeExt()
        ext.script["page.questions"] = [{"ok": True, "status": "done", "detail": "1 вопрос", "data": {
            "snapshot_id": "s7", "questions": [
                {"q_ref": "f0:e1", "index": 1, "kind": "text", "input_ref": "f0:e2", "options": [],
                 "has_media": False}]}}]
        agent, server, _, _, _ = make([act("page_questions"),
                                       act("page_fill_form", fields=[{"ref": "f0:e2", "value": "Париж"}]),
                                       {"status": "done"}], ext=ext)
        agent.start("t23", "цель")
        await agent.wait("t23")
        return server, ext

    server, ext = run(scenario())
    lr = server.steps[1]["last_result"]
    assert lr["questions"][0]["ref"] == "f0:e2" and lr["questions"][0]["index"] == 1
    assert "questions" not in lr["data"] and lr["data"]["snapshot_id"] == "s7"
    # snapshot_id — из последнего observation (после page_questions цикл снял страницу заново: s2).
    assert ("page.fill_form", {"tab_id": 11, "snapshot_id": "s2", "values": {"f0:e2": "Париж"}}) in ext.calls


def test_resumed_task_starts_at_step_zero_with_observe():
    async def scenario():
        agent, server, ext, _, _ = make([{"status": "done"}])
        assert agent.start("t24", "цель", step=0)
        await agent.wait("t24")
        return server, ext

    server, ext = run(scenario())
    assert server.steps[0]["step"] == 0
    assert server.steps[0]["observation"]["snapshot_id"] == "s1"
    assert ext.actions()[:2] == ["agent_window.open", "page.observe"]


def test_step_timeout_from_setting(monkeypatch):
    import importlib

    from desktop.core import config
    monkeypatch.setenv("BROWSER_STEP_TIMEOUT", "42")
    monkeypatch.setenv("SAKURA_NO_DOTENV", "1")
    try:
        assert importlib.reload(config).BROWSER_STEP_TIMEOUT == 42.0
        monkeypatch.delenv("BROWSER_STEP_TIMEOUT")
        assert importlib.reload(config).BROWSER_STEP_TIMEOUT == 360.0
    finally:
        importlib.reload(config)
    assert BA.STEP_TIMEOUT == 360.0


def test_server_arg_q_index_makes_question_frame():
    """server_args схемы: page_shot.q_index — кадр-вырезка вопроса с его номером."""
    async def scenario():
        agent, server, ext, _, _ = make([act("page_shot", crop_ref="f0:e4", q_index=2, note="вопрос 2"),
                                         {"status": "done"}])
        agent.start("t30", "цель")
        await agent.wait("t30")
        return server, ext

    server, ext = run(scenario())
    assert ("page.shot", {"tab_id": 11, "crop_ref": "f0:e4", "snapshot_id": "s1"}) in ext.calls
    assert [(f["kind"], f.get("q_index")) for f in server.steps[1]["frames"]] == [("question", 2), ("page", None)]


def test_fill_form_pairs_from_questions_rows():
    """rows вопроса → пары сервера → values расширения; снимок — последний observation (ref строк
    расширение переносит между снимками, DECISIONS №80)."""
    async def scenario():
        ext = FakeExt()
        ext.script["page.questions"] = [{"ok": True, "status": "done", "detail": "1 вопрос", "data": {
            "snapshot_id": "s7", "questions": [{"q_ref": "f0:e1", "index": 1, "kind": "match", "text": "?",
                                                "rows": [{"row_ref": "f0:e2", "text": "Италия"}],
                                                "options": [{"text": "Рим"}]}]}}]
        agent, server, _, _, _ = make([
            act("page_questions"),
            act("page_fill_form", fields=[{"ref": "f0:e1", "kind": "match",
                                           "pairs": [{"row_ref": "f0:e2", "option_text": "Рим"}]}]),
            {"status": "done"},
        ], ext=ext)
        agent.start("t31", "цель")
        await agent.wait("t31")
        return server, ext

    server, ext = run(scenario())
    q = server.steps[1]["last_result"]["questions"][0]
    assert q["rows"] == [{"row_ref": "f0:e2", "text": "Италия"}] and q["options"][0]["name"] == "Рим"
    assert ("page.fill_form", {"tab_id": 11, "snapshot_id": "s2", "values": {
        "f0:e1": {"kind": "match", "pairs": [{"row_ref": "f0:e2", "option_text": "Рим"}]}}}) in ext.calls
