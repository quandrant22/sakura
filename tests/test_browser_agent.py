"""server/browser-step: browser agent на сервере (S2–S10).

Run: python -m pytest tests/test_browser_agent.py -q
Модели — моки generate_agent / generate_raw: сеть не нужна.
"""

import asyncio
import base64
import json
import logging
from types import SimpleNamespace

import pytest

import config
from sakura_core import browser_step as bs
from sakura_core import browser_task as bt
from sakura_core import llm
from sakura_core import quiz_solver as qs
from sakura_core import rate_limiter as rl

JPEG = b"\xff\xd8\xff\xe0" + b"FRAMEBYTES" * 20
B64 = base64.b64encode(JPEG).decode()
PAGE_SECRET = "PAGE_TEXT_SECRET_42"


# ── инфраструктура ───────────────────────────────────────────────────

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


def fc(tool, note="делаю шаг", **args):
    if note is not None:
        args["note"] = note
    return SimpleNamespace(function_calls=[SimpleNamespace(name=tool, args=args)], text=None)


def text_resp(text):
    return SimpleNamespace(function_calls=None, text=text)


class FakeLLM:
    """generate_agent: навигатор (tools), сводка (без tools), решатель (schema)."""

    def __init__(self, nav=None, summary="сводка шагов", solve=None):
        self.nav = list(nav or [])
        self.default_nav = fc("page_scroll", direction="down")
        self.summary = summary
        self.solve = list(solve or [])
        self.calls = []

    async def __call__(self, contents, **kw):
        self.calls.append((contents, kw))
        if kw.get("tools") is not None:
            item = self.nav.pop(0) if self.nav else self.default_nav
        elif kw.get("response_schema") is not None:
            item = self.solve.pop(0)
        else:
            item = text_resp(self.summary)
        if isinstance(item, Exception):
            raise item
        return llm.AgentResponse("gemma-test", item, 10)

    def kinds(self):
        return ["nav" if kw.get("tools") is not None else
                "solve" if kw.get("response_schema") is not None else "summary"
                for _, kw in self.calls]

    def nav_requests(self):
        return [c for c, kw in self.calls if kw.get("tools") is not None]


def request_text(parts) -> str:
    return "\n".join(p.text for p in parts if getattr(p, "text", None))


def images(parts) -> int:
    return sum(1 for p in parts if getattr(p, "inline_data", None) is not None)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "TASKS_DIR", tmp_path / "browser_tasks")
    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    monkeypatch.setattr(config, "BROWSER_CONFIRM_SENSITIVE", False)
    monkeypatch.setattr(config, "BROWSER_SUMMARIZE_EVERY", 0)
    monkeypatch.setattr(config, "BROWSER_MAX_STEPS", 200)
    monkeypatch.setattr(config, "BROWSER_MAX_SECONDS", 1800)
    monkeypatch.setattr(config, "BROWSER_MAX_TOKENS", 0)
    monkeypatch.setattr(config, "BROWSER_FRAMES_IN_CONTEXT", 3)
    monkeypatch.setattr(rl, "_limiter", rl.RateLimiter(path=None))
    import modules.ws_auth as wa
    monkeypatch.setattr(wa, "is_master_device", lambda d: True)
    bt.reset()
    notes = SimpleNamespace(tg=[], orb=[])

    async def tg_send(text):
        notes.tg.append(text)
        return SimpleNamespace(message_id=1)

    async def tg_edit(msg, text):
        notes.tg.append(text)
        return True

    async def orb(text):
        notes.orb.append(text)

    monkeypatch.setattr(bs, "tg_send", tg_send)
    monkeypatch.setattr(bs, "tg_edit", tg_edit)
    monkeypatch.setattr(bs, "orb", orb)
    monkeypatch.setattr(bs, "_loaded", True)
    yield notes
    bt.reset()
    bs._locks.clear()


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "generate_agent", f)
    return f


def element(n, role="button", name=None, **kw):
    return {"ref": f"f0:e{n}", "role": role, "name": name or f"кнопка {n}",
            "value": "", "enabled": True, "in_viewport": True, "bbox": [0, 0, 1, 1], **kw}


def obs(url="https://ex.com/a", elements=None, **kw):
    return {"snapshot_id": "s1", "window_id": 7, "tab_id": 3, "url": url, "title": "T",
            "elements": elements if elements is not None else [element(i) for i in range(1, 7)],
            "text": PAGE_SECRET, "has_canvas": False, "has_video": False,
            "cross_origin_frames": 0, "captcha_detected": False, **kw}


def frame(kind="page", q_index=None, fid="fr"):
    out = {"frame_id": fid, "kind": kind, "mime": "image/jpeg", "data_b64": B64}
    if q_index is not None:
        out["q_index"] = q_index
    return out


class Desk:
    """Desktop: шлёт шаги одной задачи и копит ответы."""

    def __init__(self, task):
        self.task = task
        self.ws = WS()
        self.n = 0

    async def step(self, observation=None, last_result=None, frames=None, step=None):
        self.n += 1
        data = {"type": "browser_step", "request_id": f"r{self.n}", "device_id": "pc",
                "task_id": self.task.task_id, "step": step if step is not None else self.n,
                "observation": observation if observation is not None else obs(),
                "frames": frames if frames is not None else []}
        if last_result is not None:
            data["last_result"] = last_result
        await bs.handle_step(self.ws, data)
        return self.ws.sent[-1]


def new_task(goal="заполни форму"):
    return bt.new_task(goal, device_id="pc")


OK = {"ok": True, "status": "done", "detail": ""}


