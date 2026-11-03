"""
core/local_mood.py — Локальное настроение агента (Слой 1: Тело дышит).

Орб не ждёт mood_update с сервера — он сам обрабатывает настроение
из локальных источников: музыка, время суток, активность, температура.

Между обновлениями сервера (раз в 30с) орб плавно интерполирует
к целевому цвету. Это делает его ЖИВЫМ — он дышит, а не接受ает.
"""

import logging
import math
import time
from datetime import datetime

log = logging.getLogger("sakura.local_mood")


# ── Палитра по жанрам музыки ─────────────────────────────────────────

_GENRE_COLORS = {
    # (hue_shift, saturation_mod, brightness_mod)
    "rock":      (0.0,  0.1,  -0.05),   # чуть насыщеннее
    "metal":     (0.0,  0.15, -0.1),    # тёмнее, насыщеннее
    "pop":       (0.05, 0.05, 0.05),    # ярче
    "electronic":(0.1,  0.1,  0.0),     # холоднее
    "jazz":      (-0.05, 0.0, -0.03),   # теплее, спокойнее
    "classical": (-0.03, -0.05, 0.0),   # мягче
    "hip-hop":   (0.02, 0.08, 0.0),     # чуть насыщеннее
    "indie":     (-0.02, 0.0, 0.02),    # тёплый, лёгкий
    "ambient":   (0.08, -0.1, -0.05),   # холодный, тихий
    "lofi":      (-0.04, -0.05, 0.0),   # тёплый, приглушённый
    "sad":       (-0.05, -0.1, -0.08),  # холодный, тёмный
    "happy":     (0.05, 0.1,  0.08),    # тёплый, яркий
    "energetic": (0.03, 0.12, 0.05),    # яркий, насыщенный
    "calm":      (0.0,  -0.08, -0.02),  # приглушённый
}


# ── Время суток → базовое настроение ─────────────────────────────────

def _time_base() -> tuple[float, float]:
    """Базовый mood по времени суток: (valence_shift, arousal_shift)."""
    hour = datetime.now().hour

    if 6 <= hour < 9:
        return (0.05, 0.1)     # утро — бодрое
    if 9 <= hour < 12:
        return (0.0, 0.05)     # утро — рабочее
    if 12 <= hour < 14:
        return (0.0, 0.0)      # обед — нейтрально
    if 14 <= hour < 17:
        return (0.0, 0.0)      # день — нейтрально
    if 17 <= hour < 20:
        return (0.0, 0.0)      # вечер — нейтрально
    if 20 <= hour < 23:
        return (0.0, -0.03)    # поздний вечер — чуть тише
    return (-0.05, -0.05)      # ночь — тихое


# ── Жанр музыки → настроение ─────────────────────────────────────────

def _detect_genre(track: dict) -> str:
    """Определяет жанр по названию/исполнителю (простая эвристика)."""
    if not track:
        return "calm"

    title = (track.get("title", "") + " " + track.get("artist", "")).lower()

    # Простые эвристики по ключевым словам
    if any(w in title for w in ("metal", "slipknot", "metallica", "iron maiden", "system")):
        return "metal"
    if any(w in title for w in ("rock", "nirvana", "linkin park", "green day")):
        return "rock"
    if any(w in title for w in ("jazz", "miles davis", "coltrane", "bossa")):
        return "jazz"
    if any(w in title for w in ("classical", "mozart", "chopin", "bach", "symphony")):
        return "classical"
    if any(w in title for w in ("lofi", "lo-fi", "chill", "study", "beats")):
        return "lofi"
    if any(w in title for w in ("edm", "techno", "house", "trance", "dubstep")):
        return "electronic"
    if any(w in title for w in ("sad", "heartbreak", "lonely", "tears")):
        return "sad"
    if any(w in title for w in ("happy", "party", "dance", "fun")):
        return "happy"
    if any(w in title for w in ("calm", "peace", "relax", "sleep")):
        return "calm"
    if any(w in title for w in ("energy", "power", "workout", "pump")):
        return "energetic"

    return "calm"  # по умолчанию


