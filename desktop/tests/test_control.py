"""Управление ПК (п. 2.3–2.6) на подставном платформенном слое: ничего настоящего не выполняется."""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from desktop.core.control import registry as reg
from desktop.core.control import safety


class FakePlatform:
    def __init__(self, fg=None, password=False):
        self.calls = []
        self.wins = [{"hwnd": 1, "title": "Документ — Блокнот", "process": "notepad.exe"},
                     {"hwnd": 2, "title": "Почта — Google Chrome", "process": "chrome.exe"}]
        self.fg = fg if fg is not None else self.wins[0]
        self.password = password

    def windows(self):
        return self.wins

    def foreground_window(self):
        return self.fg

    def __getattr__(self, name):  # window_show, window_snap, power, display_off, … — записать вызов
        def f(*a):
            self.calls.append((name, a))
            return {"mic_mute": True, "set_brightness": True, "radio": True, "recycle": True, "reveal": True,
                    "window_show": True, "window_snap": True, "window_to_monitor": True,
                    "activate_window_handle": True, "open_path": True}.get(name)
        return f

    def focused_is_password(self):
        return self.password


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    def write(self, text, interval=0):
        self.calls.append(("write", text))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))


def ctx(**kw):
    clip = {"text": "секрет"}
    procs = [{"pid": 10, "name": "notepad.exe", "memory_mb": 50}, {"pid": 4, "name": "explorer.exe", "memory_mb": 90},
             {"pid": 11, "name": "chrome.exe", "memory_mb": 900}]
    killed = []
    c = reg.Ctx(platform=kw.get("platform") or FakePlatform(), keyboard=FakeKeyboard(),
                clipboard=SimpleNamespace(copy=lambda t: clip.update(text=t), paste=lambda: clip["text"]),
                processes=lambda: procs, kill=lambda pid: killed.append(pid) or True,
                files=SimpleNamespace(open_file=lambda n: f"открыл файл {n}", find=lambda n: f"C:/x/{n}" if n else None,
                                      recent=lambda: ["отчёт", "фото"]),
                fs=SimpleNamespace(copy=lambda s, d: clip.update(copied=(s, d)),
                                   move=lambda s, d: clip.update(moved=(s, d))))
    c.extra = {"clip": clip, "killed": killed}
    return c


def run(action, arg="", confirmed=False, c=None):
    return reg.execute(action, arg, confirmed, ctx=c or ctx(), limiter=safety.RateLimiter(limit=1000))


# ── окна ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("action,call", [("window.minimize", ("window_show", (1, "minimize"))),
                                         ("window.maximize", ("window_show", (1, "maximize"))),
                                         ("window.restore", ("window_show", (1, "restore")))])
def test_window_states_on_active(action, call):
    c = ctx()
    assert run(action, c=c)["ok"] is True
    assert c.platform.calls == [call]


def test_window_by_title_snap_monitor_focus_list():
    c = ctx()
    assert run("window.snap", "left:chrome", c=c)["ok"] is True
    assert c.platform.calls[-1] == ("window_snap", (2, "left"))
    assert run("window.snap", "влево", c=c)["ok"] is True
    assert run("window.snap", "diagonal", c=c)["status"] == "failed"
    assert run("window.move_monitor", "next", c=c)["ok"] is True
    assert run("window.focus", "почта", c=c)["ok"] is True
    assert c.platform.calls[-1] == ("activate_window_handle", (2,))
    assert run("window.focus", "нет такого", c=c)["status"] == "failed"
    out = run("window.list", c=c)
    assert out["windows"] == ["Документ — Блокнот", "Почта — Google Chrome"]


# ── питание (подставной исполнитель) ─────────────────────────────────
def test_power_lock_display_off_sleep_confirm():
    c = ctx()
    assert run("power.lock", c=c)["ok"] is True and ("power", ("lock",)) in c.platform.calls
    assert run("power.display_off", c=c)["ok"] is True
    assert run("power.sleep", c=c) == {"ok": False, "status": "unsupported", "detail": "нужно подтверждение"}
    assert ("power", ("sleep",)) not in c.platform.calls
    assert run("power.sleep", confirmed=True, c=c)["ok"] is True


