"""Параметры запуска приложений (шаг Е) на подставном слое: ничего настоящего не запускается."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from desktop.core import app_launch as A

EXE = r"C:\Users\U\AppData\Local\Programs\YandexMusic\Яндекс Музыка.exe"
STORE = r"C:\Program Files\WindowsApps\Yandex.Music_5.0\Яндекс Музыка.exe"


class World:
    """Процессы приложения, запуск и закрытие — в памяти; часы — ручные."""

    def __init__(self, running=False, flag=False, exe=EXE, files=(EXE,), a11y=30, stubborn=False):
        self.t = 0.0
        self.files = set(files)
        self.procs = []
        self.spawned = []
        self.killed = []
        self.a11y = a11y
        self.stubborn = stubborn
        self.next_pid = 100
        if running:
            self._start(exe, [A.A11Y_FLAG] if flag else [])

    def _start(self, exe, args):
        main = self.next_pid
        self.next_pid += 10
        self.procs = [{"pid": main, "ppid": 1, "exe": exe, "name": "Яндекс Музыка.exe", "cmdline": [exe, *args]},
                      {"pid": main + 1, "ppid": main, "exe": exe, "name": "Яндекс Музыка.exe",
                       "cmdline": [exe, "--type=renderer"]}]

    def env(self):
        def kill_tree(pid):
            self.killed.append(pid)
            if not self.stubborn:
                self.procs = []

        def spawn(argv):
            self.spawned.append(argv)
            self._start(argv[0], argv[1:])

        def sleep(s):
            self.t += s

        return A.Env(procs=lambda: list(self.procs), exists=lambda p: p in self.files, start_menu=lambda: [],
                     lnk_target=lambda p: p, uninstall=lambda: [], apps_cache=lambda: [], kill_tree=kill_tree,
                     spawn=spawn, a11y_elements=lambda: self.a11y if self.procs else None, sleep=sleep,
                     clock=lambda: self.t)


@pytest.fixture(autouse=True)
def prefs(monkeypatch):
    monkeypatch.setitem(A.PREFS, "yandex_music", True)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\U\AppData\Local")


def launcher(w):
    return A.AppLauncher(env=w.env())


def test_whitelist_and_app_key():
    assert A.allowed_args("yandex_music", ["--force-renderer-accessibility", "--remote-debugging-port=9222",
                                           "--disable-web-security"]) == ["--force-renderer-accessibility"]
    assert A.app_key("Яндекс Музыка") == "yandex_music" and A.app_key("yandex music") == "yandex_music"
    assert A.app_key("блокнот") is None


def test_launch_not_running_with_flag():
    w = World()
    assert launcher(w).launch("yandex_music")["ok"] is True
    assert w.spawned == [[EXE, A.A11Y_FLAG]]


def test_launch_without_flag_when_setting_off(monkeypatch):
    monkeypatch.setitem(A.PREFS, "yandex_music", False)
    w = World()
    launcher(w).launch("yandex_music")
    assert w.spawned == [[EXE]]


def test_launch_already_running_noop():
    w = World(running=True)
    assert launcher(w).launch("yandex_music")["status"] == "noop" and w.spawned == []


def test_path_found_dynamically_from_running_process_any_version():
    other = r"D:\Apps\YandexMusic-5.9.1\Яндекс Музыка.exe"
    w = World(running=True, exe=other, files=(other,))
    assert launcher(w).find_exe("yandex_music") == other


def test_path_from_registry_when_not_running_and_missing_default():
    reg = r"E:\YM\Яндекс Музыка.exe"
    w = World(files=(reg,))
    env = w.env()
    env.uninstall = lambda: [r"E:\nope\Яндекс Музыка.exe", reg]
    assert A.AppLauncher(env=env).find_exe("yandex_music") == reg
    env.uninstall = lambda: []
    assert A.AppLauncher(env=env).find_exe("yandex_music") is None


def test_store_app_unsupported():
    w = World(files=(STORE,))
    env = w.env()
    env.uninstall = lambda: [STORE]
    out = A.AppLauncher(env=env).launch("yandex_music")
    assert out["status"] == "unsupported" and "Microsoft Store" in out["detail"] and w.spawned == []


def test_state_running_without_and_with_flag():
    st = launcher(World(running=True, flag=False, a11y=8)).state("yandex_music")
    assert st["running"] is True and st["with_flag"] is False and st["a11y"] is False
    st = launcher(World(running=True, flag=True, a11y=40)).state("yandex_music")
    assert st["with_flag"] is True and st["a11y"] is True
    assert launcher(World()).state("yandex_music")["running"] is False


def test_restart_closes_whole_tree_and_starts_with_flag():
    w = World(running=True, flag=False)
    out = launcher(w).restart("yandex_music")
    assert out["ok"] is True and out["a11y"] is True
    assert w.killed[0] == 100 and w.spawned == [[EXE, A.A11Y_FLAG]]
    assert w.procs[0]["cmdline"] == [EXE, A.A11Y_FLAG]


def test_restart_close_timeout():
    w = World(running=True, stubborn=True)
    out = launcher(w).restart("yandex_music")
    assert out["status"] == "failed" and "не закрылась" in out["detail"] and w.spawned == []


def test_restart_flag_but_a11y_tree_stays_small():
    w = World(running=True, a11y=8)
    out = launcher(w).restart("yandex_music")
    assert out["ok"] is True and out["a11y"] is False and "кнопки окна пока не видны" in out["detail"]


def test_control_app_restart_action():
    from desktop.core.control import registry as reg
    from desktop.core.control import safety
    w = World(running=True)
    ctx = reg.Ctx(platform=SimpleNamespace(), apps=launcher(w))
    lim = safety.RateLimiter(limit=100)
    assert reg.execute("app.restart", "яндекс музыка", ctx=ctx, limiter=lim)["ok"] is True
    assert reg.execute("app.restart", "блокнот", ctx=ctx, limiter=lim)["status"] == "unsupported"


def test_agent_open_app_launches_with_params_when_not_running():
    from desktop.core import agent as agent_mod
    w = World()
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(json.loads(raw))
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a._ws, a.bus, a.media, a.server_link = WS(), None, None, None
    a.app_launcher = launcher(w)
    asyncio.run(a._run_command("open.app", "c1", "яндекс музыка"))
    assert w.spawned == [[EXE, A.A11Y_FLAG]]
    assert sent[-1]["id"] == "c1" and sent[-1]["ok"] is True
