"""Настоящий сервер Сакуры (adapters/ws.ws_handler) для test_private_over_noise.

Запускается ОТДЕЛЬНЫМ процессом: у сервера свой config.py, в процессе тестов
агента модуль config — агентский. Агентский код этот файл не импортирует.

    python server_harness.py <корень репозитория> <рабочий каталог>

Рабочий каталог — временный: все относительные пути сервера (memory/…)
пишутся туда, .env не читается. Источник соединений НЕ считается локальным
(is_local_peer → False) — как ПК в интернете без VPN.

stdout: одна строка JSON {"port", "words", "server_pub"}; сервер работает,
пока открыт stdin. Нет серверных зависимостей — строка "SKIP …", код 3.
"""

import asyncio
import json
import logging
import os
import sys


def main() -> int:
    root, work = sys.argv[1], sys.argv[2]
    os.chdir(work)
    os.environ.update({
        "MASTER_ID": "123456789",
        "TELEGRAM_TOKEN": "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        "GEMINI_KEY_1": "AIzaFakeKeyForTests1234567890",
        "WS_SECRET": "test-secret-minimum-16-chars",
        "MASTER_DEVICES": "laptop,pc",
        "SECURE_CHANNEL": "optional",
        "PRIVATE_REQUIRES_SECURE": "1",
        "PROTO_V2": "1",
        "COMPUTER_USE": "1",
        "SECURE_DIR": os.path.join(work, "secure"),
        "MEMORY_DB_PATH": os.path.join(work, "test.db"),
        "CHAT_DB_PATH": os.path.join(work, "chat.db"),
        "PROFILE_PATH": os.path.join(work, "profile_v2.json"),
        "SCENARIOS_PATH": os.path.join(work, "scenarios.json"),
    })
    os.makedirs(os.path.join(work, "memory"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    sys.path.insert(0, root)
    try:
        import dotenv
        dotenv.load_dotenv = lambda *a, **k: False      # .env разработчика не читаем
        import websockets

        import adapters.ws as wh
        import modules.state as st
        import modules.tts_server as tts
        import sakura_core.ws_protocol as proto
        from modules import device_manager, presence_sync, rituals
        from modules.ws_auth import MAX_WS_MESSAGE_SIZE
        from sakura_core import secure_policy
    except ImportError as e:
        print(f"SKIP нет серверной зависимости: {e.name}", flush=True)
        return 3

    # Как фикстура env в tests/test_securechannel_ws.py: без побочных эффектов.
    device_manager.set_device_offline = lambda d: None
    presence_sync.set_offline = lambda d: None
    rituals.should_farewell = lambda: False
    proto.update_device = lambda *a, **k: None
    proto.should_greet_device = lambda d: False
    proto.should_brief = lambda: False
    proto.ps_update = lambda *a, **k: None
    tts._preconnect_task = tts._preconnect_ready = tts._preconnect_release = None

    async def _no_preconnect(*a, **k):
        return False
    wh.tts_preconnect = wh.tts_release_preconnect = _no_preconnect
    st._pending_power = {}
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    # Прогрев: первый импорт numpy (через sqlite_vec в memory/db) в свежем
    # окружении Windows грузит DLL десятки секунд — до «готов», не в запросе.
    from memory import db as _memdb
    _memdb.list_memories(None, 0, 1)
    # «VPN выключен»: никакой источник не считается локальным.
    secure_policy.is_local_peer = lambda ip: False

    async def serve():
        ctx = secure_policy.context()
        words, _ = ctx.pairing.create()
        from securechannel.keys import b64url
        async with websockets.serve(wh.ws_handler, "127.0.0.1", 0, max_size=MAX_WS_MESSAGE_SIZE,
                                    ping_interval=None) as srv:
            port = srv.sockets[0].getsockname()[1]
            print(json.dumps({"port": port, "words": words,
                              "server_pub": b64url(ctx.keys.current[1])}), flush=True)
            await asyncio.get_running_loop().run_in_executor(None, sys.stdin.read)

    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