def test_exhausted_chain_pauses_and_auto_resumes(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.nav = [llm.ChainExhausted(1_000.0)]               # время сброса в прошлом
    out = asyncio.run(desk.step())
    assert out["status"] == "paused" and "лимит Gemma" in out["reason"]
    assert any("Упёрлась в лимит Gemma, продолжу в" in t for t in env.tg)
    assert task.state == "paused" and task.pause_kind == "quota"
    asyncio.run(bs._auto_resume(task.task_id, 0))
    assert task.state == "running"
    assert desk.ws.sent[-1] == {"type": "browser.do", "task_id": task.task_id,
                                "goal": task.goal, "resume": True}


def test_quota_wait_reaches_desktop_and_step_is_not_counted_twice(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.nav = [llm.QuotaWait(12.2), fc("page_observe")]
    out = asyncio.run(desk.step(step=1))
    assert out == {"type": "browser_step", "request_id": "r1", "task_id": task.task_id,
                   "status": "wait", "retry_after": 13}
    out = asyncio.run(desk.step(step=1))                   # повтор того же шага
    assert out["action"]["tool"] == "page_observe" and task.step == 1


# ── S1: цепочки агента ──────────────────────────────────────────────

def test_agent_chains_are_gemma_only():
    assert config.BROWSER_MODEL_CHAIN == ("gemma-4-26b-a4b-it", "gemma-4-31b-it")
    assert config.QUIZ_MODEL_CHAIN == ("gemma-4-31b-it", "gemma-4-26b-a4b-it")
    assert config._gemma_only("X", ("gemma-4-31b-it", "gemini-3.5-flash-lite")) == ("gemma-4-31b-it",)


# ── S6: навигатор ────────────────────────────────────────────────────

def test_json_block_instead_of_function_call():
    resp = text_resp('Думаю…\n```json\n{"tool": "page_act", "args": {"ref": "f0:e1", '
                     '"action": "click"}, "note": "жму кнопку"}\n```')
    assert bs.parse_tool_call(resp) == ("page_act", {"ref": "f0:e1", "action": "click"}, "жму кнопку")
    resp = text_resp('{"tool": "page_observe", "args": {"note": "смотрю"}}')
    assert bs.parse_tool_call(resp) == ("page_observe", {}, "смотрю")
    assert bs.parse_tool_call(text_resp('{"tool": "rm_rf", "args": {}}')) is None


def test_note_required_one_retry_then_dash(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_observe", note=None), fc("page_observe", note="смотрю снова"),
                fc("page_forms", note=None), fc("page_forms", note=None)]
    asyncio.run(desk.step())
    assert task.steps[-1]["note"] == "смотрю снова"
    asyncio.run(desk.step(last_result=OK))
    assert task.steps[-1]["note"] == "—"
    assert fake.kinds() == ["nav"] * 4
    assert "не было note" in request_text(fake.nav_requests()[1])


def test_evicted_frame_replaced_by_its_note(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_observe", note=f"заметка {i}") for i in range(1, 6)]

    async def run():
        for i in range(1, 6):
            await desk.step(last_result=OK if i > 1 else None, frames=[frame(fid=f"f{i}")])
    asyncio.run(run())
    assert len(task.frames) == 3 and [f.step for f in task.frames] == [3, 4, 5]
    assert task.notes == {"1": "заметка 1", "2": "заметка 2"}
    last = fake.nav_requests()[-1]
    assert images(last) == 3
    assert "[кадр шага 2 выпал из окна: заметка 2]" in request_text(last)


def test_request_grows_only_by_journal(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.default_nav = fc("page_scroll", note="листаю дальше", direction="down")

    async def run():
        for i in range(1, 51):
            await desk.step(last_result=OK if i > 1 else None, frames=[frame(fid=f"f{i}")])
    asyncio.run(run())
    reqs = fake.nav_requests()
    assert len(reqs) == 50
    rest = []
    for i, parts in enumerate(reqs, 1):
        text = request_text(parts)
        journal = "\n".join(f"{s['n']}. {s['tool']} → {s['status']}: {s['note']}"
                            for s in task.steps[:i - 1])
        journal += "".join(f"\n   [кадр шага {n} выпал из окна: листаю дальше]"
                           for n in range(1, i - 2))
        rest.append(len(text) - len(journal))
        assert images(parts) == min(i, 3)
    assert max(rest[3:]) - min(rest[3:]) <= 6       # разница — только цифры номера шага


def test_summarize_on_step_15(env, fake, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_SUMMARIZE_EVERY", 15)
    task = new_task()
    desk = Desk(task)

    async def run():
        for i in range(1, 17):
            await desk.step(last_result=OK if i > 1 else None)
    asyncio.run(run())
    kinds = fake.kinds()
    assert kinds.count("summary") == 1 and kinds.index("summary") == 14
    assert task.summary == "сводка шагов" and task.summarized_upto == 14
    step15 = request_text(fake.nav_requests()[14])
    assert "Сводка прошлых шагов: сводка шагов" in step15
    assert "Журнал (шаг. инструмент → статус: заметка):\n—" in step15


def test_auto_shot_triggers(env):
    task = new_task()
    assert bs.need_shot(task, obs(), []) is None
    task.last_url = "https://ex.com/old"
    assert bs.need_shot(task, obs(), []) == "сменился адрес"
    task.last_url = "https://ex.com/a"
    task.stale_streak = 2
    assert bs.need_shot(task, obs(), []) == "два stale подряд"
    task.stale_streak = 0
    assert bs.need_shot(task, obs(elements=[element(1)]), []) == "мало элементов"
    for flag in ({"has_canvas": True}, {"has_video": True}, {"cross_origin_frames": 2}):
        assert bs.need_shot(task, obs(**flag), []) == "canvas/видео/чужие фреймы"
    page = bs.Frame(step=1, frame_id="x", kind="page", data=JPEG)
    assert bs.need_shot(task, obs(has_canvas=True), [page]) is None
    task.step = 1
    task.record("page_shot", "кадр")
    assert bs.need_shot(task, obs(has_canvas=True), []) is None   # не зацикливаться


def test_auto_shot_skips_model(env, fake):
    task = new_task()
    desk = Desk(task)

    async def run():
        await desk.step()
        return await desk.step(observation=obs(url="https://ex.com/b"), last_result=OK)
    out = asyncio.run(run())
    assert out["action"] == {"tool": "page_shot", "args": {}}
    assert fake.kinds() == ["nav"]


# ── S5: чекпоинт ─────────────────────────────────────────────────────

def test_checkpoint_without_frames_and_restore(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_observe", note="смотрю")]
    asyncio.run(desk.step(frames=[frame()]))
    path = bt.TASKS_DIR / f"{task.task_id}.json"
    raw = path.read_text(encoding="utf-8")
    assert B64[:40] not in raw and PAGE_SECRET not in raw and "frames" not in json.loads(raw)
    bt.reset()
    restored = bt.get(task.task_id)
    assert restored is not task and restored.step == 1 and restored.steps[0]["note"] == "смотрю"
    assert len(restored.frames) == 0
    desk.task = restored
    fake.nav = [fc("page_forms", note="формы")]
    out = asyncio.run(desk.step(last_result=OK))           # «переподключение»
    assert out["action"]["tool"] == "page_forms" and restored.step == 2
    assert restored.steps[0]["status"] == "done"


def test_new_task_in_same_window_cancels_old(env, fake):
    old, new = new_task("старая"), new_task("новая")
    d_old, d_new = Desk(old), Desk(new)
    d_new.ws = d_old.ws

    async def run():
        await d_old.step()
        await d_new.step()
    asyncio.run(run())
    assert old.state == "cancelled" and new.state == "running"
    assert {"type": "browser.cancel", "task_id": old.task_id} in d_old.ws.sent
    assert any("в том же окне" in t for t in env.tg)


# ── S7: решатель ─────────────────────────────────────────────────────

OPTS = [{"ref": "f0:e11", "name": "три"}, {"ref": "f0:e12", "name": "четыре"},
        {"ref": "f0:e13", "name": "пять"}]


@pytest.mark.parametrize("kind,answer,expected", [
    ("single", {"refs": ["f0:e12"]}, {"refs": ["f0:e12"]}),
    ("select", {"refs": ["f0:e12"]}, {"refs": ["f0:e12"]}),
    ("multi", {"refs": ["f0:e11", "f0:e13", "f0:e99"]}, {"refs": ["f0:e11", "f0:e13"]}),
    ("order", {"order": ["f0:e13", "f0:e11", "f0:e12"]}, {"order": ["f0:e13", "f0:e11", "f0:e12"]}),
    ("text", {"text": " Москва "}, {"text": "Москва"}),
    ("number", {"text": "4"}, {"text": "4"}),
])
def test_solver_all_kinds(monkeypatch, kind, answer, expected):
    f = FakeLLM(solve=[text_resp(json.dumps({"reasoning": "потому что", "answer": answer}))])
    monkeypatch.setattr(llm, "generate_agent", f)
    q = {"index": 1, "kind": kind, "text": "вопрос", "ref": "f0:e10",
         "options": OPTS if kind not in ("text", "number") else []}
    res = asyncio.run(qs.solve(q))
    assert res["answer"] == expected and res["reasoning"] == "потому что"
    kw = f.calls[0][1]
    assert kw["chain"] == config.QUIZ_MODEL_CHAIN and kw["response_schema"] is not None
    assert "thinking_config" not in kw


def test_solver_rejects_bad_answer_then_retries(monkeypatch):
    f = FakeLLM(solve=[text_resp('{"reasoning": "", "answer": {"refs": ["f0:e11", "f0:e12"]}}'),
                       text_resp('{"reasoning": "", "answer": {"refs": ["f0:e12"]}}')])
    monkeypatch.setattr(llm, "generate_agent", f)
    q = {"index": 1, "kind": "single", "text": "?", "options": OPTS}
    assert asyncio.run(qs.solve(q))["answer"] == {"refs": ["f0:e12"]}
    f.solve = [text_resp("мусор"), text_resp('{"answer": {}}')]
    with pytest.raises(qs.SolveError):
        asyncio.run(qs.solve(q))


def test_solver_short_prompt_when_timer_low(monkeypatch):
    f = FakeLLM(solve=[text_resp('{"reasoning": "-", "answer": {"refs": ["f0:e11"]}}')] * 2)
    monkeypatch.setattr(llm, "generate_agent", f)
    q = {"index": 1, "kind": "single", "text": "?", "options": OPTS}
    asyncio.run(qs.solve(q, seconds_left=45))
    asyncio.run(qs.solve(q, seconds_left=300))
    short, full = f.calls[0], f.calls[1]
    assert qs.STYLE_SHORT in short[0][-1].text and short[1]["max_tokens"] == 512
    assert qs.STYLE_FULL in full[0][-1].text and full[1]["max_tokens"] == 2048


def test_verify_checked_and_value():
    q = {"index": 1, "kind": "multi", "options": OPTS}
    els = [element(11, "checkbox", checked=True), element(13, "checkbox", checked=False)]
    assert qs.verify(q, {"refs": ["f0:e11"]}, els) is True
    assert qs.verify(q, {"refs": ["f0:e11", "f0:e13"]}, els) is False
    assert qs.verify({"ref": "f0:e10"}, {"text": "4"}, [element(10, "textbox", value="4")]) is True
    assert qs.verify(q, {"order": ["f0:e11"]}, els) is None


QUESTIONS = [
    {"index": 1, "kind": "single", "text": "Сколько будет QUESTION_SECRET 2+2?",
     "ref": "f0:e10", "options": OPTS, "answered": False},
    {"index": 2, "kind": "text", "text": "Столица QUESTION_SECRET?", "ref": "f0:e20",
     "options": [], "answered": False},
]


def quiz_obs(checked=None, values=None, extra=()):
    els = [element(11, "radio", "три"), element(12, "radio", "четыре"),
           element(13, "radio", "пять"), element(20, "textbox", "ответ"),
           element(30, "button", "Завершить тест"), element(31, "button", "Далее"), *extra]
    for e in els:
        if e["ref"] in (checked or ()):
            e["checked"] = True
        if e["ref"] in (values or {}):
            e["value"] = values[e["ref"]]
    return obs(url="https://quiz.ex/t", elements=els, timer={"text": "10:00", "seconds_left": 600})


def solve_resp(answer, reasoning="REASONING_SECRET"):
    return text_resp(json.dumps({"reasoning": reasoning, "answer": answer}))


def test_quiz_flow_solve_fill_verify_and_isolation(env, fake):
    task = new_task("пройди тест")
    desk = Desk(task)
    fake.nav = [fc("page_questions", note="читаю вопросы"),
                fc("page_act", note="завершаю", ref="f0:e30", action="click")]
    fake.solve = [solve_resp({"refs": ["f0:e12"]}), solve_resp({"text": "Москва"})]

    async def run():
        outs = [await desk.step(observation=quiz_obs())]
        res = {**OK, "detail": {"questions": QUESTIONS}}
        # пакет из двух: вопросу 2 (text) нужен кадр — сначала вырезка
        outs.append(await desk.step(observation=quiz_obs(), last_result=res))
        # кадр пришёл: оба решены параллельно, вписаны одним page_fill_form
        outs.append(await desk.step(observation=quiz_obs(), last_result=OK,
                                    frames=[frame("question", q_index=2)]))
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"],
                                                         values={"f0:e20": "Москва"}),
                                    last_result=OK))
        return outs
    outs = asyncio.run(run())
    assert outs[0]["action"]["tool"] == "page_questions"
    assert outs[1]["action"] == {"tool": "page_shot", "args": {"crop_ref": "f0:e20", "q_index": 2}}
    assert outs[2]["action"] == {"tool": "page_fill_form", "args": {"fields": [
        {"ref": "f0:e12", "checked": True}, {"ref": "f0:e20", "value": "Москва"}]}}
    # дальше навигатор: кнопка «Завершить» → сначала проверка вопросов
    assert outs[3]["action"]["tool"] == "page_questions"
    solve_calls = [c for c, kw in fake.calls if kw.get("response_schema") is not None]
    assert images(solve_calls[0]) == 0 and images(solve_calls[1]) == 1
    assert [a["status"] for a in task.answers] == ["verified", "verified"]
    assert task.reasoning == {1: "REASONING_SECRET", 2: "REASONING_SECRET"}
    for parts in fake.nav_requests():
        text = request_text(parts)
        assert "QUESTION_SECRET" not in text and "REASONING_SECRET" not in text
    last_nav = request_text(fake.nav_requests()[-1])
    assert "вопрос 1 (single): verified" in last_nav and "вопрос 2 (text): verified" in last_nav
    assert "f0:e12" not in last_nav.split("Страница сейчас")[1]      # варианты скрыты


def test_quiz_refill_when_not_checked(env, fake):
    task = new_task("тест")
    desk = Desk(task)
    fake.nav = [fc("page_questions")]
    fake.solve = [solve_resp({"refs": ["f0:e12"]})]

    async def run():
        await desk.step(observation=quiz_obs())
        res = {**OK, "detail": json.dumps({"questions": QUESTIONS[:1]})}
        await desk.step(observation=quiz_obs(), last_result=res)
        again = await desk.step(observation=quiz_obs(), last_result=OK)   # не отмечено
        await desk.step(observation=quiz_obs(), last_result=OK)           # снова нет
        return again
    again = asyncio.run(run())
    assert again["action"]["tool"] == "page_fill_form"
    assert task.answers[0]["status"] == "failed"


def test_missed_questions_solved_before_finish(env, fake):
    task = new_task("тест")
    desk = Desk(task)
    task.answers = [{"index": 1, "kind": "single", "answer": {"refs": ["f0:e12"]}, "status": "verified"}]
    fake.nav = [fc("page_act", note="завершаю тест", ref="f0:e30", action="click")]
    fake.solve = [solve_resp({"text": "Москва"})]
    q_with_media = [dict(QUESTIONS[0], answered=True), dict(QUESTIONS[1], has_media=False)]

    async def run():
        outs = [await desk.step(observation=quiz_obs(checked=["f0:e12"]))]
        res = {**OK, "detail": {"questions": q_with_media}}
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=res))
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=OK,
                                    frames=[frame("question", q_index=2)]))
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"],
                                                         values={"f0:e20": "Москва"}),
                                    last_result=OK))
        return outs
    outs = asyncio.run(run())
    assert outs[0]["action"]["tool"] == "page_questions"           # перехват «Завершить»
    assert outs[1]["action"]["tool"] == "page_shot"                # пропущенный вопрос 2
    assert outs[2]["action"]["tool"] == "page_fill_form"
    assert outs[3]["action"] == {"tool": "page_act", "args": {"ref": "f0:e30", "action": "click"}}
    assert fake.kinds().count("nav") == 1                           # кнопку не перерешивали


