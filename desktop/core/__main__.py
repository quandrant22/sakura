"""Точка входа ядра: python -m desktop.core [--headless] [--api-port N].

Поднимает логи (ротация 2 МБ × 5, как agent/sakura.py), faulthandler (crash.log),
хуки исключений, защиту от второго экземпляра, захват системного звука для
эквалайзера, локальный API и агента (голос, сервер, команды, расширение).
Интерфейс (desktop/ui) и оверлей (python -m desktop.overlay) подключаются к
локальному API отдельными процессами.
"""
import argparse
import asyncio
import faulthandler
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from desktop.core import config

log = logging.getLogger("sakura")

# Код выхода «ядро уже запущено»: надзор в Electron (coreProcess.ts) такое ядро не перезапускает.
EXIT_ALREADY_RUNNING = 3


def setup_logging(log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    crash = open(os.path.join(log_dir, "crash.log"), "a", buffering=1, encoding="utf-8")
    faulthandler.enable(file=crash, all_threads=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s  %(message)s")
    fh = RotatingFileHandler(os.path.join(log_dir, "sakura.log"), maxBytes=2 * 1024 * 1024,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


class SingleInstance:
    """Файловая блокировка в DATA_DIR: второй экземпляр ядра не стартует."""

    def __init__(self, path: str):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._fh = open(self.path, "a+")  # держим открытым всю жизнь процесса
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False


def watch_parent(parent_pid: int, pid_exists=None, exit_fn=os._exit, interval: float = 2.0,
                 sleep=time.sleep, once: bool = False) -> None:
    """Окно (Electron) запустило ядро и исчезло, не закрыв его, — ядро завершается само."""
    if pid_exists is None:
        import psutil
        pid_exists = psutil.pid_exists
    while True:
        if not pid_exists(parent_pid):
            log.warning("[core] окно (pid %s) завершилось — закрываю ядро", parent_pid)
            exit_fn(0)
            return
        if once:
            return
        sleep(interval)


def _start_parent_watch() -> None:
    raw = os.getenv("SAKURA_PARENT_PID", "")
    if raw.isdigit():
        import threading
        threading.Thread(target=watch_parent, args=(int(raw),), daemon=True, name="parent-watch").start()


def _start_music_listener(service) -> None:
    from desktop.core.music_listener import start

    last = [0.0]

    def on_bars(bars):
        now = time.monotonic()
        if now - last[0] >= 0.1:  # не чаще 10 раз в секунду
            last[0] = now
            service.api.emit_threadsafe({"type": "audio_level", "bars": [round(b, 3) for b in bars]})

    start(callback=on_bars)


async def run_core(api_port: int) -> None:
    from desktop.core.hands import get_command_registry
    from desktop.core.service import CoreService

    get_command_registry()
    service = CoreService()
    _start_music_listener(service)
    await service.run(api_port)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="desktop.core", description="Sakura desktop core")
    ap.add_argument("--headless", action="store_true", help="без интерфейса, только ядро")
    ap.add_argument("--api-port", type=int, default=0, help="порт локального API (0 — любой свободный)")
    ap.add_argument("--no-server", action="store_true", help="не подключаться к VPS (как SAKURA_OFFLINE=1)")
    args = ap.parse_args(argv)
    if args.no_server:
        os.environ["SAKURA_OFFLINE"] = "1"
        config.OFFLINE = True

    setup_logging(config.LOG_DIR)
    from desktop.core.exception_hooks import install_exception_hooks
    install_exception_hooks(log)

    guard = SingleInstance(os.path.join(config.DATA_DIR, "core.lock"))
    if not guard.acquire():
        log.warning("Ядро Сакуры уже запущено.")
        return EXIT_ALREADY_RUNNING
    log.info("[core] старт: device=%s env=%s data=%s headless=%s offline=%s", config.DEVICE_ID,
             "найден" if config.ENV_FILE else "нет", config.DATA_DIR, args.headless, config.OFFLINE)
    _start_parent_watch()
    asyncio.run(run_core(args.api_port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
