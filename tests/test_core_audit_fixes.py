"""Регрессии аудита ядра (20.11.2026): гонки, обработка ошибок, остановка.

Run: python -m pytest tests/test_core_audit_fixes.py -q

Каждый тест воспроизводит найденный дефект на настоящем коде (сокет
websockets, git во временном каталоге, цикл остановки main.py); внешние
сервисы (LLM, Telegram, TTS) подменены.
"""

import asyncio
import json
import logging
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import websockets

import adapters.ws as wh
import capabilities.coding as cap_coding
import config
import main as entrypoint
import modules.state as st
import modules.tts_server as tts
import sakura_core.llm as llm
import sakura_core.registry as registry
import sakura_core.ws_protocol as proto
from modules import device_manager, presence_sync, rituals, ws_auth
from modules.ws_auth import _WS_SECRET, MAX_WS_MESSAGE_SIZE
from sakura_core import browser_step as bs
from sakura_core import browser_task as bt
from sakura_core import proto_devices, voice_turns
from sakura_core.executor import ExecutionContext, get_handler
from tests.test_llm_resilience import _Client, _mock_keys

DEV = "laptop"


# ── adapters/ws.py: голосовой ход и цикл сокета ─────────────────────────


@pytest.fixture
def ws_env(monkeypatch):
    """Настоящий ws_handler; регистрация, presence и TTS-состояние — подменены."""
    offline = []
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    monkeypatch.setattr(device_manager, "set_device_offline",
                        lambda d: offline.append(("device", d)))
    monkeypatch.setattr(presence_sync, "set_offline",
                        lambda d: offline.append(("presence", d)))
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    monkeypatch.setattr(ws_auth, "is_master_device", lambda d: d == DEV)
    monkeypatch.setattr(voice_turns, "_last", {})
    monkeypatch.setattr(tts, "_last_end", {})
    yield offline
    st.connected_devices.clear()
    st.connected_devices.update(saved)


async def _serve(scenario):
    async with websockets.serve(wh.ws_handler, "127.0.0.1", 0,
                                max_size=MAX_WS_MESSAGE_SIZE,
                                ping_interval=None) as server:
        port = server.sockets[0].getsockname()[1]
        return await asyncio.wait_for(scenario(f"ws://127.0.0.1:{port}"), 10)


async def _until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "условие на сервере не наступило"
        await asyncio.sleep(0.02)


def test_superseding_voice_turn_runs_voice_handler_even_if_ping_follows(ws_env, monkeypatch):
    """Голосовой ход, который вытесняет прежний, исполняется своим обработчиком.

    Фабрику хода voice_turns зовёт после вытеснения прежнего хода (до 3 с);
    цикл сокета тем временем читает ping (он идёт на каждую смену окна).
    Лямбда хода брала handler из замыкания цикла — второй ход уходил в
    handle_ping с данными голосовой команды и молча пропадал."""
    calls = []

    async def voice(websocket, data, ctx):
        calls.append(("voice", data.get("text")))
        try:
            await asyncio.sleep(5)
        finally:
            # Отмена хода дорабатывает свой finally — окно, в которое
            # цикл сокета успевает разобрать следующее сообщение.
            await asyncio.sleep(0.3)

    async def ping(websocket, data, ctx):
        calls.append(("ping", data.get("text")))

    monkeypatch.setattr(wh, "handle_voice_command", voice)
    monkeypatch.setattr(wh, "handle_ping", ping)

    async def scenario(uri):
        async with websockets.connect(uri, max_size=None) as c:
            async def send(msg):
                await c.send(json.dumps({"token": _WS_SECRET, "device_id": DEV, **msg}))
            await send({"type": "register"})
            await send({"type": "voice_command", "text": "первый"})
            await _until(lambda: ("voice", "первый") in calls)
            await send({"type": "voice_command", "text": "второй"})
            await send({"type": "ping"})
            await _until(lambda: ("voice", "второй") in calls or ("ping", "второй") in calls)
            await asyncio.sleep(0.1)

    asyncio.run(_serve(scenario))
    assert ("voice", "второй") in calls
    assert ("ping", "второй") not in calls
    assert ("ping", None) in calls          # сам ping обработан как ping