# ── процессы ─────────────────────────────────────────────────────────
def test_process_list_and_kill_with_confirm_and_protection():
    c = ctx()
    out = run("process.list", c=c)
    assert out["processes"][0]["name"] == "chrome.exe"
    assert run("process.kill", "notepad", c=c)["detail"] == "нужно подтверждение"
    assert c.extra["killed"] == []
    assert run("process.kill", "notepad", confirmed=True, c=c)["ok"] is True
    assert c.extra["killed"] == [10]
    assert run("process.kill", "explorer", confirmed=True, c=c)["status"] == "unsupported"
    assert run("process.kill", "nope", confirmed=True, c=c)["status"] == "failed"


# ── буфер обмена ─────────────────────────────────────────────────────
def test_clipboard_read_write_clear():
    c = ctx()
    assert run("clipboard.read", c=c)["detail"] == "секрет"
    run("clipboard.write", "привет", c=c)
    assert c.extra["clip"]["text"] == "привет"
    run("clipboard.clear", c=c)
    assert run("clipboard.read", c=c)["detail"] == "буфер обмена пуст"


# ── экран, звук, сеть ─────────────────────────────────────────────────
def test_display_audio_net():
    c = ctx()
    assert run("display.brightness", "70", c=c)["detail"] == "яркость 70%"
    assert run("display.brightness", "ярко", c=c)["status"] == "failed"
    night = run("display.night_light", "on", c=c)
    assert night["status"] == "unsupported" and ("open_path", ("ms-settings:nightlight",)) in c.platform.calls
    assert run("audio.mic_mute", "on", c=c)["detail"] == "микрофон выключен"
    assert run("net.bluetooth", "off", c=c)["ok"] is True
    assert run("net.wifi", "off", c=c)["detail"] == "нужно подтверждение"
    assert run("net.wifi", "off", confirmed=True, c=c)["ok"] is True


# ── клавиатура: белый список, чёрный список окон, поля паролей ─────────
@pytest.mark.parametrize("combo,ok", [("Ctrl+C", True), ("ctrl + v", True), ("Win+D", True), ("alt+tab", True),
                                      ("PrtSc", True), ("ctrl+alt+del", False), ("win+r", False), ("alt+f4", False)])
def test_hotkey_whitelist(combo, ok):
    c = ctx()
    assert run("keys.hotkey", combo, c=c)["ok"] is ok
    assert bool(c.keyboard.calls) is ok


def test_type_never_into_password_or_blocked_window():
    c = ctx(platform=FakePlatform(password=True))
    assert run("keys.type", "пароль123", c=c)["detail"] == "поле пароля — не ввожу"
    assert c.keyboard.calls == []
    c = ctx(platform=FakePlatform(fg={"hwnd": 9, "title": "KeePassXC", "process": "keepassxc.exe"}))
    assert run("keys.type", "текст", c=c)["detail"] == "это окно в чёрном списке — ввод запрещён"
    assert run("keys.hotkey", "ctrl+v", c=c)["status"] == "unsupported"
    assert c.keyboard.calls == []
    c = ctx()
    out = run("keys.type", "привет", c=c)
    assert out["ok"] is True and "привет" not in out["detail"]


def test_blocklist_from_env(monkeypatch):
    monkeypatch.setenv("WINDOW_BLOCKLIST", "Блокнот, steam")
    c = ctx()
    assert run("keys.type", "x", c=c)["status"] == "unsupported"


def test_media_keys():
    c = ctx()
    assert run("keys.media", "next", c=c)["ok"] is True
    assert run("keys.media", "launch", c=c)["status"] == "failed"


# ── файлы ────────────────────────────────────────────────────────────
def test_files():
    c = ctx()
    assert run("files.open", "отчёт", c=c)["ok"] is True
    assert run("files.reveal", "отчёт", c=c)["ok"] is True
    assert run("files.recent", c=c)["files"] == ["отчёт", "фото"]
    assert run("files.copy", "отчёт|D:/копия", c=c)["ok"] is True
    assert c.extra["clip"]["copied"] == ("C:/x/отчёт", "D:/копия")
    assert run("files.copy", "отчёт", c=c)["status"] == "failed"
    assert run("files.move", "отчёт|D:/", c=c)["detail"] == "нужно подтверждение"
    assert run("files.delete", "отчёт", c=c)["detail"] == "нужно подтверждение"
    # удаление по имени запрещено — только полный существующий путь
    assert run("files.delete", "отчёт", confirmed=True, c=c)["status"] == "failed"
    assert not any(call[0] == "recycle" for call in c.platform.calls)


