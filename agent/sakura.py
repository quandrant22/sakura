"""
sakura.py — точка входа агента (Фаза 2).

Изменения: подключён сигнал moodUpdate → overlay.set_mood().
"""

import asyncio
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / "sakura.log"

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s  %(message)s")

file_handler = RotatingFileHandler(
    log_path,
    maxBytes=2 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

log = logging.getLogger("sakura")

from core.exception_hooks import install_exception_hooks

install_exception_hooks(log)

from PyQt6.QtCore import QSharedMemory
from PyQt6.QtWidgets import QApplication

from core.agent import Agent
from core.events import EventBus
from core.hands import get_command_registry
from core.music_listener import start as start_music_listener
from ui.app import UiBridge, build_tray
from ui.overlay import Overlay


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Сакура")
    app.setQuitOnLastWindowClosed(False)

    guard = QSharedMemory("sakura-agent-singleton")
    if not guard.create(1):
        log.warning("Сакура уже запущена.")
        return

    get_command_registry()

    bus     = EventBus()
    agent   = Agent(bus)
    bridge  = UiBridge(bus)
    overlay = Overlay()

    bridge.stateChanged.connect(overlay.set_state)
    bridge.userText.connect(overlay.add_user_message)
    bridge.sakuraText.connect(overlay.add_sakura_message)
    bridge.connectionChanged.connect(overlay.set_connected)
    bridge.moodUpdate.connect(overlay.set_mood)        # ← Фаза 2
    bridge.gameMode.connect(overlay.set_game_mode)
    bridge.micLevel.connect(overlay.hud.set_audio_level)
    bridge.orbArrival.connect(overlay.animate_arrival)
    bridge.orbDeparture.connect(overlay.animate_departure)
    overlay.submit.connect(agent.submit_user_text)

    app.tray = build_tray(app, overlay)

    # Захват системного аудио для эквалайзера
    # Используем Qt сигнал для thread-safe обновления UI
    def _on_music_bars(bars: list):
        bridge.micLevel.emit(bars)  # thread-safe через Qt signal

    start_music_listener(callback=_on_music_bars)

    threading.Thread(target=lambda: asyncio.run(agent.run()), daemon=True).start()

    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()