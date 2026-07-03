"""ui/app.py — мост между шиной событий и Qt."""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap


class UiBridge(QObject):
    stateChanged      = pyqtSignal(str)
    userText          = pyqtSignal(str)
    sakuraText        = pyqtSignal(str)
    connectionChanged = pyqtSignal(bool)
    gameMode          = pyqtSignal(bool)
    moodUpdate        = pyqtSignal(dict)
    orbArrival        = pyqtSignal()
    orbDeparture      = pyqtSignal()
    micLevel          = pyqtSignal(list)

    def __init__(self, bus):
        super().__init__()

        def _on_event(event: str, data: dict):
            if event == "state":
                self.stateChanged.emit(data.get("value", "idle"))
            elif event == "user_text":
                self.userText.emit(data.get("text", ""))
            elif event == "sakura_text":
                self.sakuraText.emit(data.get("text", ""))
            elif event == "connection":
                self.connectionChanged.emit(data.get("online", False))
            elif event == "game_mode":
                self.gameMode.emit(data.get("on", False))
            elif event == "mood_update":
                self.moodUpdate.emit(data.get("params", {}))
            elif event == "orb_arrival":
                self.orbArrival.emit()
            elif event == "orb_departure":
                self.orbDeparture.emit()

        bus.subscribe(_on_event)


def _make_icon(color: str = "#9a7fb5") -> QIcon:
    px = QPixmap(16, 16)
    px.fill(QColor(color))
    return QIcon(px)


def build_tray(app: QApplication, overlay) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_make_icon(), app)
    menu = QMenu()
    menu.addAction("Показать / скрыть", lambda: overlay.setVisible(not overlay.isVisible()))
    menu.addSeparator()

    game_action = QAction("Игровой режим (клик-сквозь)", app)
    game_action.setCheckable(True)
    game_action.toggled.connect(overlay.set_game_mode)
    menu.addAction(game_action)

    menu.addSeparator()
    menu.addAction("Выход", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: overlay.setVisible(not overlay.isVisible())
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    return tray