# ── Основной класс ───────────────────────────────────────────────────

class LocalMood:
    """
    Локальное настроение агента.
    Считает целевой mood из музыки, времени, активности, температуры.
    Плавно интерполирует к цели.
    """

    def __init__(self):
        self._target_valence = 0.0
        self._target_arousal = 0.3
        self._current_valence = 0.0
        self._current_arousal = 0.3
        self._last_update = time.monotonic()
        self._last_track = None
        self._genre = "calm"

    def update(self, track: dict = None, activity: float = 0.0,
               cpu_temp: float = None, server_mood: dict = None):
        """
        Обновляет целевое настроение.
        Приоритет: серверное настроение (90%) > локальные факторы (10%).
        """
        now = time.monotonic()
        dt = now - self._last_update
        self._last_update = now

        if server_mood:
            # Серверное настроение — основной источник (90%)
            sv = server_mood.get("valence", 0.0)
            sa = server_mood.get("arousal", 0.3)
            self._target_valence = sv
            self._target_arousal = sa
        else:
            # Нет сервера — локальные факторы
            tv, ta = _time_base()
            if track and track.get("title"):
                genre = _detect_genre(track)
                shift = _GENRE_COLORS.get(genre, (0, 0, 0))
                tv += shift[0]
                ta += shift[1]
            ta += activity * 0.1
            if cpu_temp and cpu_temp > 80:
                ta += 0.08
            self._target_valence = max(-1.0, min(1.0, tv))
            self._target_arousal = max(0.0, min(1.0, ta))

        # Плавная интерполяция (alpha = 0.15 → плавно за ~7 секунд)
        alpha = min(1.0, dt * 0.15)
        self._current_valence += (self._target_valence - self._current_valence) * alpha
        self._current_arousal += (self._target_arousal - self._current_arousal) * alpha

    def get_current(self) -> dict:
        """Текущее настроение (с интерполяцией)."""
        return {
            "valence": round(self._current_valence, 3),
            "arousal": round(self._current_arousal, 3),
        }

    def get_color(self) -> str:
        """Текущий цвет орба в hex — из текущего mood."""
        v = self._current_valence
        a = self._current_arousal

        # Конвертация valence/arousal → RGB (упрощённо)
        # Положительный valence → тёплые тона (розовый/лиловый)
        # Отрицательный → холодные (синий/серый)
        # Высокий arousal → ярче, низкий → тусклее

        base_r, base_g, base_b = 154, 127, 181  # базовый лиловый

        if v >= 0:
            r = int(base_r + v * 80)
            g = int(base_g + v * 30)
            b = int(base_b - v * 60)
        else:
            fac = -v
            r = int(base_r - fac * 90)
            g = int(base_g + fac * 50)
            b = int(base_b + fac * 60)

        # Arousal влияет на яркость
        brightness = 0.7 + a * 0.3
        r = int(max(0, min(255, r * brightness)))
        g = int(max(0, min(255, g * brightness)))
        b = int(max(0, min(255, b * brightness)))

        return f"#{r:02x}{g:02x}{b:02x}"

    def get_orb_params(self) -> dict:
        """Параметры для орба — совместимые с mood_vector.get_orb_params()."""
        v = self._current_valence
        a = self._current_arousal

        pulse_amp = 0.03 + a * 0.11
        petal_speed = 0.5 + a * 1.0 + max(0, v) * 0.3
        petal_count = max(3, min(14, int(5 + max(0, v) * 6 + a * 3)))

        if a > 0.75 and v > 0.4:
            inner_weather = "clear"
        elif a < 0.25 and v > 0.1:
            inner_weather = "shimmer"
        elif v < -0.5:
            inner_weather = "fog"
        else:
            inner_weather = "clear"

        return {
            "color":         self.get_color(),
            "pulse_amp":     round(pulse_amp, 3),
            "petal_speed":   round(petal_speed, 2),
            "petal_count":   petal_count,
            "inner_weather": inner_weather,
            "valence":       round(v, 2),
            "arousal":       round(a, 2),
            "source":        "local",  # маркер что это локальный mood
        }
