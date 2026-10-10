"""desktop.core.media.router — один диспетчер для встроенных и внешних плееров.

Правило цели: встроенный плеер активен (играет или на паузе меньше
BUILTIN_IDLE_S = 10 минут) → действие исполняет он; иначе — внешний путь,
как в старом агенте (SMTC, приложение Яндекс.Музыки, расширение браузера).
Таблица действий — desktop/docs/media.md.

plan() — чистая функция «действие → маршрут» (тестируется на всех 30 действиях);
исполнение встроенного маршрута — событие media_command в локальный API
(плееры живут в окне интерфейса).
"""
import time
from dataclasses import dataclass, field

BUILTIN_IDLE_S = 600.0
SEEK_STEP_S = 10
SPEED_STEP = 0.25

MUSIC_ACTIONS = ("dislike", "history", "like", "liked_tracks", "mute", "next", "now_playing", "play_pause",
                 "playlists", "podcasts", "prev", "repeat", "seek_back", "seek_forward", "shuffle",
                 "volume_down", "volume_up", "wave")
YOUTUBE_ACTIONS = ("forward", "fullscreen", "like", "mini", "next", "pause", "rewind", "speed_down",
                   "speed_up", "sub_toggle", "theater", "trending")

# Встроенная реализация: действие → (команда плеера, аргумент по умолчанию).
# None — у встроенного плеера нет аналога, всегда внешний путь.
MUSIC_BUILTIN: dict[str, tuple[str, object] | None] = {
    "play_pause": ("toggle", None), "next": ("next", None), "prev": ("prev", None),
    "seek_back": ("seekBy", -SEEK_STEP_S), "seek_forward": ("seekBy", SEEK_STEP_S),
    "shuffle": ("shuffle", None), "repeat": ("repeat", None), "mute": ("mute", None),
    "volume_up": ("volumeBy", None), "volume_down": ("volumeBy", None),
    "now_playing": ("now_playing", None), "like": ("like", None), "dislike": ("dislike", None),
    "liked_tracks": ("play_liked", None), "playlists": ("list_playlists", None),
    "history": ("list_history", None), "wave": ("wave", None),
    "podcasts": None,
}
YOUTUBE_BUILTIN: dict[str, tuple[str, object] | None] = {
    "pause": ("toggle", None), "forward": ("seekBy", SEEK_STEP_S), "rewind": ("seekBy", -SEEK_STEP_S),
    "next": ("next", None), "fullscreen": ("fullscreen", None), "mini": ("mini", None),
    "speed_up": ("rateBy", SPEED_STEP), "speed_down": ("rateBy", -SPEED_STEP),
    "sub_toggle": ("subtitles", None), "theater": ("theater", None),
    "like": None,      # лайк требует аккаунта YouTube — только во вкладке браузера
    "trending": None,  # «Популярное» открывается в браузере
}


@dataclass
class PlayerState:
    status: str = "stopped"     # playing | paused | stopped
    updated: float = 0.0
    source: str = ""            # local | yandex | youtube | url
    title: str = ""
    artist: str = ""
    album: str = ""
    position: float = 0.0
    duration: float = 0.0
    extra: dict = field(default_factory=dict)

    def active(self, now: float) -> bool:
        if self.status == "playing":
            return True
        return self.status == "paused" and now - self.updated < BUILTIN_IDLE_S


@dataclass
class Route:
    target: str                 # builtin | external
    player: str | None = None   # music | video
    cmd: str | None = None
    arg: object = None


def canonical(action: str) -> tuple[str, str] | None:
    """music.next / music:next / music_next / youtube.pause / youtube_pause → (домен, глагол)."""
    for dom in ("music", "youtube"):
        for sep in (".", ":", "_"):
            pre = dom + sep
            if action.startswith(pre):
                verb = action[len(pre):].split(":", 1)[0]
                if dom == "music" and verb in MUSIC_ACTIONS:
                    return dom, verb
                if dom == "youtube" and verb in YOUTUBE_ACTIONS:
                    return dom, verb
    return None


class MediaRouter:
    def __init__(self, volume_step: int = 10, clock=time.monotonic):
        self.volume_step = volume_step
        self.clock = clock
        self.players = {"music": PlayerState(), "video": PlayerState()}

    def update(self, player: str, **state):
        if player not in self.players:
            return
        st = self.players[player]
        for k, v in state.items():
            if hasattr(st, k):
                setattr(st, k, v)
        st.updated = self.clock()

    def active(self, player: str) -> bool:
        return self.players[player].active(self.clock())

    def plan(self, action: str, arg: str = "") -> Route | None:
        """None — действие не медиа. Иначе маршрут: встроенный плеер или внешний путь."""
        c = canonical(action)
        if c is None:
            return None
        dom, verb = c
        player = "music" if dom == "music" else "video"
        table = MUSIC_BUILTIN if dom == "music" else YOUTUBE_BUILTIN
        impl = table.get(verb)
        if impl is None or not self.active(player):
            return Route("external")
        cmd, default = impl
        if cmd == "volumeBy":
            n = int(arg) if str(arg).isdigit() and 1 <= int(arg) <= 100 else self.volume_step
            value: object = n if verb == "volume_up" else -n
        else:
            value = default
        return Route("builtin", player, cmd, value)

    def now_playing_text(self, player: str = "music") -> str:
        st = self.players[player]
        if not st.title:
            return "Ничего не играет"
        who = f"{st.artist} — " if st.artist else ""
        suffix = "" if st.status == "playing" else " (пауза)"
        return f"{who}{st.title}{suffix}"

    def current_track(self) -> dict | None:
        """Поле current_track для ping/register — как у music_listener/SMTC (сервер не меняется)."""
        st = self.players["music"]
        if not st.title or not st.active(self.clock()):
            return None

        def mmss(s: float) -> str:
            s = max(0, int(s))
            return f"{s // 60}:{s % 60:02d}"
        status = {"playing": "играет", "paused": "пауза"}.get(st.status, "остановлен")
        return {"title": st.title, "artist": st.artist, "album": st.album, "status": status,
                "position": mmss(st.position), "duration": mmss(st.duration),
                "progress": int(st.position / st.duration * 100) if st.duration else 0}

    def active_window_hint(self) -> str | None:
        """Заголовок для active_window, пока играет встроенное видео (контекст window:youtube)."""
        st = self.players["video"]
        if st.status != "playing":
            return None
        if st.source == "youtube":
            return f"{st.title or 'Видео'} - YouTube — Sakura Player"
        return f"{st.title or 'Видео'} — Sakura Player"
