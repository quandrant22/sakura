"""
core/extension_server.py — локальный WebSocket сервер для расширения браузера.

Слушает первый свободный порт из config.EXTENSION_PORTS (8766, 8767, …):
исторический 8766 может занять любая программа — VS Code держал его, и
агент без паузы ретраил привязку, сжигая ядро CPU.
Расширение Opera подключается сюда и ждёт команд.
Агент пересылает сюда команды от VPS которые помечены {"via": "extension"}.

Схема:
  VPS → WS :8765 → agent._run_command
                        ↓ если via=extension
                 extension_server.send_command(action, arg)
                        ↓
                 Расширение → Chrome API → DOM/Вкладки/YouTube
                        ↓
                 extension_server.result → WS → VPS
"""

import asyncio
import json
import logging
import time

log = logging.getLogger("sakura.extension")

# Порт выбирается при старте: первый свободный из config.EXTENSION_PORTS
# (agent/config.py, переопределяется в .env). None — свободного нет:
# сервер не поднят, расширение переподключится, когда агент найдёт порт
# (ретраи — в run_forever с backoff).
EXTENSION_PORT = None

# Ошибка привязки логируется один раз на серию неудачных попыток, а не
# на каждой попытке (иначе — тысячи строк в секунду, как в бою с VS Code).
_bind_error_logged = False

# ── Backoff для run_forever ─────────────────────────────────────────
# Нарастающая пауза между попытками: 5, 10, 30 с, дальше раз в 60.
# Сбрасывается, если сервер проработал дольше RESTART_STABLE_SEC.
RESTART_DELAYS = (5, 10, 30)
RESTART_MAX_DELAY = 60
RESTART_STABLE_SEC = 60

_extension_ws = None          # WebSocket соединение с расширением
_pending: dict = {}            # action_id → asyncio.Future
_last_activity: float = 0.0   # время последней активности расширения


def is_connected() -> bool:
    return _extension_ws is not None


def get_status() -> dict:
    """Статус расширения для диагностики."""
    return {
        "connected": _extension_ws is not None,
        "pending": len(_pending),
    }


_agent_loop = None  # event loop основного агента


def set_agent_loop(loop):
    global _agent_loop
    _agent_loop = loop


def next_restart_delay(fail_count: int) -> int:
    """Пауза после fail_count подряд неудач: 5, 10, 30, 60, 60, …"""
    if fail_count < len(RESTART_DELAYS):
        return RESTART_DELAYS[fail_count]
    return RESTART_MAX_DELAY


def run_forever(start=None, sleep=time.sleep, logger=None):
    """Цикл запуска сервера: пауза при ЛЮБОМ завершении start().

    Живёт в отдельном потоке (вызов из agent.run). Раньше пауза стояла
    только в ветке except, а start() глотал ошибку привязки и возвращался
    нормально — цикл перезапускался мгновенно, строка лога каждые ~10 мс,
    ядро CPU отнималось у слуха. Теперь: нарастающая пауза 5/10/30/60,
    сброс счётчика, если сервер проработал дольше RESTART_STABLE_SEC
    (перезапуск — не падение).
    """
    import asyncio as _aio

    log_ = logger or log
    fails = 0
    while True:
        started = time.monotonic()
        loop = None
        try:
            loop = _aio.new_event_loop()
            _aio.set_event_loop(loop)
            # start — параметр; модульную start() достаём из globals(),
            # когда явный start не передан (боевой путь из agent.run).
            loop.run_until_complete(
                start() if start is not None else globals()["start"]())
        except Exception as e:
            log_.warning(f"[extension] Сервер упал: {e}")
        finally:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass
        # Долго жил → сброс счётчика (перезапуск, а не падение).
        if time.monotonic() - started > RESTART_STABLE_SEC:
            fails = 0
        delay = next_restart_delay(fails)
        log_.warning(f"[extension] Перезапуск сервера через {delay}с")
        sleep(delay)
        fails += 1


async def send_command(action: str, arg: str = "", timeout: float = 8.0) -> dict:
    """
    Отправляет команду расширению и ждёт результата.
    Поддерживает все команды: tabs, navigation, bookmarks, history, youtube, forms, etc.
    """
    if not _extension_ws:
        return {"ok": False, "error": "Расширение не подключено"}

    import uuid
    cmd_id = str(uuid.uuid4())[:8]
    loop   = asyncio.get_event_loop()
    fut    = loop.create_future()
    _pending[cmd_id] = fut

    try:
        await _extension_ws.send(json.dumps({
            "id":     cmd_id,
            "action": action,
            "arg":    arg,
        }))
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending.pop(cmd_id, None)
        return {"ok": False, "error": "Тайм-аут расширения"}
    except Exception as e:
        _pending.pop(cmd_id, None)
        return {"ok": False, "error": str(e)}