def test_disconnect_cleanup_survives_failing_status_push(ws_env, monkeypatch, caplog):
    """Сбой пуша статуса при отключении не оставляет устройство «онлайн»."""
    async def broken_push(device_id):
        raise RuntimeError("push failed")

    monkeypatch.setattr(proto_devices, "on_disconnect", broken_push)

    async def scenario(uri):
        c = await websockets.connect(uri, max_size=None)
        await c.send(json.dumps({"type": "register", "token": _WS_SECRET, "device_id": DEV}))
        await _until(lambda: DEV in st.connected_devices)
        await c.close()
        await _until(lambda: len(ws_env) == 2)

    with caplog.at_level(logging.WARNING):
        asyncio.run(_serve(scenario))
    assert sorted(ws_env) == [("device", DEV), ("presence", DEV)]
    assert "пуш отключения: RuntimeError: push failed" in caplog.text


# ── sakura_core/llm.py: пустые реплики, стрим, HTTP-таймаут ─────────────


def test_build_contents_skips_empty_history_parts(monkeypatch):
    """Пустая часть в contents — 400 у Gemini на каждом запросе с этой историей."""
    import memory.memory as mem
    import modules.intimacy_mode as im
    monkeypatch.setattr(mem, "get_history", lambda: [
        {"role": "user", "parts": ["привет"]},
        {"role": "model", "parts": [""]},
        {"role": "model", "parts": ["   "]},
        {"role": "model", "parts": []},
        {"role": "user", "parts": ["как дела"]},
    ])
    monkeypatch.setattr(im, "dialogue", lambda channel=None: [("model", "")])
    contents = llm._build_contents("вопрос", channel="voice")
    texts = [c.parts[0].text for c in contents]
    assert texts == ["привет", "как дела", "вопрос"]


def test_empty_voice_reply_is_not_saved_to_history(monkeypatch):
    """Пустой ответ модели не пишется в историю (иначе петля 400 → пусто)."""
    import memory.memory as mem
    import modules.intimacy_mode as im
    import modules.mood_broadcast as mood_broadcast
    import modules.web_search as web_search
    saved = []
    monkeypatch.setattr(config, "get_active_key", lambda: "k")
    monkeypatch.setattr(config, "mark_key_used", lambda k: None)

    async def _bs(query="", profile="full", channel=None):
        return "system"

    monkeypatch.setattr(llm, "_build_system", _bs)
    monkeypatch.setattr(llm, "_build_contents", lambda *a, **k: [])
    monkeypatch.setattr(llm, "_vision_followup", lambda text: (None, ""))
    monkeypatch.setattr(llm, "generate", AsyncMock(return_value=""))
    monkeypatch.setattr(web_search, "needs_search", lambda t: False)
    monkeypatch.setattr(mem, "add_to_history", lambda role, text: saved.append((role, text)))
    monkeypatch.setattr(im, "is_active", lambda channel=None: False)
    monkeypatch.setattr(im, "is_intimate_content", lambda text: False)
    monkeypatch.setattr(mood_broadcast, "broadcast_mood_after_reply", AsyncMock())

    async def run():
        out = await llm.ask_gemini_voice("вопрос", websocket=None)
        await asyncio.sleep(0)
        return out

    text, _emotion = asyncio.run(run())
    assert text == ""
    assert saved == [("user", "вопрос")]


def test_stream_hung_first_model_leaves_budget_for_fallback(monkeypatch):
    """Стрим: первая модель без первого токена за долю бюджета — к запасной.

    Раньше срок у стрима был один на всю цепочку: зависшая первая модель
    съедала весь голосовой ход, запасная не звалась."""
    _mock_keys(monkeypatch)
    calls = []

    class Models:
        def generate_content_stream(self, *, model, **_kwargs):
            calls.append(model)
            if model == "model-a":
                time.sleep(1.5)
                yield SimpleNamespace(text="too late")
                return
            yield SimpleNamespace(text="fallback")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def measure():
        started = time.monotonic()
        tokens = [t async for t in llm.stream_tokens(
            "hello", chain=("model-a", "model-b"), timeout=1.0)]
        return tokens, time.monotonic() - started

    tokens, elapsed = asyncio.run(measure())
    assert tokens == ["fallback"]
    assert calls == ["model-a", "model-b"]
    assert elapsed < 1.0 + 0.2


