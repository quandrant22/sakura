"""tools/core_check: проверка живого ядра по ui.token — то же, что видит интерфейс."""
import asyncio
import json

from desktop.core.api.server import LocalApiServer
from desktop.tools import core_check


def _serve(tmp_path, snapshot):
    api = LocalApiServer(token="tok", token_path=str(tmp_path / "ui.token"), snapshot=lambda: snapshot)
    return api


def test_ready_and_online(tmp_path):
    async def go():
        api = _serve(tmp_path, [{"type": "connection", "server": "online", "proto": 1},
                                {"type": "settings", "settings": {"core_ready": True}}])
        await api.start()
        try:
            return await core_check.check(api.token_path, wait=3)
        finally:
            await api.stop()
    r = asyncio.run(go())
    assert r == {"core": True, "core_ready": True, "server": "online", "proto": 1}


def test_waits_for_server_then_gives_up(tmp_path):
    async def go():
        api = _serve(tmp_path, [{"type": "connection", "server": "offline", "proto": None},
                                {"type": "settings", "settings": {"core_ready": True}}])
        await api.start()
        try:
            return await core_check.check(api.token_path, wait=1)
        finally:
            await api.stop()
    r = asyncio.run(go())
    assert r["core"] is True and r["server"] == "offline"


def test_no_core(tmp_path, capsys):
    (tmp_path / "ui.token").write_text(json.dumps({"port": 1, "token": "x"}), encoding="utf-8")
    assert core_check.main(["--token-file", str(tmp_path / "ui.token")]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["core"] is False and "x" not in json.dumps(out)