# ── общие правила ────────────────────────────────────────────────────
def test_destructive_need_confirm_and_flags():
    destructive = {"power.sleep", "process.kill", "net.wifi", "files.move", "files.delete"}
    assert {k for k, a in reg.ACTIONS.items() if a.confirm} == destructive
    assert all(not reg.ACTIONS[k].reversible for k in ("process.kill", "files.move", "keys.type"))


def test_rate_limit_5_per_second():
    t = [0.0]
    lim = safety.RateLimiter(limit=5, window=1.0, clock=lambda: t[0])
    c = ctx()
    res = [reg.execute("window.list", "", False, ctx=c, limiter=lim)["ok"] for _ in range(6)]
    assert res == [True] * 5 + [False]
    t[0] = 1.01
    assert reg.execute("window.list", "", False, ctx=c, limiter=lim)["ok"] is True


def test_journal_has_no_text(caplog):
    caplog.set_level(logging.INFO, logger="sakura.actions")
    run("keys.type", "секретный текст")
    run("clipboard.write", "тайна")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "keys.type" in text and "секретный" not in text and "тайна" not in text


def test_errors_become_honest_statuses():
    class Broken(FakePlatform):
        def display_off(self):
            raise NotImplementedError

        def mic_mute(self, m):
            raise PermissionError
    c = ctx(platform=Broken())
    assert run("power.display_off", c=c)["detail"] == "недоступно на этой системе"
    assert run("audio.mic_mute", c=c)["status"] == "unsupported"
    assert run("nope.action", c=c)["status"] == "unsupported"


# ── интеграция: команда сервера → агент → command_result ───────────────
def test_agent_runs_control_action_and_reports(monkeypatch):
    from desktop.core import agent as agent_mod
    sent, events = [], []

    class WS:
        async def send(self, raw):
            sent.append(json.loads(raw))
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a._ws = WS()
    a.bus = SimpleNamespace(emit=lambda ev, **k: events.append((ev, k)))
    a.media = None
    from desktop.core import control
    def fake_execute(action, arg, confirmed):
        return {"ok": confirmed, "status": "done" if confirmed else "unsupported", "detail": f"{action}:{arg}"}
    monkeypatch.setattr(control, "execute", fake_execute)
    asyncio.run(a._run_command("files.delete", "c1", "отчёт", confirmed=True))
    asyncio.run(a._run_command("process.kill", "c2", "notepad"))
    results = [m for m in sent if m["type"] == "command_result"]
    assert [(r["id"], r["ok"], r["status"]) for r in results] == [("c1", True, "done"), ("c2", False, "unsupported")]
    assert ("pc_action", {"active": True}) in events and ("pc_action", {"active": False}) in events


# ── UI Automation (п. 3.3) ─────────────────────────────────────────────
class FakeUI:
    def __init__(self):
        self.calls = []
        self.fields = {"Поиск": "edit", "Пароль": "password", "Адрес": "readonly"}

    def click(self, name):
        self.calls.append(("click", name))
        return True if name == "OK" else None

    def type_into(self, name, text):
        self.calls.append(("type", name))
        kind = self.fields.get(name, "")
        fallback = "not_found" if name else "done"
        return {"edit": "done", "password": "password", "readonly": "readonly"}.get(kind, fallback)

    def scroll(self, direction, pages):
        self.calls.append(("scroll", direction, pages))
        return True

    def read(self, name):
        return "Привет, мир" if not name else ""


def uictx(**kw):
    c = ctx(**kw)
    c.ui = FakeUI()
    return c


