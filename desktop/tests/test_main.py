"""Точка входа ядра: блокировка второго экземпляра, логи с ротацией."""
import logging
import os
from logging.handlers import RotatingFileHandler

from desktop.core import __main__ as core_main


def test_single_instance_lock(tmp_path):
    a = core_main.SingleInstance(str(tmp_path / "core.lock"))
    b = core_main.SingleInstance(str(tmp_path / "core.lock"))
    assert a.acquire() is True
    assert b.acquire() is False
    os.close(a._fd)


def test_setup_logging_rotating(tmp_path):
    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        core_main.setup_logging(str(tmp_path / "logs"))
        fh = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert fh and fh[0].maxBytes == 2 * 1024 * 1024 and fh[0].backupCount == 5
        assert (tmp_path / "logs" / "crash.log").exists()
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved


def test_cli_help_parses():
    import pytest
    with pytest.raises(SystemExit) as e:
        core_main.main(["--help"])
    assert e.value.code == 0


def test_second_instance_exits_with_already_running(tmp_path, monkeypatch):
    # Надзор в Electron не перезапускает ядро с этим кодом.
    monkeypatch.setattr(core_main.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_main.config, "LOG_DIR", str(tmp_path / "logs"))
    held = core_main.SingleInstance(str(tmp_path / "core.lock"))
    assert held.acquire()
    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        assert core_main.main(["--headless"]) == core_main.EXIT_ALREADY_RUNNING == 3
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved
        os.close(held._fd)


def test_lock_holds_after_pid_written_and_reports_owner(tmp_path):
    path = str(tmp_path / "core.lock")
    a = core_main.SingleInstance(path)
    assert a.acquire()
    # файл вырос (записан pid) — второй экземпляр всё равно не получает блокировку
    b = core_main.SingleInstance(path)
    assert b.acquire() is False
    assert b.owner_pid() == os.getpid()
    os.close(a._fd)
    # владелец исчез — блокировка свободна (протухшая перехватывается)
    c = core_main.SingleInstance(path)
    assert c.acquire() is True
    os.close(c._fd)


def test_second_core_process_exits_with_code_3(tmp_path):
    """Два настоящих процесса: второй выходит сразу с кодом 3."""
    import subprocess
    import sys
    import textwrap
    code = textwrap.dedent(f"""
        import sys, time
        from desktop.core.__main__ import SingleInstance
        g = SingleInstance(r"{tmp_path / 'core.lock'}")
        if not g.acquire():
            print("busy", g.owner_pid()); sys.exit(3)
        import os; print("ok", os.getpid(), flush=True); time.sleep(5)
    """)
    first = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, cwd=os.getcwd())
    tag, owner = first.stdout.readline().split()  # venv python.exe — запускатель: pid владельца у дочернего
    second = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    first.kill()
    first.wait()
    assert tag == "ok" and second.returncode == 3 and second.stdout.split() == ["busy", owner]
