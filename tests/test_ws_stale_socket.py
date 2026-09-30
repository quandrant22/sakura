"""fix/ws-stale-socket: закрытие устаревшего сокета не снимает живую регистрацию.

Телефон иногда держит два сокета с одним device_id. Раньше закрытие
старого делало connected_devices.pop + set_device_offline — и снимало
регистрацию живого соединения. Теперь:
  * регистрация нового сокета вытесняет старый (close 4000 «replaced»);
  * закрытие не текущего сокета устройство онлайн не трогает;
  * закрытие единственного сокета — офлайн, как раньше.

Настоящий сервер websockets + настоящий ws_handler; побочные эффекты
регистрации (файл устройств, presence в БД, приветствие) подменены.

Run: python -m pytest tests/test_ws_stale_socket.py -q
"""

import asyncio
import json
import logging

import pytest
import websockets

import modules.state as st
import sakura_core.ws_protocol as proto
from adapters.ws import ws_handler
from modules import device_manager, presence_sync, rituals
from modules.ws_auth import _WS_SECRET, MAX_WS_MESSAGE_SIZE

DEVICE = "phone"


@pytest.fixture
def offline(monkeypatch):
    """Перехват снятия регистрации; connected_devices — тот же dict, чистый."""
    calls = []
    saved = dict(st.connected_devices)
    st.connected_devices.clear()   # adapters.ws держит ссылку на этот dict
    monkeypatch.setattr(device_manager, "set_device_offline",
                        lambda d: calls.append(("device", d)))
    monkeypatch.setattr(presence_sync, "set_offline",
                        lambda d: calls.append(("presence", d)))
    monkeypatch.setattr(rituals, "should_farewell", lambda: False)
    monkeypatch.setattr(proto, "update_device", lambda *a, **k: None)
    monkeypatch.setattr(proto, "should_greet_device", lambda d: False)
    monkeypatch.setattr(proto, "should_brief", lambda: False)
    monkeypatch.setattr(proto, "ps_update", lambda *a, **k: None)
    yield calls
    st.connected_devices.clear()
    st.connected_devices.update(saved)


async def _with_server(scenario):
    async with websockets.serve(ws_handler, "127.0.0.1", 0,
                                max_size=MAX_WS_MESSAGE_SIZE,
                                ping_interval=None) as server:
        port = server.sockets[0].getsockname()[1]
        await scenario(f"ws://127.0.0.1:{port}")


async def _register(uri):
    client = await websockets.connect(uri, max_size=None)
    await client.send(json.dumps(
        {"type": "register", "token": _WS_SECRET, "device_id": DEVICE}))
    return client


async def _until(cond, timeout=3.0):
    """Дождаться условия на стороне сервера (finally обработчика)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        assert loop.time() < end, "условие на сервере не наступило"
        await asyncio.sleep(0.02)


def test_old_socket_closed_after_new_registration_keeps_device_online(
        offline, caplog):
    """Второй сокет того же device_id: старый закрыт кодом 4000, устройство
    остаётся онлайн на новом; офлайн — только когда закрылся и новый."""
    async def scenario(uri):
        old = await _register(uri)
        await _until(lambda: DEVICE in st.connected_devices)
        old_server_ws = st.connected_devices[DEVICE]

        new = await _register(uri)
        await _until(lambda: st.connected_devices.get(DEVICE) is not old_server_ws)
        await asyncio.wait_for(old.wait_closed(), 3)
        assert old.close_code == 4000 and old.close_reason == "replaced"

        # finally старого обработчика отработал — регистрация на месте.
        await _until(lambda: "закрыт устаревший сокет" in caplog.text)
        assert DEVICE in st.connected_devices
        assert offline == [], f"устаревший сокет снял регистрацию: {offline}"

        await new.close()
        await _until(lambda: DEVICE not in st.connected_devices)
        await _until(lambda: len(offline) == 2)

    with caplog.at_level(logging.INFO):
        asyncio.run(_with_server(scenario))

    assert sorted(offline) == [("device", DEVICE), ("presence", DEVICE)]
    assert f"[ws] замена сокета device_id={DEVICE}" in caplog.text
    assert "code=4000 reason='replaced'" in caplog.text
    assert "[ws] connection open 127.0.0.1:" in caplog.text


def test_only_socket_closed_marks_device_offline(offline, caplog):
    """Единственный сокет закрылся → офлайн, код закрытия в логе."""
    async def scenario(uri):
        client = await _register(uri)
        await _until(lambda: DEVICE in st.connected_devices)
        await client.close()
        await _until(lambda: DEVICE not in st.connected_devices)
        await _until(lambda: len(offline) == 2)

    with caplog.at_level(logging.INFO):
        asyncio.run(_with_server(scenario))

    assert sorted(offline) == [("device", DEVICE), ("presence", DEVICE)]
    assert "замена сокета" not in caplog.text
    assert f"device_id={DEVICE} code=1000" in caplog.text
    assert f"Устройство отключено: {DEVICE}" in caplog.text
