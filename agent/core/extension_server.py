"""
core/extension_server.py — локальный WebSocket сервер для расширения браузера.

Слушает на ws://127.0.0.1:8766.
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

log = logging.getLogger("sakura.extension")

EXTENSION_PORT = 8766

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
    """Запускает локальный WS сервер для расширения."""
    try:
        import websockets
        log.info(f"[extension] Сервер запущен на ws://127.0.0.1:{EXTENSION_PORT}")
        async with websockets.serve(
            _handler, "127.0.0.1", EXTENSION_PORT,
            reuse_address=True,
        ):
            await asyncio.Future()
    except Exception as e:
        log.error(f"[extension] Ошибка сервера: {e}")