async def send_command_with_code(action: str, code: str = "", timeout: float = 8.0) -> dict:
    """Отправляет команду с произвольным JS кодом."""
    if not _extension_ws:
        return {"ok": False, "error": "Расширение не подключено"}

    import uuid
    cmd_id = str(uuid.uuid4())[:8]
    loop   = asyncio.get_event_loop()
    fut    = loop.create_future()
    _pending[cmd_id] = fut

    try:
        await _extension_ws.send(json.dumps({
            "id":   cmd_id,
            "action": action,
            "code": code,
        }))
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending.pop(cmd_id, None)
        return {"ok": False, "error": "Тайм-аут расширения"}
    except Exception as e:
        _pending.pop(cmd_id, None)
        return {"ok": False, "error": str(e)}


async def _handler(websocket):
    global _extension_ws, _last_activity

    # Если уже есть живое соединение — закрываем новое
    if _extension_ws is not None:
        try:
            await _extension_ws.ping()
            await websocket.close(1008, "Already connected")
            return
        except Exception:
            pass

    # Представляемся первым сообщением: расширение ждёт sakura_hello не
    # дольше секунды и уходит к следующему порту, если на том конце не
    # Сакура (в бою 8766 держал VS Code — без проверки расширение слало
    # команды ему). Единственное изменение протокола агент↔расширение;
    # протокол агент↔VPS не тронут.
    try:
        await websocket.send(json.dumps(
            {"type": "sakura_hello", "version": "3.0.0"}))
    except Exception:
        return

    _extension_ws = websocket
    _last_activity = asyncio.get_event_loop().time()
    log.info("[extension] Расширение подключено")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            _last_activity = asyncio.get_event_loop().time()
            msg_type = msg.get("type", "")

            if msg_type == "extension_ready":
                log.info(f"[extension] Готово, версия {msg.get('version', '?')}")
                continue

            if msg_type == "extension_result":
                cmd_id = msg.get("id")
                if cmd_id and cmd_id in _pending:
                    fut = _pending.pop(cmd_id)
                    result = msg.get("result", {})
                    if _agent_loop and not fut.done():
                        _agent_loop.call_soon_threadsafe(
                            fut.set_result, result
                        )
                    elif not fut.done():
                        fut.set_result(result)
                continue

    except Exception as e:
        log.debug(f"[extension] Обрыв: {e}")
    finally:
        if _extension_ws is websocket:
            _extension_ws = None
        log.info("[extension] Расширение отключено")


async def start():
    """Запускает локальный WS сервер для расширения на первом свободном порту.

    Берёт первый свободный порт из config.EXTENSION_PORTS; выбранный порт —
    в лог один раз, после успешной привязки. При ошибке привязки (WinError
    10013/10048 — на Windows чужой эксклюзивный сокет отвечает «отказано в
    доступе», а не «адрес занят») пробрасывает исключение наружу: паузу
    между попытками держит _run_ext_server, а не этот модуль.
    """
    global _bind_error_logged
    try:
        import websockets
        from config import EXTENSION_PORTS
    except ImportError as e:
        raise RuntimeError(f"extension_server: нет зависимостей: {e}") from e

    last_err: Exception | None = None
    for port in EXTENSION_PORTS:
        try:
            async with websockets.serve(
                _handler, "127.0.0.1", port,
                reuse_address=True,
            ):
                global EXTENSION_PORT
                EXTENSION_PORT = port
                _bind_error_logged = False  # серия неудач кончилась
                log.info(f"[extension] Сервер запущен на ws://127.0.0.1:{port}")
                await asyncio.Future()  # сервер живёт до отмены/обрыва цикла
        except OSError as e:
            # Занятый порт — не фатально: пробуем следующий из списка.
            if not _bind_error_logged:
                log.error(
                    f"[extension] Порт {port} недоступен "
                    f"({e.errno} — {e.strerror}): занят другой программой. "
                    f"Пробую следующий из {EXTENSION_PORTS}"
                )
                _bind_error_logged = True
            last_err = e
            continue
    # Все порты заняты — наверх, в _run_ext_server (там backoff и ретрай).
    raise RuntimeError(
        f"extension_server: ни один порт не подошёл: {EXTENSION_PORTS} "
        f"(последняя ошибка: {last_err})"
    )