def test_stream_answer_started_on_first_model_is_read_to_the_end(monkeypatch):
    """Доля бюджета — только до первого токена: начатый ответ дочитывается."""
    _mock_keys(monkeypatch)

    class Models:
        def generate_content_stream(self, *, model, **_kwargs):
            yield SimpleNamespace(text="раз ")
            time.sleep(0.4)          # дольше доли бюджета (0,6 × 0,5 с) от старта
            yield SimpleNamespace(text="два")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def collect():
        return [t async for t in llm.stream_tokens(
            "hello", chain=("model-a", "model-b"), timeout=0.5 + 0.4)]

    assert asyncio.run(collect()) == ["раз ", "два"]


@pytest.mark.parametrize("api", ["generate", "stream"])
def test_llm_calls_carry_http_timeout(monkeypatch, api):
    """У синхронного вызова в потоке есть HTTP-таймаут: wait_for поток не
    останавливает, а genai.Client по умолчанию ждёт ответа сколько угодно."""
    _mock_keys(monkeypatch)
    seen = []

    class Models:
        def generate_content(self, *, model, contents, config):
            seen.append(config.http_options.timeout)
            return SimpleNamespace(text="ok")

        def generate_content_stream(self, *, model, contents, config):
            seen.append(config.http_options.timeout)
            yield SimpleNamespace(text="ok")

    monkeypatch.setattr(llm, "get_client", lambda _key: _Client(Models()))

    async def call():
        if api == "generate":
            return await llm.generate("hello", chain=("gemma-4-26b-a4b-it",), timeout=3.0)
        return "".join([t async for t in llm.stream_tokens(
            "hello", chain=("gemma-4-26b-a4b-it",), timeout=3.0)])

    assert asyncio.run(call()) == "ok"
    # Gemma: filter_params режет незнакомые параметры — http_options добавляется после.
    assert len(seen) == 1 and 0 < seen[0] <= (3.0 + llm.HTTP_TIMEOUT_SLACK_S) * 1000


# ── sakura_core/browser_step.py: сбой шага ─────────────────────────────


class _RecWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.fixture
def browser_env(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "TASKS_DIR", tmp_path / "browser_tasks")
    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    monkeypatch.setattr(bs, "_loaded", True)
    bt.reset()

    async def quiet(*a, **k):
        return SimpleNamespace(message_id=1)

    monkeypatch.setattr(bs, "tg_send", quiet)
    monkeypatch.setattr(bs, "orb", quiet)
    ws = _RecWS()
    monkeypatch.setattr(st, "connected_devices", {"pc": ws})
    yield ws
    bt.reset()


def test_browser_step_server_error_answers_and_fails_task(browser_env, monkeypatch):
    """Непредвиденная ошибка шага: ответ desktop и задача закрыта.

    Раньше исключение уходило в задачу spawn: запрос оставался без ответа
    (desktop ждёт ≥ 5 мин и шлёт шаг снова), задача висела running."""
    task = bt.new_task("тест", device_id="pc")

    async def broken(*a, **k):
        raise KeyError("questions")

    monkeypatch.setattr(bs, "decide", broken)
    asyncio.run(bs.handle_step(browser_env, {"request_id": "r1", "task_id": task.task_id,
                                             "step": 0, "observation": {}}))
    reply = browser_env.sent[-1]
    assert reply["type"] == "browser_step" and reply["request_id"] == "r1"
    assert reply["status"] == "fail" and "внутренняя ошибка сервера" in reply["reason"]
    assert task.state == "fail" and not task.active
    assert task.task_id not in bs._locks


def test_browser_cancel_drops_step_lock(browser_env):
    """Отмена мимо handle_step (стоп, новая задача в окне) снимает замок шага."""
    task = bt.new_task("тест", device_id="pc")
    bs._locks[task.task_id] = asyncio.Lock()
    assert asyncio.run(bs.cancel(task, "стоп")) is True
    assert task.task_id not in bs._locks


# ── sakura_core/ws_protocol.py: LLM не держит цикл сокета ──────────────


class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self, *a, **k):
        pass