def test_final_report_lists_answers(env, fake):
    task = new_task("тест")
    desk = Desk(task)
    task.answers = [{"index": 1, "kind": "single", "answer": {"refs": ["f0:e12"]}, "status": "verified"},
                    {"index": 2, "kind": "text", "answer": {"text": "Москва"}, "status": "filled"}]
    task.quiz = {"labels": {1: "четыре"}}
    fake.nav = [fc("done", note="готово", summary="тест сдан")]
    out = asyncio.run(desk.step())
    assert out["status"] == "done" and out["summary"] == "тест сдан"
    report = env.tg[-1]
    assert "Итог: тест сдан" in report and "Шагов: 1" in report
    assert "Вопрос 1: четыре" in report and "Вопрос 2: Москва" in report
    assert not (bt.TASKS_DIR / f"{task.task_id}.json").exists()


# ── S8: формы и капча ────────────────────────────────────────────────

def test_form_resubmitted_after_validation_errors(env, fake):
    task = new_task()
    desk = Desk(task)
    submit = element(5, "button", "Отправить")
    form = [element(1, "textbox", "email"), element(2), element(3), element(4), submit]
    bad = [element(1, "textbox", "email", invalid=True, error="неверный email"),
           element(2), element(3), element(4), submit]
    fake.default_nav = fc("page_act", note="отправляю", ref="f0:e5", action="click")

    async def run():
        outs = [await desk.step(observation=obs(elements=form))]
        for _ in range(4):
            outs.append(await desk.step(observation=obs(elements=bad), last_result=OK))
        return outs
    outs = asyncio.run(run())
    hints = [request_text(r) for r in fake.nav_requests()[1:]]
    assert "попытка 1 из 3" in hints[0] and "f0:e1" in hints[0]
    assert "попытка 3 из 3" in hints[2]
    assert outs[4]["status"] == "fail" and "форма не принята после 3" in outs[4]["reason"]


