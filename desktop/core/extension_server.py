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
import os
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
_extension_version = None      # версия из extension_ready (Настройки → Расширение браузера)
_extension_id = None           # ID подключённого расширения (из Origin) — для закрепления
_server_loop = None            # цикл потока сервера: запись в сокет — только в нём
_status_listener = None        # подключение/версия изменились → обновить настройки в интерфейсе
_upload_store = None           # desktop.core.upload_store.UploadStore для page.upload


def is_connected() -> bool:
    return _extension_ws is not None


def get_status() -> dict:
    """Статус расширения для диагностики."""
    return {
        "connected": _extension_ws is not None,
        "pending": len(_pending),
        "version": _extension_version,
        "extension_id": _extension_id,
    }


def set_status_listener(fn) -> None:
    global _status_listener
    _status_listener = fn


def set_upload_store(store) -> None:
    global _upload_store
    _upload_store = store


def _notify_status() -> None:
    fn = _status_listener
    if fn is None:
        return
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        log.debug(f"[extension] status listener: {type(e).__name__}")


_agent_loop = None  # event loop основного агента


def set_agent_loop(loop):
    global _agent_loop
    _agent_loop = loop


def next_restart_delay(fail_count: int) -> int:
    """Пауза после fail_count подряд неудач: 5, 10, 30, 60, 60, …"""
    if fail_count < len(RESTART_DELAYS):
        return RESTART_DELAYS[fail_count]
    return RESTART_MAX_DELAY


def _allowed_origins():
    """Return the configured extension ID, or empty for any Chrome extension."""
    return os.getenv("SAKURA_EXTENSION_ID", "").strip()


def _origin_allowed(origin: str | None) -> bool:
    if not origin or not origin.startswith("chrome-extension://"):
        return False
    extension_id = origin.removeprefix("chrome-extension://")
    if not extension_id:
        return False
    configured_id = _allowed_origins()
    return not configured_id or extension_id == configured_id


def _request_origin(websocket) -> str | None:
    request = getattr(websocket, "request", None)
    headers = getattr(request, "headers", None)
    if headers is not None:
        return headers.get("Origin")
    legacy_headers = getattr(websocket, "request_headers", None)
    if legacy_headers is not None:
        return legacy_headers.get("Origin")
    return None


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


async def _send_json(ws, payload: dict) -> None:
    """Запись в сокет расширения. Сокет живёт в цикле потока сервера, а команды идут из цикла
    агента — запись переносится в цикл сервера (транспорт asyncio не потокобезопасен)."""
    data = json.dumps(payload, ensure_ascii=False)
    srv = _server_loop
    if srv is not None and srv is not asyncio.get_running_loop() and srv.is_running():
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(ws.send(data), srv))
    else:
        await ws.send(data)


def _resolve(fut, result) -> None:
    if not fut.done():
        fut.set_result(result)


async def send_command(action: str, arg: str = "", timeout: float = 8.0, args: dict | None = None) -> dict:
    """
    Отправляет команду расширению и ждёт результата.
    Поддерживает все команды: tabs, navigation, bookmarks, history, youtube, forms, etc.
    args — аргументы действий агента браузера (tabs.*, agent_window.*, page.*).
    Произвольный JS (js_exec) отсюда не отправляется: в реестре команд его нет.
    """
    ws = _extension_ws
    if not ws:
        return {"ok": False, "error": "Расширение не подключено"}

    import uuid
    cmd_id = str(uuid.uuid4())[:8]
    loop   = asyncio.get_running_loop()
    fut    = loop.create_future()
    _pending[cmd_id] = fut

    payload = {"id": cmd_id, "action": action, "arg": arg}
    if args is not None:
        payload["args"] = args
    try:
        await _send_json(ws, payload)
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        _pending.pop(cmd_id, None)
        return {"ok": False, "error": "Тайм-аут расширения"}
    except Exception as e:
        _pending.pop(cmd_id, None)
        return {"ok": False, "error": str(e)}


async def _serve_upload(websocket, msg: dict) -> None:
    """upload_fetch {id, file_token} → upload_data {id, ok, name, mime, data_b64 | error}.
    В журнал — только размер, без имени и содержимого файла."""
    reply = {"type": "upload_data", "id": msg.get("id")}
    store = _upload_store
    if store is None:
        reply.update(ok=False, error="загрузка файлов не настроена")
    else:
        try:
            item = await asyncio.to_thread(store.take, str(msg.get("file_token") or ""))
            reply.update(ok=True, **item)
            log.info("[extension] upload_fetch: %d байт", item.get("size", 0))
        except Exception as e:  # noqa: BLE001 — текст UploadError без пути; прочее — общий отказ
            reply.update(ok=False, error=str(e) if type(e).__name__ == "UploadError" else "файл не прочитан")
            log.info("[extension] upload_fetch: отказ")
    try:
        await websocket.send(json.dumps(reply, ensure_ascii=False))
    except Exception:
        pass


async def _handler(websocket):
    global _extension_ws, _last_activity, _extension_version, _extension_id, _server_loop

    # Если уже есть живое соединение — закрываем новое
    if _extension_ws is not None:
        try:
            await _extension_ws.ping()
            await websocket.close(1008, "Already connected")
            return
        except Exception:
            pass

    origin = _request_origin(websocket)
    if not _origin_allowed(origin):
        log.warning("[extension] Отклонено соединение с Origin=%r", origin)
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    # Представляемся первым сообщением: расширение ждёт sakura_hello не
    # дольше секунды и уходит к следующему порту, если на том конце не
    # Сакура (в бою 8766 держал VS Code — без проверки расширение слало
    # команды ему). Единственное изменение протокола агент↔расширение;
    # протокол агент↔VPS не тронут.
    try:
        await websocket.send(json.dumps(
            {"type": "sakura_hello", "version": "3.1.0"}))
    except Exception:
        return

    _extension_ws = websocket
    _server_loop = asyncio.get_running_loop()
    _extension_id = origin.removeprefix("chrome-extension://")
    _extension_version = None
    _last_activity = asyncio.get_running_loop().time()
    log.info("[extension] Расширение подключено")
    _notify_status()

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            _last_activity = asyncio.get_running_loop().time()
            msg_type = msg.get("type", "")

            if msg_type == "extension_ready":
                _extension_version = str(msg.get("version") or "")[:20] or None
                log.info(f"[extension] Готово, версия {msg.get('version', '?')}")
                _notify_status()
                continue

            if msg_type == "upload_fetch":
                asyncio.ensure_future(_serve_upload(websocket, msg))
                continue

            if msg_type == "extension_result":
                cmd_id = msg.get("id")
                if cmd_id and cmd_id in _pending:
                    fut = _pending.pop(cmd_id)
                    result = msg.get("result", {})
                    # Будущее создано в цикле вызывающего (обычно агента) — разрешаем там же.
                    fut_loop = fut.get_loop()
                    if fut_loop is not asyncio.get_running_loop():
                        fut_loop.call_soon_threadsafe(_resolve, fut, result)
                    else:
                        _resolve(fut, result)
                continue

    except Exception as e:
        log.debug(f"[extension] Обрыв: {e}")
    finally:
        if _extension_ws is websocket:
            _extension_ws = None
            _extension_version = None
        log.info("[extension] Расширение отключено")
        _notify_status()


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

        from desktop.core.config import EXTENSION_PORTS
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
