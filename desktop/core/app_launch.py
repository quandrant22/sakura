"""desktop.core.app_launch — параметры запуска приложений (Настройки → Приложения).

Параметры только из белого списка (не от голоса и не от сервера). Сейчас одно приложение —
Яндекс.Музыка (Electron, обычный exe): ключ --force-renderer-accessibility включает доступность
Chromium, тогда кнопки окна (перемешать, повтор, «Моя волна») видны UI Automation.

Путь к exe ищется при каждом запуске: запущенный процесс → %LOCALAPPDATA%\\Programs\\YandexMusic →
ярлык в «Пуске» → реестр Uninstall → apps_cache.json; номер версии в пути не кэшируется.
Приложение однооконное: чтобы ключ применился, закрывается ВСЁ дерево его процессов, затем запуск
с ключом; успех — ключ в CommandLine нового главного процесса и в дереве UI Automation > 8 элементов.
Приложения из Microsoft Store (WindowsApps) параметров не принимают — unsupported.
Системные зависимости (psutil, реестр, запуск) подменяются в тестах (Env).
"""
import glob
import json
import logging
import os
import time
from dataclasses import dataclass, field

from desktop.core import results as R

log = logging.getLogger("sakura.apps")

A11Y_FLAG = "--force-renderer-accessibility"
EXE_NAME = "Яндекс Музыка.exe"
APPS = {
    "yandex_music": {
        "title": "Яндекс.Музыка",
        "names": ("яндекс музыка", "яндекс.музыка", "yandex music", "yandex_music", "музыка"),
        "exe": EXE_NAME,
        "allowed": (A11Y_FLAG,),
        "default": (A11Y_FLAG,),
    },
}
# Настройка «Поддержка кнопок окна» (MUSIC_ACCESSIBILITY, по умолчанию 1); сервис меняет её из Настроек.
PREFS = {"yandex_music": os.getenv("MUSIC_ACCESSIBILITY", "1") != "0"}
MIN_A11Y_ELEMENTS = 8
CLOSE_TIMEOUT_S = 10.0
START_TIMEOUT_S = 15.0


def app_key(name: str) -> str | None:
    n = (name or "").strip().lower()
    for key, spec in APPS.items():
        if n == key or any(a in n for a in spec["names"]):
            return key
    return None


def default_args(key: str) -> list[str]:
    """Параметры по умолчанию с учётом переключателя в Настройках."""
    return list(APPS[key]["default"]) if PREFS.get(key, True) else []


def allowed_args(key: str, args) -> list[str]:
    """Только параметры из белого списка приложения."""
    allowed = APPS[key]["allowed"]
    return [a for a in (args or ()) if a in allowed]


def is_store_path(path: str) -> bool:
    return "\\windowsapps\\" in (path or "").lower().replace("/", "\\")


@dataclass
class Env:
    """Системные зависимости — подменяются в тестах."""
    procs: object = None            # () → [{"pid", "ppid", "exe", "cmdline": [..], "name"}]
    exists: object = os.path.isfile
    start_menu: object = None       # () → [пути .lnk]
    lnk_target: object = None       # (lnk) → путь
    uninstall: object = None        # () → [пути exe из реестра]
    apps_cache: object = None       # () → [пути]
    kill_tree: object = None        # (pid) → None
    spawn: object = None            # ([exe, *args]) → None
    a11y_elements: object = None    # () → число элементов в дереве окна или None
    sleep: object = time.sleep
    clock: object = time.monotonic
    extra: dict = field(default_factory=dict)


