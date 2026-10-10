"""desktop.overlay.adapter — старый PyQt6-оверлей (agent/ui/overlay.py) на локальном API ядра.

Вид оверлея не меняется: адаптер только переводит события API в вызовы тех же
методов, что дёргал agent/sakura.py через UiBridge, а ввод из оверлея
(overlay.submit) отправляет командой send_text.
"""
import json
import os
import sys

# События локального API → (путь к методу оверлея, аргументы).
# Пути через точку: "hud.set_audio_level" — метод вложенного SphereCore.


def route(event: dict) -> list[tuple[str, tuple]]:
    kind = event.get("type")
    if kind == "state":
        return [("set_state", (event.get("value", "idle"),))]
    if kind == "chat_message":
        m = event.get("message") or {}
        method = {"user": "add_user_message", "assistant": "add_sakura_message",
                  "system": "add_system_message"}.get(m.get("role"))
        return [(method, (m.get("text", ""),))] if method else []
    if kind == "connection":
        return [("set_connected", (event.get("server") == "online",))]
    if kind == "game_mode":
        return [("set_game_mode", (bool(event.get("on")),))]
    if kind == "notify":
        return [("add_system_message", (event.get("text", ""),))]
    if kind == "orb_arrival":
        return [("animate_arrival", ())]
    if kind == "orb_departure":
        return [("animate_departure", ())]
    if kind == "mood":
        return [("set_mood", (event.get("params") or {},))]
    if kind == "audio_level":
        return [("hud.set_audio_level", (event.get("bars") or [],))]
    return []


def read_token_file(path: str) -> tuple[int, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return int(data["port"]), str(data["token"])


def _import_legacy_overlay():
    """agent/ui/overlay.py ждёт модуль `config` и пакет `core` из agent/."""
    from desktop.core import config as desktop_config

    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    agent_dir = os.path.join(repo, "agent")
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    sys.modules.setdefault("config", desktop_config)
    from ui.overlay import Overlay
    return Overlay


def main() -> int:  # pragma: no cover — ручной запуск (нужен экран)
    import asyncio
    import threading

    import websockets
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication

    from desktop.core.api.server import default_token_path

    app = QApplication(sys.argv)
    app.setApplicationName("Сакура — оверлей")
    Overlay = _import_legacy_overlay()
    overlay = Overlay()

    class Bridge(QObject):
        event = pyqtSignal(dict)

    bridge = Bridge()
    outbox: list[str] = []

    def apply(ev: dict):
        for path, args in route(ev):
            target = overlay
            for part in path.split("."):
                target = getattr(target, part)
            target(*args)

    bridge.event.connect(apply)

    async def client():
        while True:
            try:
                port, token = read_token_file(default_token_path())
                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    await ws.send(json.dumps({"type": "hello", "token": token, "client": "overlay"}))

                    async def pump():
                        while True:
                            while outbox:
                                await ws.send(outbox.pop(0))
                            await asyncio.sleep(0.05)
                    pump_task = asyncio.ensure_future(pump())
                    try:
                        async for raw in ws:
                            bridge.event.emit(json.loads(raw))
                    finally:
                        pump_task.cancel()
            except (OSError, ValueError, KeyError, websockets.WebSocketException):
                bridge.event.emit({"type": "connection", "server": "offline"})
            await asyncio.sleep(2)

    overlay.submit.connect(lambda text: outbox.append(json.dumps(
        {"type": "send_text", "request_id": "overlay", "text": text})))
    threading.Thread(target=lambda: asyncio.run(client()), daemon=True).start()
    overlay.show()
    return app.exec()
