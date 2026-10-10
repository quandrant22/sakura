"""Точка входа ядра: блокировка второго экземпляра, логи с ротацией."""
import logging
from logging.handlers import RotatingFileHandler

from desktop.core import __main__ as core_main


def test_single_instance_lock(tmp_path):
    a = core_main.SingleInstance(str(tmp_path / "core.lock"))
    b = core_main.SingleInstance(str(tmp_path / "core.lock"))
    assert a.acquire() is True
    assert b.acquire() is False
    a._fh.close()


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