def _default_env() -> Env:
    import subprocess

    import psutil

    def procs():
        out = []
        for p in psutil.process_iter(["pid", "ppid", "exe", "name", "cmdline"]):
            i = p.info
            out.append({"pid": i["pid"], "ppid": i["ppid"], "exe": i["exe"] or "", "name": i["name"] or "",
                        "cmdline": i["cmdline"] or []})
        return out

    def start_menu():
        roots = [os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
                 os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]
        return [p for r in roots for p in glob.glob(os.path.join(r, "**", "*узык*.lnk"), recursive=True)]

    def lnk_target(lnk):
        import comtypes.client
        sh = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
        return sh.CreateShortcut(lnk).TargetPath

    def uninstall():
        from desktop.core.platform.windows import uninstall_exes
        return uninstall_exes(("музык", "yandex music"), EXE_NAME)

    def apps_cache():
        from desktop.core import config
        try:
            data = json.load(open(os.path.join(config.DATA_DIR, "apps_cache.json"), encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data if isinstance(data, list) else data.get("apps", [])
        return [str(a.get("path", "")) for a in items
                if isinstance(a, dict) and "узык" in str(a.get("name", "")).lower()]

    def kill_tree(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def spawn(argv):
        subprocess.Popen(argv, close_fds=True, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    def a11y_elements():
        from desktop.core.platform import uia
        root = uia.window_by_title("Яндекс Музыка")
        if root is None:
            return None
        c = uia.client()
        return root.FindAll(4, c.CreateTrueCondition()).Length

    return Env(procs=procs, start_menu=start_menu, lnk_target=lnk_target, uninstall=uninstall,
               apps_cache=apps_cache, kill_tree=kill_tree, spawn=spawn, a11y_elements=a11y_elements)


class AppLauncher:
    def __init__(self, env: Env | None = None):
        self.env = env or _default_env()

    # ── процессы ───────────────────────────────────────────────────
    def _app_procs(self, key: str) -> list[dict]:
        exe = APPS[key]["exe"].lower()
        return [p for p in self.env.procs() if (p["name"] or "").lower() == exe
                or os.path.basename(p["exe"] or "").lower() == exe]

    def _main(self, procs: list[dict]) -> dict | None:
        pids = {p["pid"] for p in procs}
        roots = [p for p in procs if p["ppid"] not in pids]
        return roots[0] if roots else None

    # ── путь к exe ─────────────────────────────────────────────────
    def find_exe(self, key: str) -> str | None:
        e = self.env
        exe = APPS[key]["exe"]
        candidates: list[str] = []
        main = self._main(self._app_procs(key))
        if main and main["exe"]:
            candidates.append(main["exe"])
        candidates.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "YandexMusic", exe))
        for getter in (lambda: [e.lnk_target(lnk) for lnk in (e.start_menu() or [])] if e.start_menu else [],
                       lambda: e.uninstall() if e.uninstall else [],
                       lambda: e.apps_cache() if e.apps_cache else []):
            try:
                candidates.extend(getter() or [])
            except Exception as ex:  # noqa: BLE001
                log.info("[apps] поиск пути: %s", type(ex).__name__)
        for c in candidates:
            if c and os.path.basename(c).lower() == exe.lower() and e.exists(c):
                return c
        return None

    # ── состояние ──────────────────────────────────────────────────
    def state(self, key: str) -> dict:
        """{running, with_flag, store, a11y, exe}: a11y — кнопки окна доступны (UIA > 8 элементов)."""
        procs = self._app_procs(key)
        main = self._main(procs)
        flag = APPS[key]["default"][0]
        exe = (main or {}).get("exe") or self.find_exe(key) or ""
        st = {"running": bool(main), "with_flag": bool(main and flag in (main.get("cmdline") or [])),
              "store": is_store_path(exe), "exe_found": bool(exe), "a11y": None}
        if main:
            try:
                n = self.env.a11y_elements()
                st["a11y"] = None if n is None else n > MIN_A11Y_ELEMENTS
            except Exception:  # noqa: BLE001
                st["a11y"] = None
        return st

    # ── запуск и перезапуск ────────────────────────────────────────
    def launch(self, key: str, args=None) -> dict:
        """Запустить с параметрами (если уже запущено — не трогать)."""
        title = APPS[key]["title"]
        if self._main(self._app_procs(key)):
            return R.noop(f"{title} уже запущена")
        exe = self.find_exe(key)
        if not exe:
            return R.failed(f"{title} не найдена — установите приложение")
        args = allowed_args(key, default_args(key) if args is None else args)
        if args and is_store_path(exe):
            return R.unsupported(f"{title} из Microsoft Store не принимает параметры запуска")
        self.env.spawn([exe, *args])
        log.info("[apps] запуск %s с параметрами %s", key, args)
        return R.done(f"открыла {title}")

    def restart(self, key: str, args=None) -> dict:
        """Закрыть всё дерево процессов приложения, дождаться и запустить с параметрами."""
        e = self.env
        title = APPS[key]["title"]
        exe = self.find_exe(key)
        if not exe:
            return R.failed(f"{title} не найдена — установите приложение")
        args = allowed_args(key, default_args(key) if args is None else args)
        if args and is_store_path(exe):
            return R.unsupported(f"{title} из Microsoft Store не принимает параметры запуска")
        t0 = e.clock()
        procs = self._app_procs(key)
        main = self._main(procs)
        if main:
            e.kill_tree(main["pid"])
        for p in self._app_procs(key):  # трей и прочие, не попавшие в дерево
            e.kill_tree(p["pid"])
        deadline = e.clock() + CLOSE_TIMEOUT_S
        while self._app_procs(key):
            if e.clock() >= deadline:
                return R.failed(f"{title} не закрылась за {int(CLOSE_TIMEOUT_S)} с — закройте её вручную")
            e.sleep(0.25)
        e.spawn([exe, *args])
        deadline = e.clock() + START_TIMEOUT_S
        while True:
            main = self._main(self._app_procs(key))
            if main and all(a in (main.get("cmdline") or []) for a in args):
                break
            if e.clock() >= deadline:
                return R.failed(f"{title} не запустилась с параметрами за {int(START_TIMEOUT_S)} с")
            e.sleep(0.25)
        a11y = None
        if A11Y_FLAG in args:
            while e.clock() < deadline:
                n = e.a11y_elements()
                if n is not None and n > MIN_A11Y_ELEMENTS:
                    a11y = n
                    break
                e.sleep(0.5)
        log.info("[apps] перезапуск %s: %.1f с, параметры %s, UIA элементов %s", key, e.clock() - t0, args, a11y)
        if A11Y_FLAG in args and a11y is None:
            return R.done(f"перезапустила {title}, но кнопки окна пока не видны", a11y=False)
        return R.done(f"перезапустила {title}" + (" с поддержкой кнопок окна" if a11y else ""), a11y=bool(a11y))