def test_ui_click_type_scroll_read():
    c = uictx()
    assert run("ui.click", "OK", c=c)["ok"] is True
    assert run("ui.click", "Нет такой", c=c)["status"] == "failed"
    assert run("ui.click", "", c=c)["status"] == "failed"
    assert run("ui.type", "Поиск|котики", c=c)["ok"] is True
    assert run("ui.type", "просто текст", c=c)["ok"] is True and c.ui.calls[-1] == ("type", "")
    assert run("ui.type", "Пароль|123", c=c)["detail"] == "поле пароля — не ввожу"
    assert run("ui.type", "Адрес|x", c=c)["status"] == "failed"
    assert run("ui.scroll", "вниз:3", c=c)["ok"] is True and c.ui.calls[-1] == ("scroll", "down", 3)
    assert run("ui.scroll", "up:99", c=c)["ok"] is True and c.ui.calls[-1] == ("scroll", "up", 10)
    assert run("ui.scroll", "по диагонали", c=c)["status"] == "failed"
    out = run("ui.read", c=c)
    assert out["text"] == "Привет, мир"
    assert run("ui.read", "кнопка", c=c)["status"] == "failed"


def test_ui_blocked_window_and_unavailable():
    c = uictx(platform=FakePlatform(fg={"hwnd": 9, "title": "Bitwarden", "process": "bitwarden.exe"}))
    for action, arg in (("ui.click", "OK"), ("ui.type", "Поиск|x"), ("ui.scroll", "down"), ("ui.read", "")):
        assert run(action, arg, c=c)["status"] == "unsupported"
    assert c.ui.calls == []
    c = ctx()  # без UI Automation (не Windows)
    assert run("ui.read", c=c)["detail"] == "недоступно на этой системе"


def test_ui_read_text_not_in_journal(caplog):
    caplog.set_level(logging.INFO, logger="sakura.actions")
    run("ui.read", c=uictx())
    assert "Привет" not in " ".join(r.getMessage() for r in caplog.records)


# ── живая проверка: run_action отдаёт результат раннеру, а не серверу ──
def test_local_result_not_sent_to_server():
    from desktop.core import agent as agent_mod
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(raw)

    async def go():
        a = agent_mod.Agent.__new__(agent_mod.Agent)
        a._ws = WS()
        a.bus = None
        fut = asyncio.get_running_loop().create_future()
        a._local_results = {"local:1": fut}
        await a._send_result("local:1", {"ok": True, "status": "done", "detail": "x"}, {"windows": []})
        return await fut
    res = asyncio.run(go())
    assert res == {"ok": True, "status": "done", "detail": "x", "windows": []} and sent == []


def test_run_action_only_with_livecheck_env(monkeypatch):
    from desktop.core import service
    names = []

    def collect(env):
        names.clear()
        if env:
            monkeypatch.setenv("SAKURA_LIVECHECK", "1")
        else:
            monkeypatch.delenv("SAKURA_LIVECHECK", raising=False)
        fake = SimpleNamespace(api=SimpleNamespace(command=lambda k, h: names.append(k)), media=None)
        for attr in dir(service.CoreService):
            if attr.startswith("cmd_"):
                setattr(fake, attr, None)
        service.CoreService._register_commands(fake)
        return set(names)
    assert "run_action" not in collect(False)
    assert "run_action" in collect(True)


def test_livecheck_device_id_wins_over_dotenv(monkeypatch):
    import importlib

    from desktop.core import config
    monkeypatch.setenv("DEVICE_ID", "mostech")
    monkeypatch.setenv("SAKURA_DEVICE_ID", "mostech-check")
    try:
        assert importlib.reload(config).DEVICE_ID == "mostech-check"
    finally:
        monkeypatch.delenv("SAKURA_DEVICE_ID")
        importlib.reload(config)


def test_mic_off_from_start(monkeypatch):
    import inspect

    from desktop.core import hearing
    src = inspect.getsource(hearing)
    assert 'self.mic_enabled   = os.getenv("SAKURA_MIC_OFF") != "1"' in src