def test_captcha_pause_and_resume(env, fake):
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_observe", note="смотрю")]

    async def run():
        first = await desk.step(observation=obs(captcha_detected=True))
        again = await desk.step(observation=obs(captcha_detected=True))
        resumed = await bs.on_resume(desk.ws, {"task_id": task.task_id}, {})
        after = await desk.step(observation=obs(), last_result=OK)
        return first, again, resumed, after
    first, again, resumed, after = asyncio.run(run())
    assert first["status"] == "paused" and "капчу" in first["reason"]
    assert again["status"] == "paused"
    assert any("капчу" in t for t in env.tg) and any(o and "капчу" in o for o in env.orb)
    assert resumed == {"type": "browser.resume", "task_id": task.task_id, "state": "running"}
    assert after["action"]["tool"] == "page_observe"


# ── S9: управление ───────────────────────────────────────────────────

def test_cancel_by_stop(env, fake):
    task = new_task()
    desk = Desk(task)
    asyncio.run(desk.step())
    text, ok = asyncio.run(bs.stop("pc"))
    assert ok and "Остановила" in text
    assert desk.ws.sent[-1] == {"type": "browser.cancel", "task_id": task.task_id}
    assert task.state == "cancelled" and len(task.frames) == 0
    out = asyncio.run(desk.step())
    assert out["status"] == "fail"
    assert asyncio.run(bs.stop("pc"))[0] == "Сейчас нет задачи в браузере."


