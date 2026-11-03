"""ui/app.py — мост между шиной событий и Qt."""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)


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
    agentAlert        = pyqtSignal(str)
    secureStatus      = pyqtSignal(bool, str)
    pairResult        = pyqtSignal(str)

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
            elif event == "agent_alert":
                self.agentAlert.emit(data.get("text", ""))
            elif event == "secure_status":
                self.secureStatus.emit(bool(data.get("secure")), data.get("text", ""))

        bus.subscribe(_on_event)


def _make_icon(color: str = "#9a7fb5") -> QIcon:
    px = QPixmap(16, 16)
    px.fill(QColor(color))
    return QIcon(px)


def build_tray(app: QApplication, overlay, bridge=None, agent=None) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_make_icon(), app)
    tray.setToolTip("Сакура")
    menu = QMenu()
    # Статус канала: 🔒 только при Noise (conn.secure)
    status_action = QAction("подключение…", app)
    status_action.setEnabled(False)
    menu.addAction(status_action)
    if bridge is not None:
        def _sync_secure(secure: bool, text: str):
            status_action.setText(text)
            tray.setToolTip(f"Сакура — {text}")
        bridge.secureStatus.connect(_sync_secure)
    if agent is not None and bridge is not None:
        add_pairing_actions(menu, app, agent, bridge, tray)
    menu.addSeparator()
    menu.addAction("Показать / скрыть", lambda: overlay.setVisible(not overlay.isVisible()))
    menu.addSeparator()

    game_action = QAction("Игровой режим (клик-сквозь)", app)
    game_action.setCheckable(True)
    game_action.toggled.connect(overlay.set_game_mode)
    menu.addAction(game_action)
    if bridge is not None:
        # Синхронизация галочки с bridge.gameMode без цикла сигналов
        def _sync_game_mode(on: bool):
            game_action.blockSignals(True)
            try:
                game_action.setChecked(bool(on))
            finally:
                game_action.blockSignals(False)
        bridge.gameMode.connect(_sync_game_mode)

    menu.addSeparator()
    menu.addAction("Выход", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: overlay.setVisible(not overlay.isVisible())
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    return tray

def add_pairing_actions(menu: QMenu, app, agent, bridge, tray) -> None:
    """«Спарить с сервером…» и «Сбросить спаривание» (ТЗ-4).

    Код (QR-строка или 8 слов) вводится скрыто и не журналируется; спаривание
    идёт в цикле агента, итог — в окне и в оверлее.
    """
    def _show(text: str):
        ok = text.startswith(("Спарено", "Спаривание сброшено"))
        box = QMessageBox.information if ok else QMessageBox.warning
        box(None, "Сакура — спаривание", text)

    bridge.pairResult.connect(_show)

    def _pair():
        code, ok = QInputDialog.getText(
            None, "Спарить с сервером",
            "Telegram: /pair. Вставьте QR-строку (sakura-pair://…) — предпочтительно,\n"
            "или введите 8 слов. Ввод скрыт.",
            QLineEdit.EchoMode.Password)
        if not ok or not code.strip():
            return
        if not agent.run_in_loop(agent.pair_device, code, done=bridge.pairResult.emit):
            _show("Агент ещё не запущен — повторите через несколько секунд")

    def _reset():
        if QMessageBox.question(None, "Сакура", "Удалить ключи устройства? Потребуется "
                                "новое спаривание.") != QMessageBox.StandardButton.Yes:
            return
        agent.run_in_loop(agent.reset_pairing, done=bridge.pairResult.emit)

    menu.addAction("Спарить с сервером…", _pair)
    menu.addAction("Сбросить спаривание", _reset)