def test_offline_core_never_connects_to_vps(monkeypatch):
    from desktop.core import agent as agent_mod
    from desktop.core import config
    events, started = [], []
    monkeypatch.setattr(config, "OFFLINE", True)
    monkeypatch.setattr(config, "WS_TOKEN", "")

    def no_connect(*a, **k):
        raise AssertionError("в режиме offline подключения к VPS быть не должно")
    monkeypatch.setattr(agent_mod.websockets, "connect", no_connect)
    monkeypatch.setattr(agent_mod, "_EXTENSION_SERVER", "нет-такого-файла.py")
    monkeypatch.setattr(agent_mod, "init_index", lambda: None)
    monkeypatch.setattr(agent_mod, "spawn", lambda coro, name="": (started.append(name), coro.close()))
    import desktop.core.presence as presence
    monkeypatch.setattr(presence, "prime_system_info", lambda: None)
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a.bus = SimpleNamespace(emit=lambda ev, **k: events.append((ev, k)))
    a.hearing = SimpleNamespace(start=lambda: started.append("hearing"))
    a.server_link = None

    async def go():
        try:
            await asyncio.wait_for(a.run(), timeout=0.3)
        except asyncio.TimeoutError:
            pass
    asyncio.run(go())
    assert ("connection", {"online": False}) in events
    assert "hearing" in started and "agent-heartbeat" not in started and "screen-analysis-loop" not in started


def test_no_server_flag_sets_offline(monkeypatch):
    from desktop.core import __main__ as entry
    from desktop.core import config
    monkeypatch.setenv("SAKURA_OFFLINE", "0")  # monkeypatch вернёт окружение после main()
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(entry, "setup_logging", lambda d: None)
    monkeypatch.setattr(entry, "SingleInstance", lambda p: SimpleNamespace(acquire=lambda: False, owner_pid=lambda: 1))
    import desktop.core.exception_hooks as hooks
    monkeypatch.setattr(hooks, "install_exception_hooks", lambda log: None)
    assert entry.main(["--no-server"]) == entry.EXIT_ALREADY_RUNNING
    assert config.OFFLINE is True


@pytest.mark.parametrize("action,arg,expected", [
    ("volume", "40", "volume:40"),            # как шлёт сервер
    ("system.volume", "40", "volume:40"),     # id реестра
    ("system.volume", "+10", "volume_up:10"),
    ("system.volume", "-5", "volume_down:5"),
])
def test_system_volume_synonym(action, arg, expected, monkeypatch):
    from desktop.core import agent as agent_mod
    from desktop.core import hands
    seen, applied = [], []
    monkeypatch.setattr(agent_mod, "execute_command", lambda full: seen.append(full) or {"result": "Громкость"})
    monkeypatch.setattr(hands, "set_volume", lambda v: applied.append(("set", v)) or "ok")
    monkeypatch.setattr(hands, "nudge_volume", lambda d: applied.append(("nudge", d)) or "ok")
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a._ws, a.bus, a.media, a.server_link = None, None, None, None
    asyncio.run(a._run_command(action, None, arg))
    assert seen == [expected]
    hands.execute_command(expected)
    assert applied == [{"volume:40": ("set", 40), "volume_up:10": ("nudge", 10),
                        "volume_down:5": ("nudge", -5)}[expected]]


def test_core_exits_when_parent_window_gone():
    from desktop.core.__main__ import watch_parent
    alive, exited = {1234}, []
    watch_parent(1234, pid_exists=lambda p: p in alive, exit_fn=exited.append, once=True)
    assert exited == []
    alive.clear()
    watch_parent(1234, pid_exists=lambda p: p in alive, exit_fn=exited.append, once=True)
    assert exited == [0]



def test_delete_never_by_fuzzy_index_match(tmp_path):
    """Живая проверка 14.10: индекс на «copy.txt» вернул cpu.txt — удаляться должен только точный путь."""
    real = tmp_path / "copy.txt"
    real.write_text("x")
    c = ctx()
    c.files = SimpleNamespace(find=lambda n: r"C:\\sakura-tmp\\cpu.txt", open_file=lambda n: "", recent=lambda: [])
    assert run("files.delete", "copy.txt", confirmed=True, c=c)["status"] == "failed"
    assert run("files.reveal", "copy.txt", c=c)["status"] == "failed"
    assert run("files.copy", f"copy.txt|{tmp_path / 'b.txt'}", c=c)["status"] == "failed"
    assert run("files.move", f"copy.txt|{tmp_path / 'b.txt'}", confirmed=True, c=c)["status"] == "failed"
    assert not any(call[0] == "recycle" for call in c.platform.calls)
    out = run("files.delete", str(real), confirmed=True, c=c)
    assert out["ok"] is True and out["detail"] == "удалила в корзину: copy.txt"
    assert ("recycle", (str(real),)) in c.platform.calls