def test_start_sends_browser_do(env, monkeypatch):
    import modules.state as st
    ws = WS()
    monkeypatch.setattr(st, "connected_devices", {"pc": ws})
    _text, ok = asyncio.run(bs.start("сделай заказ на https://shop.ex/x", ws, "pc"))
    assert ok
    msg = ws.sent[-1]
    assert msg["type"] == "browser.do" and msg["start_url"] == "https://shop.ex/x"
    assert bt.get(msg["task_id"]).goal == "сделай заказ на https://shop.ex/x"


def test_progress_throttled(env, fake):
    task = new_task()
    desk = Desk(task)

    async def run():
        for i in range(3):
            await desk.step(last_result=OK if i else None)
    asyncio.run(run())
    assert len([t for t in env.tg if "шаг" in t]) == 1           # не чаще раза в 10 с
    assert env.orb[0].startswith("шаг 1 — ")


# ── лимиты ───────────────────────────────────────────────────────────

def test_step_limit_fails_with_last_note(env, fake, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_MAX_STEPS", 2)
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_observe", note="первый"), fc("page_observe", note="второй")]

    async def run():
        return [await desk.step(last_result=OK if i else None) for i in range(3)]
    outs = asyncio.run(run())
    assert outs[2] == {"type": "browser_step", "request_id": "r3", "task_id": task.task_id,
                       "status": "fail", "reason": "лимит шагов (2); последнее: второй"}


def test_zero_means_no_limit(env, fake, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_MAX_STEPS", 0)
    monkeypatch.setattr(config, "BROWSER_MAX_SECONDS", 0)
    monkeypatch.setattr(config, "BROWSER_MAX_TOKENS", 0)
    task = new_task()
    task.started_at -= 100_000
    task.tokens_used = 10**9
    desk = Desk(task)

    async def run():
        return [await desk.step(last_result=OK if i else None) for i in range(5)]
    assert all("action" in o for o in asyncio.run(run()))


def test_time_and_token_limits(env, fake, monkeypatch):
    task = new_task()
    task.started_at -= 2000
    out = asyncio.run(Desk(task).step())
    assert out["status"] == "fail" and out["reason"].startswith("лимит времени")
    task = new_task()
    task.started_at -= 2000
    task.paused_s = 1900                       # паузы не считаются
    assert "action" in asyncio.run(Desk(task).step())
    monkeypatch.setattr(config, "BROWSER_MAX_TOKENS", 15)
    task = new_task()
    desk = Desk(task)

    async def run():
        return [await desk.step(last_result=OK if i else None) for i in range(3)]
    outs = asyncio.run(run())
    assert outs[1]["action"] and outs[2]["reason"].startswith("лимит токенов (15)")


# ── S10: подтверждения ───────────────────────────────────────────────

def _submit_obs():
    return obs(elements=[element(1, "textbox", "Пароль", type="password"), element(2), element(3),
                         element(4), element(5, "button", "Отправить")])


def test_confirm_off_acts_without_questions(env, fake):
    task = new_task()
    fake.nav = [fc("page_act", note="отправляю", ref="f0:e5", action="click")]
    out = asyncio.run(Desk(task).step(observation=_submit_obs()))
    assert out["action"] == {"tool": "page_act", "args": {"ref": "f0:e5", "action": "click"}}


def test_confirm_on_holds_submit_and_password(env, fake, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_CONFIRM_SENSITIVE", True)
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_act", note="ввожу пароль", ref="f0:e1", action="type", text="x")]

    async def run():
        held = await desk.step(observation=_submit_obs())
        await bs.on_resume(desk.ws, {"task_id": task.task_id}, {})
        released = await desk.step(observation=_submit_obs())
        return held, released
    held, released = asyncio.run(run())
    assert held["status"] == "paused" and "ввод пароля" in held["reason"]
    assert released["action"]["args"]["ref"] == "f0:e1"
    assert fake.kinds() == ["nav"]                              # решение не перезапрашивали
    assert bs.sensitive("page_fill_form", {"fields": [], "submit_ref": "f0:e5"}, _submit_obs())
    assert bs.sensitive("page_scroll", {"direction": "down"}, _submit_obs()) is None


# ── кадры: не в логах, не в чекпоинтах ───────────────────────────────

def test_frames_and_page_text_not_logged(env, fake, caplog):
    caplog.set_level(logging.DEBUG)
    task = new_task()
    desk = Desk(task)
    fake.nav = [fc("page_questions")]
    fake.solve = [solve_resp({"refs": ["f0:e12"]})]

    async def run():
        await desk.step(observation=quiz_obs(), frames=[frame()])
        res = {**OK, "detail": {"questions": QUESTIONS[:1]}}
        await desk.step(observation=quiz_obs(), last_result=res, frames=[frame()])
    asyncio.run(run())
    path = bt.TASKS_DIR / f"{task.task_id}.json"
    for blob in (caplog.text, path.read_text(encoding="utf-8")):
        assert B64[:40] not in blob and "FRAMEBYTES" not in blob
        assert PAGE_SECRET not in blob and "QUESTION_SECRET" not in blob
        assert "REASONING_SECRET" not in blob
    assert "шаг 2 → page_fill_form" in caplog.text


# ── протокол ─────────────────────────────────────────────────────────

def test_proto_routes_master_secure_and_flag(env, monkeypatch):
    import sakura_core.proto_v2 as pv2
    assert pv2.is_v2("browser_step") and pv2.is_v2("browser.resume")
    assert pv2.is_private("browser_step") and pv2.is_private("browser.resume")
    monkeypatch.setattr(pv2, "connection_secure", lambda ws: True)
    monkeypatch.setattr(pv2, "_is_master", lambda d: True)
    monkeypatch.setattr(config, "BROWSER_AGENT", False)
    ws = WS()
    asyncio.run(pv2.handle(ws, {"type": "browser_step", "request_id": "x", "device_id": "pc"}, {}))
    assert ws.sent[-1]["code"] == "unsupported"
    monkeypatch.setattr(pv2, "_is_master", lambda d: False)
    asyncio.run(pv2.handle(ws, {"type": "browser_step", "request_id": "y", "device_id": "ph"}, {}))
    assert ws.sent[-1]["code"] == "not_master"


def test_bad_frames_rejected(env):
    task = new_task()
    desk = Desk(task)
    out = asyncio.run(desk.step(frames=[{"kind": "page", "mime": "image/png", "data_b64": B64}]))
    assert out["type"] == "error" and out["code"] == "bad_request"
    out = asyncio.run(desk.step(frames=[frame()] * 5))
    assert out["code"] == "bad_request"


def test_restart_reschedules_quota_resume(env, monkeypatch):
    task = new_task()
    task.state, task.pause_kind, task.resume_at = "paused", "quota", 1_000.0
    bt.checkpoint(task)
    bt.reset()
    monkeypatch.setattr(bs, "_loaded", False)
    ws = WS()
    import modules.state as st
    monkeypatch.setattr(st, "connected_devices", {"pc": ws})

    async def run():
        bs.ensure_loaded()
        bs.ensure_loaded()                        # второй раз — ничего
        await asyncio.sleep(0.05)
    asyncio.run(run())
    assert bt.get(task.task_id).state == "running"
    assert ws.sent == [{"type": "browser.do", "task_id": task.task_id,
                        "goal": task.goal, "resume": True}]


# ── параллельный решатель, мысли навигатора, 500 → пауза ─────────────

def _single_questions(n):
    return [{"index": i, "kind": "single", "text": f"вопрос {i}?", "ref": f"f0:e{100 + i}",
             "options": [{"ref": f"f0:e{200 + i}", "name": "да"}], "answered": False}
            for i in range(1, n + 1)]


def _quiz_raw(monkeypatch, delay=0.02):
    """generate_raw для решателя: ответ по номеру вопроса, учёт одновременности."""
    import re as _re
    state = {"now": 0, "max": 0, "calls": 0}

    async def raw(model, contents, timeout=None, **cfg):
        state["calls"] += 1
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(delay)
        state["now"] -= 1
        idx = int(_re.search(r"Вопрос (\d+)", contents[-1].text).group(1))
        return SimpleNamespace(text=json.dumps({"reasoning": "r", "answer": {"refs": [f"f0:e{200 + idx}"]}}),
                               usage_metadata=None)

    monkeypatch.setattr(llm, "generate_raw", raw)
    return state


def test_quiz_parallel_batches_of_three(env, fake, monkeypatch):
    monkeypatch.setattr(llm, "generate_agent", ORIGINAL_GENERATE_AGENT)
    monkeypatch.setattr(config, "QUIZ_PARALLEL", 3)
    monkeypatch.setattr(rl, "_limiter", rl.RateLimiter(rpm=100, rpd=1000, path=None))
    state = _quiz_raw(monkeypatch)
    task = new_task("тест")
    task.pending["await"] = "questions"
    desk = Desk(task)

    async def run():
        res = {**OK, "detail": {"questions": _single_questions(5)}}
        first = await desk.step(observation=quiz_obs(), last_result=res)
        second = await desk.step(observation=quiz_obs(), last_result=OK)
        return first, second
    first, second = asyncio.run(run())
    assert [f["ref"] for f in first["action"]["args"]["fields"]] == ["f0:e201", "f0:e202", "f0:e203"]
    assert [f["ref"] for f in second["action"]["args"]["fields"]] == ["f0:e204", "f0:e205"]
    assert state["max"] == 3 and state["calls"] == 5


def test_quiz_parallel_respects_limiter(env, fake, monkeypatch):
    """RPM 2: третий вопрос пакета ждёт квоту (status wait), решённые не перерешиваются."""
    monkeypatch.setattr(llm, "generate_agent", ORIGINAL_GENERATE_AGENT)
    clock = Clock()
    lim = rl.RateLimiter(rpm=2, rpd=1000, path=None, clock=clock)
    monkeypatch.setattr(rl, "_limiter", lim)
    state = _quiz_raw(monkeypatch, delay=0)
    task = new_task("тест")
    task.pending["await"] = "questions"
    desk = Desk(task)

    async def run():
        res = {**OK, "detail": {"questions": _single_questions(3)}}
        waited = await desk.step(observation=quiz_obs(), last_result=res, step=1)
        clock.t += 30                                   # токен вернулся
        filled = await desk.step(observation=quiz_obs(), last_result=res, step=1)
        return waited, filled
    waited, filled = asyncio.run(run())
    assert waited["status"] == "wait" and waited["retry_after"] == 30
    assert state["calls"] == 3                          # 2 + 1, без повторов решённых
    assert len(filled["action"]["args"]["fields"]) == 3
    assert lim.used("gemma-4-31b-it") == 3


ORIGINAL_GENERATE_AGENT = llm.generate_agent


def test_navigator_minimal_thinking_solver_default(env, fake, monkeypatch):
    task = new_task()
    asyncio.run(Desk(task).step())
    assert fake.calls[-1][1]["thinking_level"] == "minimal"
    monkeypatch.setattr(config, "BROWSER_NAV_THINKING", "")
    asyncio.run(Desk(new_task()).step())
    assert fake.calls[-1][1]["thinking_level"] is None
    f = FakeLLM(solve=[solve_resp({"refs": ["f0:e11"]})])
    monkeypatch.setattr(llm, "generate_agent", f)
    asyncio.run(qs.solve({"index": 1, "kind": "single", "text": "?", "options": OPTS}))
    assert "thinking_level" not in f.calls[0][1]


def test_server_errors_pause_with_own_message(env, fake):
    task = new_task()
    fake.nav = [llm.ChainExhausted(1_000.0, reason="unavailable")]
    out = asyncio.run(Desk(task).step())
    assert out["status"] == "paused" and out["reason"].startswith("Gemma не отвечает")
    assert task.pause_kind == "quota"


def test_max_seconds_default_unlimited():
    import os
    assert config.BROWSER_MAX_SECONDS == int(os.getenv("BROWSER_MAX_SECONDS", "0"))


# ── сопоставление и порядок парами, skipped, фолбэк решателя ─────────

MATCH_ROWS = [{"ref": "f0:e41", "name": "Франция"}, {"ref": "f0:e42", "name": "Япония"}]
MATCH_Q = {"index": 1, "kind": "match", "text": "Сопоставьте страну и столицу", "ref": "f0:e40",
           "rows": MATCH_ROWS, "options": [{"name": "Париж"}, {"name": "Токио"}, {"name": "Рим"}]}
# нынешняя форма расширения: строки — options (select), тексты — choices
MATCH_Q_EXT = {"index": 1, "kind": "match", "text": "Сопоставьте", "ref": "f0:e40",
               "options": [{"ref": "f0:e41", "name": "Франция", "text": "Франция"},
                           {"ref": "f0:e42", "name": "Япония", "text": "Япония"}],
               "choices": ["Париж", "Токио", "Рим"]}
ORDER_ROWS_Q = {"index": 2, "kind": "order", "text": "Расставьте по порядку", "ref": "f0:e50",
                "rows": [{"ref": "f0:e51", "name": "Рассвет"}, {"ref": "f0:e52", "name": "Закат"}],
                "options": [{"name": "1"}, {"name": "2"}]}
ORDER_PLAIN_Q = {"index": 3, "kind": "order", "text": "Упорядочьте", "ref": "f0:e60",
                 "options": [{"ref": "f0:e61", "name": "Б"}, {"ref": "f0:e62", "name": "А"}]}

PAIRS_OK = [{"row_ref": "f0:e41", "option_text": "париж"}, {"row_ref": "f0:e42", "option_text": "Токио"}]


@pytest.mark.parametrize("question", [MATCH_Q, MATCH_Q_EXT])
def test_solver_match_pairs(monkeypatch, question):
    f = FakeLLM(solve=[solve_resp({"pairs": PAIRS_OK})])
    monkeypatch.setattr(llm, "generate_agent", f)
    res = asyncio.run(qs.solve(question))
    assert res["answer"] == {"pairs": [{"row_ref": "f0:e41", "option_text": "Париж"},
                                       {"row_ref": "f0:e42", "option_text": "Токио"}]}
    prompt = f.calls[0][0][-1].text
    assert "Строки:\n- f0:e41: Франция" in prompt and "- Рим" in prompt and "answer.pairs" in prompt
    assert qs.fill_fields(question, res["answer"]) == [{"ref": "f0:e40", "pairs": res["answer"]["pairs"]}]
    assert qs.answer_label(question, res["answer"]) == "Франция → Париж; Япония → Токио"


def test_solver_match_rejects_incomplete_or_foreign_pairs(monkeypatch):
    bad1 = solve_resp({"pairs": PAIRS_OK[:1]})
    bad2 = solve_resp({"pairs": [PAIRS_OK[0], {"row_ref": "f0:e42", "option_text": "Берлин"}]})
    monkeypatch.setattr(llm, "generate_agent", FakeLLM(solve=[bad1, bad2]))
    with pytest.raises(qs.SolveError):
        asyncio.run(qs.solve(MATCH_Q))


def test_solver_order_with_rows_uses_pairs(monkeypatch):
    pairs = [{"row_ref": "f0:e51", "option_text": "1"}, {"row_ref": "f0:e52", "option_text": "2"}]
    monkeypatch.setattr(llm, "generate_agent", FakeLLM(solve=[solve_resp({"pairs": pairs})]))
    assert asyncio.run(qs.solve(ORDER_ROWS_Q))["answer"] == {"pairs": pairs}
    # место повторяется — не годится
    dup = [{"row_ref": "f0:e51", "option_text": "1"}, {"row_ref": "f0:e52", "option_text": "1"}]
    with pytest.raises(qs.SolveError):
        qs.validate(ORDER_ROWS_Q, {"pairs": dup})


def test_solver_order_without_rows_keeps_order(monkeypatch):
    f = FakeLLM(solve=[solve_resp({"order": ["f0:e62", "f0:e61"]})])
    monkeypatch.setattr(llm, "generate_agent", f)
    res = asyncio.run(qs.solve(ORDER_PLAIN_Q))
    assert res["answer"] == {"order": ["f0:e62", "f0:e61"]}
    assert "answer.order" in f.calls[0][0][-1].text and "Строки:" not in f.calls[0][0][-1].text
    assert qs.fill_fields(ORDER_PLAIN_Q, res["answer"]) == [{"ref": "f0:e60", "order": ["f0:e62", "f0:e61"]}]


def test_pairs_verify_by_select_values():
    els = [element(41, "combobox", value="Париж"), element(42, "combobox", value="Токио")]
    pairs = {"pairs": [{"row_ref": "f0:e41", "option_text": "Париж"},
                       {"row_ref": "f0:e42", "option_text": "Токио"}]}
    assert qs.verify(MATCH_Q, pairs, els) is True
    els[1]["value"] = "Рим"
    assert qs.verify(MATCH_Q, pairs, els) is False
    assert qs.verify(MATCH_Q, pairs, [element(41)]) is None


def _quiz_task(questions):
    task = new_task("тест")
    task.pending["await"] = "questions"
    return task, Desk(task), {**OK, "questions": questions}


def test_match_and_order_each_go_in_own_fill_form(env, fake, monkeypatch):
    monkeypatch.setattr(config, "QUIZ_PARALLEL", 3)
    single = dict(QUESTIONS[0], index=4)
    fake.solve = [solve_resp({"pairs": PAIRS_OK}), solve_resp({"order": ["f0:e62", "f0:e61"]}),
                  solve_resp({"refs": ["f0:e12"]})]
    _task, desk, res = _quiz_task([dict(MATCH_Q, has_media=False), ORDER_PLAIN_Q, single])
    frames = [frame("question", q_index=1, fid="a"), frame("question", q_index=3, fid="b")]

    async def run():
        outs = [await desk.step(observation=quiz_obs(), last_result=res)]          # кадр вопроса 1
        outs.append(await desk.step(observation=quiz_obs(), last_result=OK, frames=frames[:1]))
        outs.append(await desk.step(observation=quiz_obs(), last_result=OK, frames=frames[1:]))
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=OK))
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=OK))
        return outs
    outs = asyncio.run(run())
    assert outs[0]["action"]["tool"] == "page_shot" and outs[1]["action"]["tool"] == "page_shot"
    simple, match, order = (o["action"]["args"]["fields"] for o in outs[2:5])
    assert simple == [{"ref": "f0:e12", "checked": True}]
    assert match == [{"ref": "f0:e40", "pairs": [{"row_ref": "f0:e41", "option_text": "Париж"},
                                                 {"row_ref": "f0:e42", "option_text": "Токио"}]}]
    assert order == [{"ref": "f0:e60", "order": ["f0:e62", "f0:e61"]}]


