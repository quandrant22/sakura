"""ui/overlay.py — присутствие Сакуры. HUD-ядро в стиле Япония × будущее.

Арк-реактор: ядро + встречно вращающиеся тех-кольца, угловые скобки, катакана,
ветвь сакуры над панелью. Имя SAKURA (Orbitron) с неоновым свечением.
Дремлет в простое (анимация выключена → нулевая нагрузка), оживает при обращении.
Чат спрятан: реплика всплывает и тает; полная история — по кнопке. Окно тянется за угол.
"""

import ctypes
import math
import os
import random
import sys
from html import escape

from PyQt6.QtCore import (Qt, QTimer, QPoint, QPointF, QRectF, QSettings,
                          QPropertyAnimation, QEasingCurve, pyqtSignal,
                          qInstallMessageHandler)
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QLinearGradient, QPainterPath,
                         QPen, QRadialGradient)
from PyQt6.QtWidgets import (QApplication, QGraphicsDropShadowEffect,
                             QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QSizeGrip, QTextEdit,
                             QVBoxLayout, QWidget)

import config

def _qt_quiet(mode, ctx, msg):
    if "UpdateLayeredWindowIndirect" in msg or "SetProcessDpiAwareness" in msg:
        return
    sys.stderr.write(msg + "\n")


qInstallMessageHandler(_qt_quiet)


# Палитра «Япония × будущее»: cyan-будущее + золото + сакура-розовый.
_STATE = {
    "idle":      {"color": "#9a7fb5", "vibe": "standby",   "kana": "待機中"},
    "listening": {"color": "#e89ad6", "vibe": "listening", "kana": "聴取中"},
    "thinking":  {"color": "#b98aff", "vibe": "thinking",  "kana": "思考中"},
    "speaking":  {"color": "#ff86b8", "vibe": "speaking",  "kana": "発話中"},
}
_ACTIVE = ("listening", "thinking", "speaking")

_PANEL_BG     = QColor(9, 14, 22, 210)
_PANEL_BORDER = QColor(120, 200, 255, 52)
_BRANCH       = QColor(90, 58, 68)
_PETAL        = QColor(255, 143, 200)
_PETAL_LIGHT  = QColor(255, 217, 234)

_DEF_W, _DEF_H = 360, 540
_MIN_W, _MIN_H = 300, 430
_GAME_SIZE     = 150


def _load_orbitron() -> str:
    path = os.path.join(config.BASE_DIR, "Orbitron.ttf")
    if os.path.exists(path):
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            return fams[0]
    return "Segoe UI"


class _Petal:
    """Падающий лепесток сакуры — постоянное движение, «она живая»."""
    def __init__(self, w, h, top=False):
        self.reset(w, h, top)

    def reset(self, w, h, top=True):
        self.x = random.uniform(0, max(1, w))
        self.y = random.uniform(-12, 0) if top else random.uniform(0, max(1, h))
        self.vy = random.uniform(0.4, 1.0)
        self.vx = random.uniform(-0.25, 0.25)
        self.size = random.uniform(3.0, 6.0)
        self.rot = random.uniform(0, 360)
        self.vr = random.uniform(-2.2, 2.2)
        self.sway = random.uniform(0, 6.28)

    def step(self, w, h):
        self.sway += 0.045
        self.y += self.vy
        self.x += self.vx + math.sin(self.sway) * 0.4
        self.rot += self.vr
        if self.y > h + 12:
            self.reset(w, h, top=True)


