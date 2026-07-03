"""Sakura Agent v2 — Overlay UI

Minimal transparent overlay with orb animation.
"""

import math
import random
import sys
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient, QLinearGradient
from PyQt6.QtWidgets import QApplication, QWidget


# Colors
COLOR_IDLE = QColor(154, 127, 181)      # Purple
COLOR_LISTENING = QColor(232, 154, 214)  # Pink
COLOR_THINKING = QColor(185, 138, 255)   # Blue-purple
COLOR_SPEAKING = QColor(255, 134, 184)   # Sakura pink

STATE_COLORS = {
    "idle": COLOR_IDLE,
    "listening": COLOR_LISTENING,
    "thinking": COLOR_THINKING,
    "speaking": COLOR_SPEAKING,
}


class OrbWidget(QWidget):
    """Animated orb widget."""

    def __init__(self, size=150):
        super().__init__()
        self.size = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._state = "idle"
        self._phase = 0.0
        self._pulse = 0.0
        self._color = COLOR_IDLE

        # Animation timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._update)
        self._timer.start(16)  # 60 FPS

    def set_state(self, state: str):
        self._state = state
        self._color = STATE_COLORS.get(state, COLOR_IDLE)

    def _update(self):
        self._phase += 0.05
        self._pulse = (math.sin(self._phase) + 1) / 2
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.size / 2
        cy = self.size / 2
        radius = self.size * 0.35

        # Glow
        glow_radius = radius * (1.2 + self._pulse * 0.3)
        glow_color = QColor(self._color)
        glow_color.setAlpha(int(40 + self._pulse * 30))

        gradient = QRadialGradient(QPointF(cx, cy), glow_radius)
        gradient.setColorAt(0, glow_color)
        gradient.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        # Core
        core_radius = radius * (0.9 + self._pulse * 0.1)
        core_gradient = QRadialGradient(QPointF(cx - radius * 0.3, cy - radius * 0.3), core_radius * 1.5)
        core_gradient.setColorAt(0, QColor(255, 255, 255, 200))
        core_gradient.setColorAt(0.3, self._color)
        core_gradient.setColorAt(1, QColor(self._color.darker(150)))

        painter.setBrush(core_gradient)
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1.5))
        painter.drawEllipse(QPointF(cx, cy), core_radius, core_radius)

        # Highlight
        highlight_radius = core_radius * 0.4
        highlight_gradient = QRadialGradient(
            QPointF(cx - core_radius * 0.2, cy - core_radius * 0.3),
            highlight_radius
        )
        highlight_gradient.setColorAt(0, QColor(255, 255, 255, 180))
        highlight_gradient.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(highlight_gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QPointF(cx - core_radius * 0.2, cy - core_radius * 0.3),
            highlight_radius, highlight_radius * 0.6
        )


class SakuraOverlay(QWidget):
    """Main overlay window."""

    submit = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sakura")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Orb
        self.orb = OrbWidget(150)
        self.orb.setParent(self)

        # State
        self._state = "idle"
        self._connected = False

        # Layout
        self.setFixedSize(180, 180)
        self.orb.move(15, 15)

        # Draggable
        self._drag_pos = None

    def set_state(self, state: str):
        self._state = state
        self.orb.set_state(state)

    def set_connected(self, connected: bool):
        self._connected = connected

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Border glow when connected
        if self._connected:
            pen = QPen(QColor(154, 127, 181, 40), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(90, 90), 85, 85)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sakura")

    overlay = SakuraOverlay()
    overlay.show()

    # Demo state changes
    def cycle_states():
        states = ["idle", "listening", "thinking", "speaking"]
        i = 0
        def update():
            nonlocal i
            overlay.set_state(states[i % len(states)])
            i += 1
        timer = QTimer()
        timer.timeout.connect(update)
        timer.start(2000)

    # Uncomment to demo:
    # cycle_states()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