def _slow_llm(reply="Привет, Мастер", delay=0.4):
    calls = []

    async def ask(prompt, **kw):
        calls.append(prompt)
        await asyncio.sleep(delay)
        return reply
    ask.calls = calls
    return ask


@pytest.fixture
def proto_env(monkeypatch):
    monkeypatch.setattr(st, "connected_devices", {})
    monkeypatch.setattr(proto, "_bg_replies", {})
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "is_master_device", lambda d: True)
    monkeypatch.setattr(proto, "_scenario_hook", AsyncMock())
    monkeypatch.setattr(proto, "announce_presence_transfer", AsyncMock())
    monkeypatch.setattr(proto_devices, "on_heartbeat", AsyncMock())


def test_register_does_not_wait_for_greeting(proto_env, monkeypatch):
    """Приветствие первого за день подключения — фоном, register не ждёт LLM."""
    monkeypatch.setattr(proto, "should_greet_device", lambda d: True)
    ask = _slow_llm()
    bot = SimpleNamespace(send_message=AsyncMock())
    ctx = {"ask_gemini": ask, "bot": bot}

    async def run():
        started = time.monotonic()
        await proto.handle_register(_WS(), {"type": "register", "device_id": DEV}, ctx)
        took = time.monotonic() - started
        await asyncio.sleep(0.6)
        return took

    took = asyncio.run(run())
    assert took < 0.3
    assert DEV in st.connected_devices
    bot.send_message.assert_awaited_once_with(config.MASTER_ID, "Привет, Мастер")


def test_register_without_device_id_is_ignored(proto_env, monkeypatch):
    """register без device_id не кладёт сокет в connected_devices[None]."""
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    ctx = {"ask_gemini": _slow_llm(), "bot": SimpleNamespace(send_message=AsyncMock())}
    asyncio.run(proto.handle_register(_WS(), {"type": "register"}, ctx))
    asyncio.run(proto.handle_ping(_WS(), {"type": "ping", "device_id": None}, ctx))
    assert st.connected_devices == {}


def test_ping_music_comment_runs_in_background_once(proto_env, monkeypatch):
    """Комментарий к музыке: ping не ждёт LLM, второй ping дубль не запускает."""
    marked = []
    monkeypatch.setattr(proto, "watcher_update", lambda *a, **k: None)
    monkeypatch.setattr(proto, "track_rec_activity", lambda *a, **k: None)
    monkeypatch.setattr(proto, "get_current_game", AsyncMock())
    monkeypatch.setattr(proto, "should_comment_music", lambda: True)
    monkeypatch.setattr(proto, "get_current_music_from_window", lambda w: "Артист — Трек")
    monkeypatch.setattr(proto, "db_get_memory_context", lambda: "память")
    monkeypatch.setattr(proto, "mark_music_commented", lambda: marked.append(1))
    monkeypatch.setattr(proto, "check_pc_health", lambda s: None)
    monkeypatch.setattr(st, "_last_command_ts", 0.0)
    ask = _slow_llm(reply="Хороший трек")
    bot = SimpleNamespace(send_message=AsyncMock())
    ctx = {"ask_gemini": ask, "bot": bot}
    data = {"type": "ping", "device_id": DEV, "active_window": "Яндекс Музыка",
            "system_info": {}}

    async def run():
        started = time.monotonic()
        await proto.handle_ping(_WS(), dict(data), ctx)
        await proto.handle_ping(_WS(), dict(data), ctx)
        took = time.monotonic() - started
        await asyncio.sleep(0.6)
        return took

    took = asyncio.run(run())
    assert took < 0.3
    assert len(ask.calls) == 1
    bot.send_message.assert_awaited_once_with(config.MASTER_ID, "Хороший трек")
    assert marked == [1]


def test_command_result_with_object_result_does_not_crash(proto_env):
    """result объектом (не строкой) не роняет разбор command_result."""
    ctx = {"ask_gemini": _slow_llm(), "bot": SimpleNamespace(send_message=AsyncMock()),
           "_resolve_command_status": lambda dev, ok, detail: "executed"}
    asyncio.run(proto.handle_command_result(
        _WS(), {"type": "command_result", "device_id": DEV, "result": {"ok": True}}, ctx))