class SphereCore(QWidget):
    """Живая сфера: глянцевое ядро, кольца, лепестки, эхо личности. Анимация не выключается."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(120, 120)
        self._state = "idle"
        self._a1 = 0.0
        self._a2 = 0.0
        self._phase = 0.0
        self._echo = 0.0
        self._audio_level = 0.0
        self._tts_level = 0.0
        self._cloud = [0.0, 2.1, 4.2]
        self._ghost = 0.0
        self._ghost_dir = 1
        self._ripples = []
        self._rip_acc = 0
        self._petals = []
        self._eq_bars    = [0.05] * 8
        self._eq_target  = [0.05] * 8
        self._game_mode  = False
        self._mood_color = None    # цвет от mood_vector
        self._mood_pulse = 0.05
        self._mood_pet_spd = 1.0
        self._mood_weather = "clear"
        self._breathe_phase = 0.0  # ambient breathing
        self._breathe_amp = 0.0    # текущая амплитуда дыхания
        import random as _rr
        self._col_weights = [_rr.uniform(0.75, 1.25) for _ in range(20)]
        self._col_targets = [0.0] * 20
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_audio_level(self, bars):
        """Обновляет полосы эквалайзера. bars: список float 0..1 длиной 8."""
        if isinstance(bars, (int, float)):
            # Старый формат — одно число, конвертируем в 8 полос
            level = float(bars)
            import random
            bars = [min(1.0, level * random.uniform(0.5, 1.5)) for _ in range(8)]
        if not isinstance(bars, list) or len(bars) == 0:
            return
        self._eq_target = bars[:8] if len(bars) >= 8 else bars + [0.05]*(8-len(bars))

    def set_eq_speaking(self, active: bool):
        """Анимация эквалайзера когда Сакура говорит."""
        import random
        if active:
            self._eq_target = [random.uniform(0.3, 1.0) for _ in range(8)]
        else:
            self._eq_target = [0.05] * 8

    def set_mood(self, params: dict):
        """Принимает орб-параметры из mood_vector.get_orb_params()."""
        if not params:
            return
        try:
            from PyQt6.QtGui import QColor as _QC
            if "color" in params:
                self._mood_color = _QC(params["color"])
        except Exception:
            pass
        self._mood_pulse   = float(params.get("pulse_amp",   getattr(self, "_mood_pulse",   0.05)))
        self._mood_pet_spd = float(params.get("petal_speed", getattr(self, "_mood_pet_spd", 1.0)))
        self._mood_weather = str(  params.get("inner_weather",getattr(self, "_mood_weather","clear")))

        # Плавное обновление цвета колец и скобок
        try:
            from PyQt6.QtGui import QColor as _QC
            if "color" in params:
                self._ring_color = _QC(params["color"])
        except Exception:
            pass

    def set_game_mode_flag(self, on: bool):
        self._game_mode = on

    def set_state(self, state: str):
        self._state = state
        self._timer.start(33 if state in _ACTIVE else 50)
        self.update()

    def set_audio_level(self, bars):
        """Принимает список полос или одно число."""
        if isinstance(bars, list):
            self._eq_target = bars[:8] if len(bars) >= 8 else bars + [0.05]*(8-len(bars))
            # Среднее для общего уровня
            self._audio_level = sum(bars)/len(bars) if bars else 0.0
        else:
            level = float(bars)
            self._audio_level = max(0.0, min(1.0, level))
            import random
            self._eq_target = [min(1.0, level * random.uniform(0.5, 1.5)) for _ in range(8)]

    def set_tts_level(self, level: float):
        self._tts_level = max(0.0, min(1.0, level))

    def _tick(self):
        active = self._state in _ACTIVE
        self._a1 = (self._a1 + (0.5 if active else 0.12)) % 360
        self._a2 = (self._a2 - (1.1 if active else 0.05)) % 360
        self._phase = (self._phase + (0.10 if active else 0.045)) % (2 * math.pi)
        self._echo = (self._echo + 0.010) % (2 * math.pi)
        self._cloud[0] += 0.008
        self._cloud[1] += 0.006
        self._cloud[2] += 0.004

        # Ambient breathing — плавное дыхание в idle
        self._breathe_phase = (self._breathe_phase + 0.015) % (2 * math.pi)
        if not active:
            # Плавное нарастание амплитуды дыхания
            target_amp = 0.03 + 0.02 * math.sin(self._breathe_phase)
            self._breathe_amp += (target_amp - self._breathe_amp) * 0.05
        else:
            self._breathe_amp *= 0.9  # быстрое затухание при активности

        if random.random() < 0.002:
            self._ghost_dir = 1
        self._ghost += 0.004 * self._ghost_dir
        if self._ghost > 1.0:
            self._ghost_dir = -1
        elif self._ghost < 0.0:
            self._ghost = 0.0
        for p in self._petals:
            p.step(self.width(), self.height())
        if self._state == "listening":
            self._rip_acc += 1
            if self._rip_acc >= 22:
                self._rip_acc = 0
                self._ripples.append(0.0)
            self._ripples = [r + 0.02 for r in self._ripples if r < 1.0]
        else:
            self._ripples = []

        # Плавная интерполяция полос эквалайзера
        target  = getattr(self, '_eq_target', [0.05] * 8)
        current = getattr(self, '_eq_bars', [0.05] * 8)
        self._eq_bars = [
            c + (t - c) * 0.5
            for c, t in zip(current, target)
        ]
        # Обновляем индивидуальные уровни колонок
        avg = sum(self._eq_bars) / 8
        import random as _r
        for i in range(20):
            noise = _r.uniform(-0.15, 0.15)
            col_t = min(1.0, max(0.0, avg * self._col_weights[i] + noise))
            prev  = self._col_targets[i]
            # Быстрый рост, медленный спад
            if col_t > prev:
                self._col_targets[i] = prev + (col_t - prev) * 0.9
            else:
                self._col_targets[i] = prev + (col_t - prev) * 0.2
        self.update()

    def _draw_petal(self, p, pt):
        p.save()
        p.translate(pt.x, pt.y)
        p.rotate(pt.rot)
        p.setPen(Qt.PenStyle.NoPen)
        # Лепестки — миксуются с mood цветом
        mood_c = getattr(self, '_mood_color', None)
        if mood_c:
            # Розовый + mood оттенок
            base = QColor(mood_c)
            col = QColor(
                min(255, (base.red() + 255) // 2),
                min(255, (base.green() + 168) // 2),
                min(255, (base.blue() + 196) // 2),
                140
            )
        else:
            col = QColor("#f7a8c4"); col.setAlpha(140)
        p.setBrush(col)
        p.drawEllipse(QPointF(0, 0), pt.size * 0.6, pt.size)
        lig = QColor("#ffd9ea"); lig.setAlpha(110)
        p.setBrush(lig)
        p.drawEllipse(QPointF(0, -pt.size * 0.2), pt.size * 0.3, pt.size * 0.5)
        p.restore()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if not self._petals and w > 10:
            self._petals = [_Petal(w, h) for _ in range(7)]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = w / 2, h / 2
        center = QPointF(cx, cy)
        c = QColor(_STATE[self._state]["color"])
        active = self._state in _ACTIVE
        pulse = (math.sin(self._phase) + 1) / 2
        R = min(w, h) / 2 - 6

        # лепестки (фон)
        for pt in self._petals:
            self._draw_petal(p, pt)

        # тиковое кольцо — используем mood цвет если есть
        ring_c = getattr(self, '_ring_color', None) or c
        p.save(); p.translate(cx, cy); p.rotate(self._a1)
        tick = QColor(ring_c); tick.setAlpha(150 if active else 90)
        p.setPen(QPen(tick, 1.0))
        for i in range(60):
            a = 2 * math.pi * i / 60
            p.drawLine(QPointF(R * 0.92 * math.cos(a), R * 0.92 * math.sin(a)),
                       QPointF(R * 0.99 * math.cos(a), R * 0.99 * math.sin(a)))
        p.restore()

        # сегментное кольцо
        p.save(); p.translate(cx, cy); p.rotate(self._a2)
        seg = QColor(ring_c); seg.setAlpha(210 if active else 110)
        p.setPen(QPen(seg, max(2.0, R * 0.03))); p.setBrush(Qt.BrushStyle.NoBrush)
        rr = R * 0.78; rect = QRectF(-rr, -rr, 2 * rr, 2 * rr)
        for st, sp in ((0, 55), (120, 40), (200, 70)):
            p.drawArc(rect, st * 16, sp * 16)
        p.restore()

        # скобки
        br, bl = R * 0.50, R * 0.12
        bc = QColor(ring_c); bc.setAlpha(170 if active else 90)
        p.setPen(QPen(bc, 1.5))
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x, y = cx + sx * br, cy + sy * br
            p.drawLine(QPointF(x, y), QPointF(x - sx * bl, y))
            p.drawLine(QPointF(x, y), QPointF(x, y - sy * bl))

        # катакана сверху / кандзи состояния снизу
        f = QFont(); f.setPointSizeF(max(7.0, R * 0.075)); p.setFont(f)
        lab = QColor(c); lab.setAlpha(180 if active else 120); p.setPen(lab)
        # катакана выводится через QLabel в Overlay

        # listening: расходящиеся круги
        for r in self._ripples:
            rc2 = QColor(c); rc2.setAlpha(int(130 * (1 - r)))
            p.setPen(QPen(rc2, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            rad = R * 0.46 + r * R * 0.30 + self._audio_level * R * 0.12
            p.drawEllipse(center, rad, rad)

        # thinking: частицы по орбите
        if self._state == "thinking":
            for i in range(6):
                ang = math.radians(self._a2 + i * 60)
                pr = R * 0.62
                dc = QColor(c); dc.setAlpha(200)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(dc)
                p.drawEllipse(QPointF(cx + pr * math.cos(ang), cy + pr * math.sin(ang)), 2.4, 2.4)

        # halo
        halo = QRadialGradient(center, R * 0.52)
        hin = QColor(c); hin.setAlpha(int(55 + pulse * 60))
        hout = QColor(c); hout.setAlpha(0)
        halo.setColorAt(0.0, hin); halo.setColorAt(1.0, hout)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(halo)
        p.drawEllipse(center, R * 0.52, R * 0.52)

        # сфера (глянец) — с учётом mood-цвета и дыхания
        mood_c = getattr(self, '_mood_color', None)
        if mood_c:
            # Микшуем state-цвет с mood-цветом (70% mood, 30% state)
            c = QColor(mood_c)
            sc = QColor(_STATE[self._state]["color"])
            mix_r = int(c.red() * 0.7 + sc.red() * 0.3)
            mix_g = int(c.green() * 0.7 + sc.green() * 0.3)
            mix_b = int(c.blue() * 0.7 + sc.blue() * 0.3)
            c = QColor(mix_r, mix_g, mix_b)
        else:
            c = QColor(_STATE[self._state]["color"])

        base_amp = {"idle": 0.03, "listening": 0.08, "thinking": 0.05, "speaking": 0.10}.get(self._state, 0.03)
        # Ambient breathing добавляется к амплитуде
        amp = base_amp + self._breathe_amp
        rc = R * 0.34 * (1 + amp * math.sin(self._phase))

        # Динамический градиент сферы — зависит от mood
        if mood_c:
            # Тёплые тона для положительного valence, холодные для отрицательного
            grad = QRadialGradient(QPointF(cx - rc * 0.35, cy - rc * 0.4), rc * 1.7)
            grad.setColorAt(0.00, QColor("#eef0ff"))
            grad.setColorAt(0.25, QColor(mood_c))
            grad.setColorAt(0.60, QColor(c.red()//2, c.green()//2, c.blue()//2))
            grad.setColorAt(1.00, QColor("#1a0a20"))
        else:
            grad = QRadialGradient(QPointF(cx - rc * 0.35, cy - rc * 0.4), rc * 1.7)
            grad.setColorAt(0.00, QColor("#eef0ff"))
            grad.setColorAt(0.18, QColor("#dccaf0"))
            grad.setColorAt(0.50, QColor("#cba4dd"))
            grad.setColorAt(0.80, QColor("#a86fc0"))
            grad.setColorAt(0.95, QColor("#5e3a72"))
            grad.setColorAt(1.00, QColor("#241430"))
        p.setBrush(grad); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, rc, rc)

        # внутренняя туманность — клип по сфере, иначе её не видно
        p.save()
        clip = QPainterPath(); clip.addEllipse(center, rc, rc); p.setClipPath(clip)
        for phase, am in ((self._cloud[0], 1.0), (self._cloud[1], 0.7), (self._cloud[2], 0.5)):
            ox = math.cos(phase) * rc * 0.25
            oy = math.sin(phase * 0.8) * rc * 0.25
            cloud = QRadialGradient(QPointF(cx + ox, cy + oy), rc * 0.9)
            ca = QColor("#ffd6f2"); ca.setAlpha(int(35 * am))
            cb = QColor("#b875ff"); cb.setAlpha(0)
            cloud.setColorAt(0.0, ca); cloud.setColorAt(1.0, cb)
            p.setBrush(cloud); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(center, rc, rc)
        p.restore()

        # эхо личности — еле уловимый силуэт внутри сферы
        ga = int(self._ghost * 18)
        if ga:
            p.save()
            clip2 = QPainterPath(); clip2.addEllipse(center, rc, rc); p.setClipPath(clip2)
            col = QColor("#ffe6f4"); col.setAlpha(ga)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
            p.drawEllipse(QPointF(cx, cy - rc * 0.08), rc * 0.18, rc * 0.22)
            p.drawEllipse(QPointF(cx - rc * 0.13, cy - rc * 0.30), rc * 0.07, rc * 0.18)
            p.drawEllipse(QPointF(cx + rc * 0.13, cy - rc * 0.30), rc * 0.07, rc * 0.18)
            p.restore()

        # блик
        hl = QRadialGradient(QPointF(cx - rc * 0.4, cy - rc * 0.45), rc * 0.7)
        hl.setColorAt(0.0, QColor(255, 255, 255, 200))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawEllipse(QPointF(cx - rc * 0.32, cy - rc * 0.36), rc * 0.42, rc * 0.30)



        # ── Эквалайзер — симметричная волна (4 строка 3 столбец) ──────────
        eq_bars = getattr(self, '_eq_bars', [0.05] * 8)
        has_signal = max(eq_bars) > 0.02 or self._state in ("speaking", "thinking", "listening")

        if has_signal:
            n_cols   = 20
            n_rows   = 9
            blk      = 3.0
            blk_gap  = 0.8
            col_gap  = 1.8
            col_step = blk + col_gap
            total_w  = n_cols * col_step - col_gap
            x0       = cx - total_w / 2
            base_y   = cy + R * 1.18

            col_targets = getattr(self, '_col_targets', [0.0] * 20)

            for i in range(n_cols):
                level = col_targets[i] if i < len(col_targets) else 0.0

                if self._state == "speaking":
                    level = max(level, 0.1 + 0.3*abs(math.sin(self._phase*3 + i*0.5)))

                active = max(1, int(level * n_rows))
                bx = x0 + i * col_step

                for row in range(active):
                    by    = base_y - row * (blk + blk_gap)
                    frac2 = row / max(active - 1, 1)
                    alpha = int(min(255, 100 + 140 * frac2))
                    p.setBrush(QColor(c.red(), c.green(), c.blue(), alpha))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawRect(QRectF(bx, by - blk, blk, blk))

        p.end()


class Overlay(QWidget):
    submit = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._font = _load_orbitron()
        self._settings = QSettings("Sakura", "SakuraOverlay")
        self._messages = []
        self._expanded = False
        self._game = False
        self._suspend = False
        self._drag_offset = None
        self._build_window()
        self._build_ui()
        self._restore_geometry()
        self.set_state("idle")

    # ── построение ──────────────────────────────────────────────────
    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(_MIN_W, _MIN_H)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 44, 18, 14)
        root.setSpacing(4)

        self.hud = SphereCore()
        root.addWidget(self.hud, 1)

        self.name = QLabel("SAKURA")
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setFont(QFont(self._font, 19, QFont.Weight.Bold))
        self.name.setStyleSheet("color: #eaf6ff; letter-spacing: 7px;")
        self._glow = QGraphicsDropShadowEffect(self.name)
        self._glow.setBlurRadius(22); self._glow.setOffset(0, 0)
        self.name.setGraphicsEffect(self._glow)
        root.addWidget(self.name)

        self.kana = QLabel("サクラ")
        self.kana.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kana.setFont(QFont("Segoe UI", 8))
        self.kana.setStyleSheet("color: #9fb6c9; letter-spacing: 4px;")
        root.addWidget(self.kana)

        self.vibe = QLabel("standby")
        self.vibe.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vibe.setFont(QFont(self._font, 9))
        root.addWidget(self.vibe)

        self.last_msg = QLabel("")
        self.last_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_msg.setWordWrap(True)
        self.last_msg.setTextFormat(Qt.TextFormat.RichText)
        self.last_msg.setStyleSheet("font-family: 'Segoe UI'; font-size: 10pt;")
        self._fade = QGraphicsOpacityEffect(self.last_msg)
        self._fade.setOpacity(0.0)
        self.last_msg.setGraphicsEffect(self._fade)
        self._fade_anim = QPropertyAnimation(self._fade, b"opacity", self)
        self._hide_timer = QTimer(self); self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        root.addWidget(self.last_msg)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFrameStyle(0)
        self.transcript.setVisible(False)
        self.transcript.setStyleSheet(
            "QTextEdit { background: transparent; color: #d7dae3; border: none;"
            " font-family: 'Segoe UI'; font-size: 10pt; }"
        )
        root.addWidget(self.transcript, 1)

        self.history_btn = QPushButton("история")
        self.history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #7c93a6; border: none;"
            " font-family: 'Orbitron','Segoe UI'; font-size: 8pt; letter-spacing: 2px; }"
            "QPushButton:hover { color: #cfe7f5; }"
        )
        self.history_btn.clicked.connect(self.toggle_history)
        root.addWidget(self.history_btn)

        self.input = QLineEdit()
        self.input.setPlaceholderText("сказать что-нибудь…")
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(120,200,255,0.05); color: #e8eaf0;"
            " border: 1px solid rgba(120,200,255,0.16); border-radius: 11px;"
            " padding: 9px 13px; font-family: 'Segoe UI'; font-size: 10pt; }"
            "QLineEdit:focus { border: 1px solid #6fe3ff; }"
        )
        self.input.returnPressed.connect(self._on_enter)
        root.addWidget(self.input)

        grip_row = QHBoxLayout()
        grip_row.addStretch()
        self.grip = QSizeGrip(self)
        grip_row.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(grip_row)

    # ── геометрия / якорь нижнего-правого угла ──────────────────────
    def _restore_geometry(self):
        geom = self._settings.value("geom")
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.resize(_DEF_W, _DEF_H)
            self.move(screen.right() - _DEF_W - config.OVERLAY_MARGIN,
                      screen.bottom() - _DEF_H - config.OVERLAY_MARGIN)
        self._anchor = self.geometry().bottomRight()

    def _save_geometry(self):
        if not self._game:
            self._settings.setValue("geom", self.saveGeometry())

    def _resize_anchored(self, w: int, h: int):
        anchor = QPoint(self._anchor)
        self._suspend = True
        self.resize(w, h)
        self.move(anchor.x() - w, anchor.y() - h)
        self._suspend = False
        self._anchor = anchor
        self._save_geometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._suspend and not self._game:
            self._anchor = self.geometry().bottomRight()
            self._save_geometry()

    def moveEvent(self, e):
        super().moveEvent(e)
        if not self._suspend and not self._game:
            self._anchor = self.geometry().bottomRight()
            self._save_geometry()

    # ── приём событий ядра ──────────────────────────────────────────
    def set_state(self, state: str):
        self.hud.set_state(state)
        meta = _STATE.get(state, _STATE["idle"])
        self.vibe.setText(meta["vibe"])
        self.vibe.setStyleSheet(f"color: {meta['color']}; letter-spacing: 3px;")
        self._glow.setColor(QColor(meta["color"]))

    def add_user_message(self, text: str):
        self._push("Я", text, "#9fc2e0")

    def add_sakura_message(self, text: str):
        self._push("Сакура", text, _STATE["speaking"]["color"])

    def set_mood(self, params: dict):
        """Применяет mood-параметры орба от VPS. Поддерживает game_theme."""
        try:
            self.hud.set_mood(params)
        except Exception:
            pass

        # №24: тема под игру
        if params.get("game_theme"):
            self._apply_game_theme(params["game_theme"])

    def _apply_game_theme(self, theme: dict):
        """Меняет цветовую схему панели под жанр игры."""
        try:
            orb_color   = theme.get("orb", "#9a7fb5")
            panel_color = theme.get("color", "#09090e")
            # Обновляем цвет свечения орба
            from PyQt6.QtGui import QColor
            self._glow.setColor(QColor(orb_color))
            # Обновляем фон панели
            r = int(panel_color[1:3], 16)
            g = int(panel_color[3:5], 16)
            b = int(panel_color[5:7], 16)
            self.findChild(__import__('PyQt6.QtWidgets', fromlist=['QWidget']).QWidget, 'panel')
            # Применяем через objectName
            for widget in self.findChildren(
                __import__('PyQt6.QtWidgets', fromlist=['QWidget']).QWidget
            ):
                if widget.objectName() == "panel":
                    widget.setStyleSheet(
                        f"#panel {{ background: rgba({r},{g},{b},210); "
                        f"border: 1px solid rgba(120,200,255,52); "
                        f"border-radius: 18px; }}"
                    )
                    break
        except Exception:
            pass

    def set_connected(self, online: bool):
        self.name.setStyleSheet(
            "color: #eaf6ff; letter-spacing: 7px;" if online
            else "color: #5d6b78; letter-spacing: 7px;"
        )

    def _push(self, who: str, text: str, color: str):
        self._messages.append(
            f'<p style="margin:4px 0;"><b style="color:{color};">{who}:</b> '
            f'<span style="color:#d7dae3;">{escape(text)}</span></p>'
        )
        del self._messages[:-config.TRANSCRIPT_MAX]
        if self._expanded:
            self.transcript.setHtml("".join(self._messages))
            bar = self.transcript.verticalScrollBar()
            bar.setValue(bar.maximum())
        else:
            self._flash(text, color)

    # ── всплывающая реплика (тает) ──────────────────────────────────
    def _flash(self, text: str, color: str):
        self.last_msg.setText(f'<span style="color:{color};">{escape(text)}</span>')
        self._fade_anim.stop()
        self._fade.setOpacity(1.0)
        self._hide_timer.start(7000)

    def _fade_out(self):
        self._fade_anim.stop()
        self._fade_anim.setDuration(1200)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_anim.start()

    # ── история ─────────────────────────────────────────────────────
    def toggle_history(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._pre_h = self.height()
            self._fade_anim.stop(); self._fade.setOpacity(0.0)
            self.last_msg.setVisible(False)
            self.transcript.setVisible(True)
            self.transcript.setHtml("".join(self._messages))
            self.history_btn.setText("свернуть историю")
            self._resize_anchored(self.width(), self.height() + 190)
        else:
            self.transcript.setVisible(False)
            self.last_msg.setVisible(True)
            self.history_btn.setText("история")
            self._resize_anchored(self.width(), getattr(self, "_pre_h", self.height() - 190))

    def _on_enter(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.submit.emit(text)

    # ── фон-панель + ветвь сакуры ───────────────────────────────────
    def paintEvent(self, _):
        # Игровой режим: ни панели, ни рамки — только ядро на прозрачном фоне.
        if self._game:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(_PANEL_BG)
        p.setPen(QPen(_PANEL_BORDER, 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 18, 18)
        self._paint_branch(p)
        p.end()

    def _paint_branch(self, p: QPainter):
        w = self.width()
        path = QPainterPath()
        path.moveTo(16, 40)
        path.cubicTo(w * 0.35, 54, w * 0.62, 34, w - 16, 48)
        twig = QPainterPath()
        twig.moveTo(w * 0.62, 38)
        twig.cubicTo(w * 0.66, 24, w * 0.72, 18, w * 0.78, 14)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_BRANCH, 2.2, cap=Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(_BRANCH, 1.4, cap=Qt.PenCapStyle.RoundCap))
        p.drawPath(twig)
        for x, y, r in ((w * 0.18, 44, 5), (w * 0.45, 42, 5), (w * 0.78, 14, 4)):
            self._paint_blossom(p, x, y, r)

    def _paint_blossom(self, p: QPainter, x: float, y: float, r: float):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_PETAL)
        for k in range(5):
            a = 2 * math.pi * k / 5 - math.pi / 2
            p.drawEllipse(QPointF(x + r * math.cos(a), y + r * math.sin(a)), r * 0.7, r * 0.7)
        p.setBrush(_PETAL_LIGHT)
        p.drawEllipse(QPointF(x, y), r * 0.5, r * 0.5)

    # ── перетаскивание ──────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _):
        self._drag_offset = None

    # ── игровой режим: только ядро + клик-сквозь ────────────────────
    def animate_arrival(self):
        self.setWindowOpacity(0.0)
        self.show()
        def _step():
            op = min(1.0, self.windowOpacity() + 0.08)
            self.setWindowOpacity(op)
            if op < 1.0:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(30, _step)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, _step)

    def animate_departure(self):
        def _step():
            op = max(0.3, self.windowOpacity() - 0.04)
            self.setWindowOpacity(op)
            if op > 0.3:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(50, _step)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, _step)

    def show_notification(self, text: str, duration_ms: int = 4000):
        """Мини-нотификация — маленькое сообщение из угла орба."""
        from PyQt6.QtWidgets import QLabel
        from PyQt6.QtCore import QTimer
        from PyQt6.QtGui import QFont
        notif = QLabel(text, self)
        notif.setWordWrap(True)
        notif.setMaximumWidth(260)
        notif.setFont(QFont("Segoe UI", 9))
        notif.setStyleSheet(
            "background: rgba(20,10,30,220); color: #d4b8e0;"
            "border: 1px solid rgba(180,120,220,80);"
            "border-radius: 8px; padding: 8px 12px;"
        )
        notif.adjustSize()
        notif.move(self.width() - notif.width() - 10,
                   self.height() - notif.height() - 10)
        notif.show()
        QTimer.singleShot(duration_ms, notif.deleteLater)

    def set_game_mode(self, enabled: bool):
        self._game = enabled
        self.hud.set_game_mode_flag(enabled)
        widgets = (self.name, self.kana, self.vibe, self.last_msg,
                   self.transcript, self.history_btn, self.input, self.grip)
        if enabled:
            self._normal_geom = self.saveGeometry()
            for wdg in widgets:
                wdg.setVisible(False)
            self.layout().setContentsMargins(14, 14, 14, 14)
            self.setMinimumSize(_GAME_SIZE, _GAME_SIZE)
            self._resize_anchored(_GAME_SIZE, _GAME_SIZE)
        else:
            for wdg in widgets:
                wdg.setVisible(wdg is not self.transcript or self._expanded)
            self.layout().setContentsMargins(18, 44, 18, 14)
            self.setMinimumSize(_MIN_W, _MIN_H)
            if getattr(self, "_normal_geom", None) is not None:
                self.restoreGeometry(self._normal_geom)
            self._anchor = self.geometry().bottomRight()
        self._set_clickthrough(enabled)

    def _set_clickthrough(self, enabled: bool):
        hwnd = int(self.winId())
        GWL_EXSTYLE, WS_LAYERED, WS_TRANSPARENT = -20, 0x00080000, 0x00000020
        ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            ex |= WS_LAYERED | WS_TRANSPARENT
        else:
            ex &= ~WS_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)