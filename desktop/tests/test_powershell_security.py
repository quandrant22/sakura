"""Проверка отключения произвольного PowerShell по умолчанию (Задача 4)."""

from desktop.core import hands


def test_raw_powershell_blocked_by_default(monkeypatch):
    monkeypatch.delenv("SAKURA_ALLOW_RAW_POWERSHELL", raising=False)
    for cmd in ("dir", "Get-Process", "Get-Date; calc.exe", "ipconfig | findstr IPv4"):
        res = hands.powershell(cmd)
        assert res["ok"] is False
        assert "отключён" in res["detail"] or "заблокировано" in res["detail"]
