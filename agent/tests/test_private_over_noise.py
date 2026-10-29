"""tests/test_private_over_noise.py — спаренный агент без VPN получает все
приватные классы (PROTOCOL §5.1) и secure_devices.

Сервер — настоящий adapters/ws.ws_handler в отдельном процессе
(server_harness.py), источник соединения НЕ считается локальным: это
«ПК в интернете, VPN выключен». Контроль: тот же запрос по старому ws+token
получает secure_channel_required.

Серверу нужны его зависимости (requirements.txt). Интерпретатор сервера —
SAKURA_SERVER_PYTHON (по умолчанию тот же, что у pytest); без зависимостей
тест пропускается с причиной.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import websockets
from core import transport

transport._ensure_securechannel_path()
pytest.importorskip("noise")

from securechannel.client import pair
from securechannel.handshake import generate_keypair
from securechannel.keys import unb64url

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_secure_store import FakeSecureStore

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().with_name("server_harness.py")
WS_SECRET = "test-secret-minimum-16-chars"      # тот же, что в server_harness.py

# Каждый приватный класс §5.1 — запросом, который сервер обрабатывает без сети
# (chat_send уходит в LLM — класс chat_* представлен chat_read и chat_search).
PRIVATE = [
    ("chat_read", {"last_read_id": "0"}),
    ("chat_search", {"q": "сакура"}),
    ("history_request", {}),
    ("memory_list", {}),
    ("profile_get", {}),
    ("secure_devices", {}),
    ("vision_request", {}),          # без кадра → bad_request ПОСЛЕ проверки канала
    ("computer_step", {}),           # без goal → bad_request ПОСЛЕ проверки канала
]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    work = tmp_path_factory.mktemp("sakura_server")
    py = os.environ.get("SAKURA_SERVER_PYTHON") or sys.executable
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("WS_TOKEN", None)
    with open(work / "server.log", "w", encoding="utf-8") as err:
        proc = subprocess.Popen([py, str(HARNESS), str(REPO), str(work)], cwd=str(work),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                text=True, encoding="utf-8", env=env)
        first: list[str] = []
        ready = threading.Event()

        def _read():
            for line in proc.stdout:            # дочитываем всё, чтобы pipe не встал
                if not first:
                    first.append(line.strip())
                    ready.set()
            ready.set()

        threading.Thread(target=_read, daemon=True).start()
        ready.wait(120)
        try:
            if not first:
                err.flush()
                tail = (work / "server.log").read_text(encoding="utf-8")[-2000:]
                pytest.fail(f"сервер не запустился (код {proc.poll()}): {tail}")
            if first[0].startswith("SKIP"):
                pytest.skip(f"{first[0]} (SAKURA_SERVER_PYTHON — интерпретатор "
                            "с requirements.txt)")
            info = json.loads(first[0])
            yield {"url": f"ws://127.0.0.1:{info['port']}", "words": info["words"],
                   "server_pub": unb64url(info["server_pub"])}
        finally:
            proc.stdin.close()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()


async def until(conn, pred, timeout=15.0):
    while True:
        raw = await asyncio.wait_for(conn.recv(), timeout)
        if isinstance(raw, bytes):
            continue
        m = json.loads(raw)
        if pred(m):
            return m


def test_paired_agent_gets_private_classes_without_vpn(server):
    async def sc():
        url = server["url"]
        priv, pub = generate_keypair()
        async with websockets.connect(url, max_size=None) as ws:
            info = await pair(ws, server["words"], priv,
                              expected_server_pub=server["server_pub"],
                              name="Ноутбук", kind="pc", device_id_hint="laptop")
        store = FakeSecureStore.paired(info["device_id"], priv, pub,
                                       info["server_pub_bytes"], server_url=url)

        # агент: спарен → только Noise, токена нет вовсе
        conn = await transport.open_connection(url, "prefer", token="", store=store)
        assert (conn.secure, conn.transport) == (True, "noise")
        await conn.send_json({"type": "register", "device_id": "laptop", "proto": 2})
        reg = await until(conn, lambda m: m.get("type") == "registered")
        out = {}
        for kind, extra in PRIVATE:
            await conn.send_json({"type": kind, "request_id": kind,
                                  "device_id": "laptop", **extra})
            out[kind] = await until(conn, lambda m, k=kind: m.get("request_id") == k)
        await conn.close()

        # контроль: тот же сервер, старый протокол — приватное закрыто
        async with websockets.connect(url) as ws:
            plain = transport.Conn(ws, transport="ws", token=WS_SECRET)
            await plain.send_json({"type": "register", "device_id": "laptop", "proto": 2})
            await until(plain, lambda m: m.get("type") == "registered")
            await plain.send_json({"type": "history_request", "request_id": "h",
                                   "device_id": "laptop"})
            control = await until(plain, lambda m: m.get("request_id") == "h")
        return info, reg, out, control

    info, reg, out, control = asyncio.run(asyncio.wait_for(sc(), 120))
    assert info["device_id"] == "laptop"
    assert reg["device_id"] == "laptop"
    for kind, _ in PRIVATE:
        assert out[kind].get("code") != "secure_channel_required", (kind, out[kind])
    assert out["history_request"]["type"] == "history"
    assert out["chat_search"]["type"] == "chat_search"
    assert out["memory_list"].get("type") != "error", out["memory_list"]
    assert out["profile_get"].get("type") != "error", out["profile_get"]
    me = [d for d in out["secure_devices"]["devices"] if d["device_id"] == "laptop"]
    assert me and me[0]["secure_now"] is True and me[0]["current"] is True
    assert out["vision_request"]["code"] == "bad_request"
    assert out["computer_step"]["code"] == "bad_request"
    assert control["code"] == "secure_channel_required"
