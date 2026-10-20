"""Голос: перебивание «стоп» во время озвучки, чувствительность слова «Сакура» по шуму, замены распознанного.

Перебивание: пока Сакура говорит, микрофон для обычного слуха заглушён (подавление эха по таймингу:
озвучка + 700 мс). Отдельный распознаватель Vosk с узкой грамматикой слушает только стоп-слова —
собственная речь Сакуры почти никогда не даёт точного совпадения с ними. Вычитание системного звука
(AEC) не делается: нужна нативная обработка (DECISIONS №53).
"""
import json
import math
import re

try:
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

STOP_GRAMMAR = ["стоп", "сакура стоп", "хватит", "сакура хватит", "замолчи", "[unk]"]
STOP_WORDS = ("стоп", "хватит", "замолчи")

# Чувствительность слова «Сакура»: high — вхождение в промежуточном результате (быстро, больше ложных),
# normal — целое слово в промежуточном, low — только в итоговом результате фразы (надёжно в шуме).
MODES = ("low", "normal", "high")
NOISE_HIGH_DB = -35.0   # громкий фон (музыка, ТВ) → low
NOISE_LOW_DB = -55.0    # тихо → high


# Уровень для ядра-графики: 0 — тише LEVEL_FLOOR_DB, 1 — от LEVEL_FLOOR_DB + LEVEL_SPAN_DB.
LEVEL_FLOOR_DB = -50.0
LEVEL_SPAN_DB = 40.0


def pcm_level(pcm16: bytes) -> float:
    """Громкость блока PCM 16 бит 0..1 (numpy, без журнала и I/O — годится для колбэка звука)."""
    if _np is None:
        db = rms_db(pcm16)
    else:
        a = _np.frombuffer(pcm16[: len(pcm16) // 2 * 2], dtype="<i2")
        if not a.size:
            return 0.0
        ms = float(_np.mean(_np.square(a, dtype=_np.float32)))
        db = 10 * math.log10(ms) - 90.309 if ms > 0 else -120.0  # 90.309 = 20·lg 32768
    return min(1.0, max(0.0, (db - LEVEL_FLOOR_DB) / LEVEL_SPAN_DB))


def rms_db(pcm16: bytes) -> float:
    """Уровень блока PCM 16 бит в dBFS."""
    n = len(pcm16) // 2
    if not n:
        return -120.0
    import array
    a = array.array("h", pcm16[: n * 2])
    ms = sum(x * x for x in a) / n
    return 20 * math.log10(math.sqrt(ms) / 32768) if ms > 0 else -120.0


class NoiseFloor:
    """Скользящая оценка фона: несимметричное экспоненциальное среднее."""

    def __init__(self, alpha: float = 0.02, start: float = -50.0):
        self.alpha = alpha
        self.db = start

    def feed(self, db: float) -> float:
        # Вниз — быстро, вверх — вчетверо медленнее: устойчивый фон (ТВ, музыка) поднимает оценку за
        # секунды, короткая речь почти не влияет. Раньше блоки громче фона+10 дБ отбрасывались целиком —
        # и при резко выросшем фоне оценка не росла вовсе.
        a = self.alpha if db < self.db else self.alpha / 4
        self.db += a * (db - self.db)
        return self.db


def choose_mode(setting: str | None, noise_db: float) -> str:
    """Ручная настройка (low/normal/high) или авто по уровню шума."""
    if setting in MODES:
        return setting
    if noise_db >= NOISE_HIGH_DB:
        return "low"
    if noise_db <= NOISE_LOW_DB:
        return "high"
    return "normal"


def wake_hit(words: tuple[str, ...], mode: str, partial: str = "", final: str = "") -> bool:
    if mode == "low":
        return any(re.search(rf"\b{re.escape(w)}\b", final) for w in words)
    if mode == "normal":
        return any(re.search(rf"\b{re.escape(w)}\b", partial or final) for w in words)
    return any(w in (partial or final) for w in words)


def is_stop(result_json: str) -> bool:
    """Итог распознавателя с узкой грамматикой — стоп-слово (не [unk])."""
    try:
        text = json.loads(result_json).get("text", "") or json.loads(result_json).get("partial", "")
    except ValueError:
        return False
    return any(w in text.split() for w in STOP_WORDS)


def apply_replacements(text: str, pairs) -> str:
    """Таблица замен распознанного («вал хейм» → «Valheim»): целые слова, без учёта регистра."""
    out = text
    for item in pairs or ():
        try:
            src, dst = item[0], item[1]
        except (TypeError, IndexError):
            continue
        src = str(src).strip()
        if not src:
            continue
        out = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", str(dst), out, flags=re.IGNORECASE)
    return out
