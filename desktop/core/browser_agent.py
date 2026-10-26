"""desktop.core.browser_agent — цикл задачи агента браузера (общий контракт BROWSER AGENT).

Состояние задачи и решения модели — на сервере; ядро ведёт цикл шагов и транзит к расширению:

  server → desktop  browser.do {task_id, goal, start_url?}
  ядро открывает окно агента (agent_window.open, без фокуса) и на каждом шаге шлёт
  desktop → server  browser_step {request_id, task_id, step, last_result?, observation, frames}
  server → desktop  browser_step {action: {tool, args}} | {status: wait|done|fail|paused, ...}
  server → desktop  browser.cancel {task_id}
  desktop → server  browser.resume {task_id}   — после «готово» Мастера на капче/паузе

Обрыв связи с сервером — ждём подключения и продолжаем с page.observe (тот же step);
выгрузка service worker расширения — ждём переподключения расширения, затем page.observe.
Кадры и текст страниц не логируются: в журнале task_id, шаг, tool, status, размеры.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

log = logging.getLogger("sakura.browser_agent")

TOOLS = ("tabs_list", "tabs_activate", "tabs_new", "tabs_close", "page_observe", "page_act", "page_shot",
         "page_forms", "page_questions", "page_fill_form", "page_upload", "page_scroll", "done", "fail")
# tool → действие расширения и тайм-аут, с.
EXT_ACTIONS = {
    "tabs_list": ("tabs.list", 10), "tabs_activate": ("tabs.activate", 10), "tabs_new": ("tabs.new", 15),
    "tabs_close": ("tabs.close", 10), "page_observe": ("page.observe", 25), "page_act": ("page.act", 40),
    "page_shot": ("page.shot", 25), "page_forms": ("page.forms", 30), "page_questions": ("page.questions", 30),
    "page_fill_form": ("page.fill_form", 90), "page_upload": ("page.upload", 90), "page_scroll": ("page.scroll", 25),
}
EXT_LOST = ("Расширение не подключено", "Тайм-аут расширения")
EXT_DOWN = "Расширение не подключено"   # команда не ушла — повтор безопасен
# Чтение: после тайм-аута расширения можно повторить. Остальное могло выполниться — не повторяем.
READ_ONLY = frozenset({"page.observe", "page.shot", "tabs.list", "page.forms", "page.questions"})
STEP_TIMEOUT = 120.0       # ответ сервера на шаг (модель думает)
EXT_WAIT = 60.0            # ждать возвращения расширения (service worker выгружен)
POLL = 1.0
MAX_FAILURES = 5           # подряд ошибок сервера (кроме обрыва связи) — задача прекращается
MAX_QUESTION_FRAMES = 4    # кадры вопросов с картинками на шаг


@dataclass
class _Task:
    task_id: str
    goal: str
    start_url: str | None
    step: int = 1
    window_id: int | None = None
    tab_id: int | None = None
    last_result: dict | None = None
    observe: dict | None = None            # свежий снимок из ответа действия
    frames: list = field(default_factory=list)
    resume: asyncio.Event = field(default_factory=asyncio.Event)
    paused: bool = False
    resume_local: bool = False
    runner: asyncio.Task | None = None


def _result(status: str, detail: str = "", **extra) -> dict:
    return {"ok": status == "done", "status": status, "detail": detail, **extra}


def _ext_lost(r: dict) -> bool:
    return not isinstance(r, dict) or ("status" not in r and r.get("error") in EXT_LOST)


def _normalize(r) -> dict:
    """Ответ extension_server → {ok, status, detail, ...}; ошибки транспорта → error."""
    if isinstance(r, dict) and r.get("status") in ("done", "stale", "not_found", "unsupported", "error"):
        return r
    detail = r.get("error") if isinstance(r, dict) else ""
    return _result("error", str(detail or "нет ответа расширения"))


def parse_reply(reply: dict) -> tuple[str, dict]:
    """Ответ сервера на шаг → (kind, данные): action | wait | done | fail | paused | unknown."""
    action = reply.get("action")
    if isinstance(action, dict) and action.get("tool"):
        tool = action["tool"]
        if tool in ("done", "fail"):
            args = action.get("args") or {}
            return tool, {"summary": args.get("summary", ""), "reason": args.get("reason", "")}
        return "action", {"tool": tool, "args": action.get("args") or {}}
    st = reply.get("status")
    if isinstance(st, dict):
        kind = st.get("type") or st.get("kind") or next(iter(st), "")
        inner = st.get(kind) if isinstance(st.get(kind), dict) else st
        return kind if kind in ("wait", "done", "fail", "paused") else "unknown", dict(inner)
    if st in ("wait", "done", "fail", "paused"):
        return st, reply
    return "unknown", {}


class BrowserAgent:
    def __init__(self, *, request: Callable[[dict], Awaitable[dict]], send: Callable[[dict], Awaitable[None]],
                 ext: Callable[..., Awaitable[dict]], ext_connected: Callable[[], bool],
                 online: Callable[[], bool], uploads=None, emit: Callable[[dict], None] | None = None,
                 sleep=asyncio.sleep, clock=time.monotonic, step_shot: bool = True,
                 ext_wait: float = EXT_WAIT, poll: float = POLL):
        self._request = request
        self._send = send
        self._ext = ext
        self._ext_connected = ext_connected
        self._online = online
        self._uploads = uploads
        self._emit = emit or (lambda ev: None)
        self._sleep = sleep
        self._clock = clock
        self._step_shot = step_shot
        self._ext_wait = ext_wait
        self._poll = poll
        self.tasks: dict[str, _Task] = {}

    # ── управление задачами ────────────────────────────────────────
    def start(self, task_id: str, goal: str, start_url: str | None = None) -> bool:
        if not task_id or task_id in self.tasks:
            return False
        t = _Task(str(task_id), str(goal or ""), start_url or None)
        self.tasks[t.task_id] = t
        t.runner = asyncio.ensure_future(self._run(t))
        log.info("[browser] task=%s старт", t.task_id)
        self._emit({"type": "browser_task", "task_id": t.task_id, "state": "running", "text": "", "window_id": None})
        return True

    def cancel(self, task_id: str) -> bool:
        t = self.tasks.get(str(task_id))
        if t is None or t.runner is None:
            return False
        t.runner.cancel()
        return True

    def cancel_all(self) -> None:
        for tid in list(self.tasks):
            self.cancel(tid)

    def resume(self, task_id: str, local: bool = True) -> bool:
        """«Готово» Мастера (local — из интерфейса: ядро сообщит серверу browser.resume)."""
        t = self.tasks.get(str(task_id))
        if t is None or not t.paused:
            return False
        t.resume_local = local
        t.resume.set()
        return True

    async def wait(self, task_id: str) -> None:
        t = self.tasks.get(str(task_id))
        if t is not None and t.runner is not None:
            await asyncio.gather(t.runner, return_exceptions=True)

    # ── цикл ───────────────────────────────────────────────────────
    async def _run(self, t: _Task) -> None:
        state, text = "fail", ""
        failures = 0
        try:
            await self._open_window(t)
            while True:
                obs = t.observe if t.observe is not None else await self._observe(t)
                t.observe = None
                frames = list(t.frames)
                t.frames.clear()
                if self._step_shot and t.window_id is not None:
                    frames.extend(await self._page_frame(t))
                msg = {"type": "browser_step", "task_id": t.task_id, "step": t.step,
                       "observation": obs, "frames": self._number(t, frames)}
                if t.last_result is not None:
                    msg["last_result"] = t.last_result
                size = sum(len(f.get("data_b64", "")) for f in msg["frames"])
                try:
                    reply = await self._request(msg)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 — ApiError: offline | timeout | not_master | …
                    code = getattr(e, "code", type(e).__name__)
                    log.info("[browser] task=%s step=%d запрос: %s", t.task_id, t.step, code)
                    if code == "offline":
                        await self._wait_online()
                        continue
                    failures += 1
                    if code == "timeout" and failures < MAX_FAILURES:
                        continue
                    text = f"сервер не отвечает ({code})" if code == "timeout" else f"сервер отказал: {code}"
                    return
                failures = 0
                kind, data = parse_reply(reply)
                log.info("[browser] task=%s step=%d → %s frames=%d bytes=%d", t.task_id, t.step,
                         data.get("tool") if kind == "action" else kind, len(msg["frames"]), size)
                if kind == "action":
                    await self._do(t, data["tool"], data["args"])
                    t.step += 1
                elif kind == "wait":
                    await self._sleep(max(0.0, min(float(data.get("retry_after") or 1), 600.0)))
                elif kind == "paused":
                    await self._pause(t, str(data.get("reason") or ""))
                elif kind == "done":
                    state, text = "done", str(data.get("summary") or "")
                    return
                elif kind == "fail":
                    text = str(data.get("reason") or "")
                    return
                else:
                    failures += 1
                    if failures >= MAX_FAILURES:
                        text = "непонятный ответ сервера"
                        return
        except asyncio.CancelledError:
            state, text = "cancelled", ""
            raise
        except Exception as e:  # noqa: BLE001
            log.error("[browser] task=%s step=%d ошибка: %s", t.task_id, t.step, type(e).__name__)
            text = "внутренняя ошибка ядра"
        finally:
            self.tasks.pop(t.task_id, None)
            log.info("[browser] task=%s конец: %s, шагов %d", t.task_id, state, t.step - 1)
            self._emit({"type": "browser_task", "task_id": t.task_id, "state": state, "text": text,
                        "window_id": t.window_id})

    # ── окно, снимок, кадры ────────────────────────────────────────
    async def _call(self, t: _Task, action: str, args: dict, timeout: float) -> dict:
        """Вызов расширения. Пропало (service worker выгружен) — ждём его возвращения и повторяем
        один раз: если команда не ушла, или это чтение. Действие после тайм-аута не повторяется."""
        r = await self._ext(action, args, timeout)
        down = isinstance(r, dict) and r.get("error") == EXT_DOWN
        if _ext_lost(r) and (down or action in READ_ONLY) and await self._wait_ext():
            r = await self._ext(action, args, timeout)
        return _normalize(r)

    async def _open_window(self, t: _Task) -> None:
        r = await self._call(t, "agent_window.open", {"url": t.start_url or "about:blank"}, 20)
        if r["ok"]:
            t.window_id, t.tab_id = r["data"]["window_id"], r["data"]["tab_id"]
            t.last_result = None
        else:
            t.last_result = _result(r["status"] if r["status"] != "done" else "error",
                                    "окно агента не открыто: " + str(r.get("detail") or ""))

    async def _observe(self, t: _Task) -> dict | None:
        if t.tab_id is None:
            if t.window_id is None:
                await self._open_window(t)
            if t.tab_id is None:
                return None
        r = await self._call(t, "page.observe", {"tab_id": t.tab_id}, EXT_ACTIONS["page_observe"][1])
        if r["status"] == "not_found" and await self._recover_tab(t):
            r = await self._call(t, "page.observe", {"tab_id": t.tab_id}, EXT_ACTIONS["page_observe"][1])
        if r["ok"]:
            return r.get("data")
        if t.last_result is None or t.last_result.get("ok"):
            t.last_result = _result(r["status"], "снимок страницы не получен: " + str(r.get("detail") or ""))
        return None

    async def _recover_tab(self, t: _Task) -> bool:
        """Текущая вкладка закрыта — активная вкладка окна агента."""
        if t.window_id is None:
            return False
        r = await self._call(t, "tabs.list", {"window_id": t.window_id}, 10)
        tabs = r.get("data") or [] if r["ok"] else []
        if not tabs:
            t.window_id = t.tab_id = None
            return False
        t.tab_id = next((x["tab_id"] for x in tabs if x.get("active")), tabs[0]["tab_id"])
        return True

    async def _page_frame(self, t: _Task) -> list:
        r = await self._call(t, "page.shot", {"window_id": t.window_id, "mode": "plain"}, 25)
        if not r["ok"]:
            return []
        return [self._frame(r["data"], "page")]

    @staticmethod
    def _frame(data: dict, kind: str, q_index=None) -> dict:
        f = {"kind": kind, "mime": data.get("mime", "image/jpeg"), "data_b64": data.get("data_b64", "")}
        if q_index is not None:
            f["q_index"] = q_index
        return f

    @staticmethod
    def _number(t: _Task, frames: list) -> list:
        return [{"frame_id": f"s{t.step}f{i + 1}", **f} for i, f in enumerate(frames)]

    # ── действие ───────────────────────────────────────────────────
    async def _do(self, t: _Task, tool: str, args: dict) -> None:
        if tool not in EXT_ACTIONS:
            t.last_result = _result("unsupported", f"неизвестный tool: {str(tool)[:40]}")
            return
        args = dict(args or {})
        action, timeout = EXT_ACTIONS[tool]
        if tool.startswith("page_") and tool != "page_shot":
            args.setdefault("tab_id", t.tab_id)
        if tool == "page_shot" and "window_id" not in args:
            args.setdefault("tab_id", t.tab_id)
        if tool == "tabs_new":
            args.setdefault("window_id", t.window_id)
            args.setdefault("active", True)
        if tool == "page_upload":
            r = self._issue_upload(args)
            if r is not None:
                t.last_result = r
                return
        r = await self._call(t, action, args, timeout)
        if _ext_lost(r) or (r["status"] == "error" and r.get("detail") in EXT_LOST):
            r = _result("error", "расширение перезапустилось — действие могло не выполниться")

        if r["ok"] and tool == "tabs_new":
            t.tab_id = (r.get("data") or {}).get("tab_id", t.tab_id)
        elif r["ok"] and tool == "tabs_activate":
            t.tab_id = args.get("tab_id", t.tab_id)
        elif r["ok"] and tool == "tabs_close" and args.get("tab_id") in (None, t.tab_id):
            await self._recover_tab(t)
        elif r["ok"] and tool == "page_shot":
            q = args.get("q_index")
            t.frames.append(self._frame(r["data"], "question" if q is not None else "page", q))
        elif r["ok"] and tool == "page_questions":
            await self._question_frames(t, (r.get("data") or {}).get("questions") or [])

        if isinstance(r.get("observe"), dict):
            t.observe = r["observe"]
        t.last_result = self._for_server(tool, r)
        log.info("[browser] task=%s step=%d tool=%s status=%s", t.task_id, t.step, tool, r["status"])

    def _issue_upload(self, args: dict) -> dict | None:
        """file/path из args → file_token (только из BROWSER_UPLOAD_DIR); отказ → результат шага."""
        if self._uploads is None:
            return _result("unsupported", "загрузка файлов не настроена (BROWSER_UPLOAD_DIR)")
        name = args.pop("file", None) or args.pop("path", None)
        try:
            args["file_token"] = self._uploads.issue(name)
        except ValueError as e:
            return _result("error", str(e))
        return None

    async def _question_frames(self, t: _Task, questions: list) -> None:
        for q in [q for q in questions if q.get("has_media")][:MAX_QUESTION_FRAMES]:
            r = await self._call(t, "page.shot", {"tab_id": t.tab_id, "crop_ref": q.get("q_ref")}, 25)
            if r["ok"]:
                t.frames.append(self._frame(r["data"], "question", q.get("index")))

    @staticmethod
    def _for_server(tool: str, r: dict) -> dict:
        """last_result без observe (уходит как observation) и без байтов кадра (уходят в frames)."""
        out = {k: v for k, v in r.items() if k != "observe"}
        if tool == "page_shot" and isinstance(out.get("data"), dict):
            out["data"] = {k: v for k, v in out["data"].items() if k != "data_b64"}
        return out

    # ── ожидания ───────────────────────────────────────────────────
    async def _wait_online(self) -> None:
        while not self._online():
            await self._sleep(self._poll)

    async def _wait_ext(self) -> bool:
        deadline = self._clock() + self._ext_wait
        while not self._ext_connected():
            if self._clock() >= deadline:
                return False
            await self._sleep(self._poll)
        return True

    async def _pause(self, t: _Task, reason: str) -> None:
        t.paused = True
        t.resume.clear()
        t.resume_local = False
        log.info("[browser] task=%s step=%d пауза", t.task_id, t.step)
        self._emit({"type": "browser_task", "task_id": t.task_id, "state": "paused", "text": reason,
                    "window_id": t.window_id})
        await t.resume.wait()
        t.paused = False
        if t.resume_local:
            while True:
                await self._wait_online()
                try:
                    await self._send({"type": "browser.resume", "task_id": t.task_id})
                    break
                except Exception:  # noqa: BLE001 — связь оборвалась во время отправки
                    await self._sleep(self._poll)
        self._emit({"type": "browser_task", "task_id": t.task_id, "state": "running", "text": "",
                    "window_id": t.window_id})
        t.last_result = _result("done", "Мастер продолжил задачу")