def test_action_desc_reads_registry_once(monkeypatch):
    """desc для пересказа результата — из кэша, не load() на каждый ответ."""
    loads = []
    real_load = registry.load

    def counting_load(*a, **k):
        loads.append(1)
        return real_load(*a, **k)

    monkeypatch.setattr(registry, "load", counting_load)
    monkeypatch.setattr(registry, "_desc_index", None)
    first = registry.action_desc("coding.git_status")
    assert registry.action_desc("coding.git_status") == first == "Показать git статус"
    assert registry.action_desc("нет.такого") == "нет.такого"
    assert loads == [1]


# ── capabilities/coding.py: секреты ────────────────────────────────────


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, shell=False,
                          capture_output=True, text=True).stdout


def test_coding_commit_never_stages_secrets(tmp_path, monkeypatch):
    """«Закоммить» по голосу не забирает .env.bak-*, дампы и сессии.

    В рабочем дереве прода лежат неигнорируемые .env.bak-* и memory/backup/:
    `git add -A` отправил бы их в историю репозитория."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "tracked.txt").write_text("v1\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("KEY=\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "--quiet", "-m", "init")

    (tmp_path / "tracked.txt").write_text("v2\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("KEY=\nOTHER=\n", encoding="utf-8")
    (tmp_path / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env.bak-20261117").write_text("KEY=secret\n", encoding="utf-8")
    (tmp_path / "sakura.session").write_bytes(b"session")
    (tmp_path / "memory" / "backup").mkdir(parents=True)
    (tmp_path / "memory" / "backup" / "dump.json").write_text("{}", encoding="utf-8")
    (tmp_path / "memory" / "chat.db").write_bytes(b"db")
    monkeypatch.setattr(cap_coding, "PROJECT_DIR", str(tmp_path))

    text, ok = asyncio.run(cap_coding.git_commit_result("правки"))
    assert ok is True, text
    committed = set(_git(tmp_path, "show", "--name-only", "--format=", "HEAD").split())
    assert committed == {"tracked.txt", ".env.example", "new_module.py"}
    untracked = _git(tmp_path, "status", "--porcelain", "--untracked-files=all")
    assert ".env.bak-20261117" in untracked and "sakura.session" in untracked


def test_coding_read_file_refuses_secrets_and_caps_size(tmp_path, monkeypatch):
    secret = tmp_path / ".env.bak-1"
    secret.write_text("GEMINI_KEY=секрет\n", encoding="utf-8")
    handler = get_handler("coding.read_file")
    text, ok = asyncio.run(handler(ExecutionContext(param=str(secret))))
    assert ok is False and "секрет" not in text.replace("секреты", "")

    template = tmp_path / ".env.example"
    template.write_text("GEMINI_KEY=\n", encoding="utf-8")
    text, ok = asyncio.run(handler(ExecutionContext(param=str(template))))
    assert ok is True and "GEMINI_KEY=" in text

    monkeypatch.setattr(cap_coding, "READ_MAX_CHARS", 10)
    big = tmp_path / "big.py"
    big.write_text("x" * 50, encoding="utf-8")
    text, ok = asyncio.run(handler(ExecutionContext(param=str(big))))
    assert ok is True and text.startswith("x" * 10) and "x" * 11 not in text


# ── main.py: падение критической поверхности ───────────────────────────


def test_critical_surface_failure_still_runs_shutdown_steps():
    """Упал polling: соседи сняты, шаги остановки и закрытие SQLite выполнены,
    ошибка наружу. Раньше ошибка уходила сразу — без закрытия БД и сокетов."""
    calls = []

    async def broken():
        await asyncio.sleep(0)
        raise RuntimeError("polling died")

    async def websocket_surface():
        try:
            await asyncio.Event().wait()
        finally:
            calls.append("websocket.cancelled")

    async def background():
        await asyncio.Event().wait()

    async def scenario():
        with pytest.raises(RuntimeError, match="polling died"):
            await entrypoint.run_services_until_stopped(
                broken(), websocket_surface(), [("bg", background())], asyncio.Event(),
                [("service components", lambda: calls.append("graceful"))],
                [("sqlite", lambda: calls.append("sqlite"))],
            )

    asyncio.run(scenario())
    assert calls == ["graceful", "websocket.cancelled", "sqlite"]
