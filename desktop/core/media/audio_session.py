"""desktop.core.media.audio_session — приоритеты звука и приглушение встроенных плееров.

Приоритеты: речь (speaking) > слушание (listening) > видео > музыка.
- Пока Сакура слушает или говорит — видео и музыка приглушаются до PLAYER_DUCK_PCT
  (по умолчанию 30 %) за 150 мс; после — возврат к 100 % за 600 мс.
- Играет видео — музыка приглушается (видео важнее).
- «стоп» ставит на паузу все встроенные плееры.
Системные звуки и внешние приложения не трогаем: менеджер выдаёт только
множители громкости для встроенных <audio>/<video> (событие audio_duck).
"""
from collections.abc import Callable

ATTACK_MS = 150
RELEASE_MS = 600
VOICE_DUCK_STATES = frozenset({"listening", "speaking"})
PLAYERS = ("video", "music")


class AudioSession:
    def __init__(self, duck_pct: int = 30, emit: Callable[[dict], None] | None = None):
        self.duck = max(0, min(100, int(duck_pct))) / 100.0
        self._emit = emit or (lambda ev: None)
        self.voice = "idle"
        self.playing = {"video": False, "music": False}
        self._gains = {"video": 1.0, "music": 1.0}

    @property
    def gains(self) -> dict:
        return dict(self._gains)

    def targets(self) -> dict:
        voice_active = self.voice in VOICE_DUCK_STATES
        video = self.duck if voice_active else 1.0
        music = self.duck if (voice_active or self.playing["video"]) else 1.0
        return {"video": video, "music": music}

    def _update(self):
        new = self.targets()
        if new == self._gains:
            return
        lowering = any(new[p] < self._gains[p] for p in PLAYERS)
        self._gains = new
        self._emit({"type": "audio_duck", "gains": dict(new), "ramp_ms": ATTACK_MS if lowering else RELEASE_MS})

    def set_voice_state(self, state: str):
        """Состояние ядра: idle | listening | thinking | speaking."""
        self.voice = state
        self._update()

    def set_playing(self, player: str, playing: bool):
        if player in self.playing:
            self.playing[player] = bool(playing)
            self._update()

    def set_duck_pct(self, pct: int):
        self.duck = max(0, min(100, int(pct))) / 100.0
        self._update()

    def stop_all(self):
        """Голосовое «стоп»: пауза всех встроенных плееров."""
        self._emit({"type": "media_command", "player": "all", "cmd": "pause"})