def test_unsupported_fill_marks_skipped_and_reported(env, fake, monkeypatch):
    monkeypatch.setattr(config, "QUIZ_PARALLEL", 3)
    fake.solve = [solve_resp({"order": ["f0:e62", "f0:e61"]}), solve_resp({"refs": ["f0:e12"]})]
    fake.nav = [fc("done", note="готово", summary="тест пройден")]
    single = dict(QUESTIONS[0], index=4)
    task, desk, res = _quiz_task([ORDER_PLAIN_Q, single])
    unsupported = {"ok": False, "status": "unsupported",
                   "detail": "порядок вариантов (перетаскивание) расширение не заполняет"}

    async def run():
        outs = [await desk.step(observation=quiz_obs(), last_result=res)]          # кадр вопроса 3
        outs.append(await desk.step(observation=quiz_obs(), last_result=OK,
                                    frames=[frame("question", q_index=3)]))      # простой ответ
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=OK))  # order
        outs.append(await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=unsupported))
        return outs
    outs = asyncio.run(run())
    assert outs[2]["action"]["args"]["fields"][0]["order"] == ["f0:e62", "f0:e61"]
    assert outs[3]["status"] == "done"                     # задача пошла дальше — к навигатору
    entry = next(a for a in task.answers if a["index"] == 3)
    assert entry["status"] == "skipped" and "перетаскивание" in entry["reason"]
    report = env.tg[-1]
    assert "Вопрос 3: пропущен — порядок вариантов (перетаскивание) расширение не заполняет" in report
    assert "Вопрос 4: четыре" in report


def test_field_level_unsupported_marks_only_its_question(env, fake, monkeypatch):
    monkeypatch.setattr(config, "QUIZ_PARALLEL", 3)
    q_text = dict(QUESTIONS[1], index=5, has_media=False)
    fake.solve = [solve_resp({"refs": ["f0:e12"]}), solve_resp({"text": "Москва"})]
    single = dict(QUESTIONS[0], index=4)
    task, desk, res = _quiz_task([single, q_text])
    partial = {"ok": False, "status": "error", "detail": "заполнено 1 из 2",
               "data": {"fields": [{"ref": "f0:e12", "status": "done"},
                                   {"ref": "f0:e20", "status": "unsupported",
                                    "detail": "не текстовое поле"}]}}

    async def run():
        await desk.step(observation=quiz_obs(), last_result=res)                     # кадр вопроса 5
        await desk.step(observation=quiz_obs(), last_result=OK, frames=[frame("question", q_index=5)])
        await desk.step(observation=quiz_obs(checked=["f0:e12"]), last_result=partial)
    asyncio.run(run())
    status = {a["index"]: (a["status"], a.get("reason")) for a in task.answers}
    assert status[4] == ("verified", None)
    assert status[5] == ("skipped", "не текстовое поле")


def test_skipped_not_resolved_on_final_check(env, fake):
    task = new_task("тест")
    task.answers = [{"index": 3, "kind": "order", "answer": {"order": ["f0:e62"]},
                     "status": "skipped", "reason": "не поддерживается"}]
    task.pending.update({"await": "questions", "final_check": True,
                         "finish_action": {"tool": "page_act", "args": {"ref": "f0:e30", "action": "click"},
                                           "note": "завершаю"}})
    out = asyncio.run(Desk(task).step(observation=quiz_obs(), last_result={**OK, "questions": [ORDER_PLAIN_Q]}))
    assert out["action"] == {"tool": "page_act", "args": {"ref": "f0:e30", "action": "click"}}
    assert fake.kinds() == []


def test_solver_falls_back_to_26b(env, monkeypatch):
    """31b не ответил (сбой/квота) — тот же вопрос решает 26b."""
    monkeypatch.setattr(llm, "generate_agent", ORIGINAL_GENERATE_AGENT)
    clock = Clock()
    monkeypatch.setattr(rl, "_limiter", rl.RateLimiter(rpm=100, rpd=1000, path=None, clock=clock))
    seen = []

    class Exhausted(Exception):
        code = 429

        def __init__(self, msg):
            super().__init__(msg)
            self.details = {"error": {"details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                 "violations": [{"quotaId": "RequestsPerDayPerModel"}]}]}}

    async def raw(model, contents, timeout=None, **cfg):
        seen.append(model)
        if model == "gemma-4-31b-it":
            raise Exhausted("429 RESOURCE_EXHAUSTED")
        return SimpleNamespace(text=json.dumps({"reasoning": "r", "answer": {"pairs": PAIRS_OK}}),
                               usage_metadata=None)

    monkeypatch.setattr(llm, "generate_raw", raw)
    res = asyncio.run(qs.solve(MATCH_Q))
    assert seen == ["gemma-4-31b-it", "gemma-4-26b-a4b-it"] and res["model"] == "gemma-4-26b-a4b-it"
