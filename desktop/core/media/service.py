"""desktop.core.media.service — сборка медиа в ядре и команды локального API.

MediaService владеет медиатекой, http-сервером, диспетчером, менеджером звука и
провайдерами. Встроенные плееры живут в окне интерфейса: ядро шлёт им событие
media_command, они сообщают своё состояние командой media_state.
"""
import asyncio
import logging
import os
import sys

from desktop.core import config

from .audio_session import AudioSession
from .library import MediaLibrary
from .media_server import MediaServer
from .providers import ProviderError, remote_smtc
from .providers import video as video_provider
from .providers.yandex import UNOFFICIAL_NOTE, YandexProvider
from .router import MediaRouter

log = logging.getLogger("sakura.media")

MEDIA_SETTINGS = {
    "music_folders": list, "video_folders": list, "crossfade_s": float, "player_duck_pct": int,
    "youtube_mode": str, "youtube_proxy": str, "music_yandex": bool,
}


class MediaService:
    def __init__(self, emit, settings, data_dir: str | None = None, yandex: YandexProvider | None = None):
        self._emit = emit
        self.settings = settings
        data_dir = data_dir or config.DATA_DIR
        self.library = MediaLibrary(os.path.join(data_dir, "media.db"))
        self.server = MediaServer(self.library)
        self.router = MediaRouter(volume_step=config.VOLUME_STEP)
        self.audio = AudioSession(duck_pct=self.get("player_duck_pct"), emit=emit)
        self.yandex = yandex or YandexProvider(config.YANDEX_MUSIC_TOKEN, self.get("music_yandex"))
        self._scan_task: asyncio.Task | None = None
        self._apply_folders()

    # ── настройки ──────────────────────────────────────────────────
    def get(self, key: str):
        defaults = {"music_folders": config.MUSIC_FOLDERS, "video_folders": config.VIDEO_FOLDERS,
                    "crossfade_s": config.CROSSFADE_S, "player_duck_pct": config.PLAYER_DUCK_PCT,
                    "youtube_mode": config.YOUTUBE_MODE, "youtube_proxy": config.YOUTUBE_PROXY,
                    "music_yandex": config.MUSIC_YANDEX}
        v = self.settings.items().get(key)
        return defaults[key] if v is None else v

    def snapshot(self) -> dict:
        snap = {k: self.get(k) for k in MEDIA_SETTINGS}
        snap["yandex_note"] = UNOFFICIAL_NOTE
        snap["media_origin"] = self.server.origin if self.server.port else None
        return snap

    def set(self, key: str, value):
        if key not in MEDIA_SETTINGS:
            raise ValueError(key)
        typ = MEDIA_SETTINGS[key]
        if typ is list:
            value = [str(p) for p in (value or []) if str(p).strip()]
        elif typ is bool:
            value = bool(value)
        else:
            value = typ(value)
        self.settings.set(key, value)
        if key in ("music_folders", "video_folders"):
            self._apply_folders()
        elif key == "player_duck_pct":
            self.audio.set_duck_pct(value)
        elif key == "music_yandex":
            self.yandex = YandexProvider(config.YANDEX_MUSIC_TOKEN, value)
        return self.snapshot()

    def _apply_folders(self):
        self.library.set_folders(self.get("music_folders"), self.get("video_folders"))

    # ── жизненный цикл ─────────────────────────────────────────────
    def start(self, port: int = 0):
        self.server.start(port)

    def scan(self):
        """Фоновое сканирование с прогрессом (событие media_scan)."""
        if self._scan_task and not self._scan_task.done():
            return False
        loop = asyncio.get_running_loop()

        def progress(p):
            loop.call_soon_threadsafe(self._emit, {"type": "media_scan", "state": "running", **p})

        async def run():
            try:
                stats = await asyncio.to_thread(self.library.scan, progress)
                self._emit({"type": "media_scan", "state": "done", **stats})
            except Exception as e:
                log.exception("[media] сканирование")
                self._emit({"type": "media_scan", "state": "error", "error": str(e)})
        self._scan_task = asyncio.ensure_future(run())
        return True

    # ── связь с агентом ────────────────────────────────────────────
    def on_voice_state(self, state: str):
        self.audio.set_voice_state(state)

    def current_track(self):
        return self.router.current_track()

    def active_window_hint(self):
        return self.router.active_window_hint()

    async def handle_command(self, action: str, arg: str = ""):
        """None — не медиа или внешний путь (агент исполняет как раньше). Иначе (ok, detail)."""
        route = self.router.plan(action, arg)
        if route is None or route.target == "external":
            return None
        if route.cmd == "now_playing":
            return True, self.router.now_playing_text(route.player)
        if route.cmd == "list_playlists":
            names = [p["name"] for p in self.library.playlists()]
            return True, ("Плейлисты: " + ", ".join(names)) if names else "Плейлистов пока нет"
        if route.cmd == "list_history":
            hist = self.library.history(5)
            return True, ("Недавно: " + "; ".join(f"{h['artist']} — {h['title']}" for h in hist)) \
                if hist else "История пуста"
        self._emit({"type": "media_command", "player": route.player, "cmd": route.cmd, "arg": route.arg})
        return True, f"{route.player}: {route.cmd}"

    # ── команды интерфейса ─────────────────────────────────────────
    def register(self, api_command):
        for name in ("state", "library", "scan", "urls", "playlist", "history", "position", "open_url",
                     "youtube_from_browser", "youtube_to_browser", "youtube_check", "yandex", "level",
                     "settings", "external", "clear_covers"):
            api_command(f"media_{name}", getattr(self, f"cmd_{name}"))

    async def cmd_state(self, msg):
        player = msg.get("player")
        if player not in ("music", "video"):
            raise ValueError("player")
        fields = {k: msg[k] for k in ("status", "source", "title", "artist", "album", "position", "duration")
                  if k in msg}
        self.router.update(player, **fields)
        if "status" in fields:
            self.audio.set_playing(player, fields["status"] == "playing")
        if fields.get("status") == "playing" and msg.get("track_id") and msg.get("new_track"):
            try:
                self.library.add_history(int(msg["track_id"]))
            except (ValueError, TypeError):
                pass
        self._emit({"type": "now_playing", "player": player, **fields})

    async def cmd_library(self, msg):
        view = msg.get("view", "tracks")
        kind = "video" if msg.get("kind") == "video" else "audio"
        if view == "tracks":
            if msg.get("q"):
                items = self.library.search(str(msg["q"]), kind=kind, limit=int(msg.get("limit") or 500))
            else:
                items = self.library.tracks(kind, int(msg.get("offset") or 0), int(msg.get("limit") or 500),
                                            album=msg.get("album"), artist=msg.get("artist"))
            return {"items": items, "total": self.library.count(kind)}
        if view == "albums":
            return {"items": self.library.albums()}
        if view == "artists":
            return {"items": self.library.artists()}
        if view == "playlists":
            return {"items": self.library.playlists()}
        raise ValueError(f"view {view}")

    async def cmd_scan(self, msg):
        return {"started": self.scan()}

    async def cmd_urls(self, msg):
        t = self.library.get(int(msg["track_id"]))
        if not t:
            raise ValueError("нет такого трека")
        subs = [{"index": i, "label": os.path.basename(p), "src": self.server.url(f"/subtitle/{t['id']}/{i}")}
                for i, p in enumerate(self.library.subtitles(t["id"]))] if t["kind"] == "video" else []
        return {"src": self.server.url(f"/media/{t['id']}"),
                "cover": self.server.url(f"/cover/{t['cover_hash']}") if t.get("cover_hash") else None,
                "subtitles": subs, "position": self.library.get_position(t["id"]) if t["kind"] == "video" else 0,
                "siblings": [s["id"] for s in self.library.folder_siblings(t["id"])] if t["kind"] == "video" else []}

    async def cmd_playlist(self, msg):
        op = msg.get("op")
        if op == "create":
            return {"id": self.library.playlist_create(str(msg["name"]), msg.get("track_ids") or [])}
        if op == "set":
            self.library.playlist_set(int(msg["id"]), msg.get("track_ids") or [])
            return None
        if op == "delete":
            self.library.playlist_delete(int(msg["id"]))
            return None
        if op == "tracks":
            return {"items": self.library.playlist_tracks(int(msg["id"]))}
        if op == "like":
            pid = next((p["id"] for p in self.library.playlists() if p["name"] == "Любимое"), None)
            if pid is None:
                pid = self.library.playlist_create("Любимое")
            ids = [t["id"] for t in self.library.playlist_tracks(pid)]
            if int(msg["track_id"]) not in ids:
                self.library.playlist_set(pid, [*ids, int(msg["track_id"])])
            return {"id": pid}
        raise ValueError(f"op {op}")

    async def cmd_history(self, msg):
        return {"items": self.library.history(int(msg.get("limit") or 50))}

    async def cmd_position(self, msg):
        self.library.set_position(int(msg["track_id"]), float(msg["position"]))

    async def cmd_open_url(self, msg):
        info = video_provider.classify_url(str(msg.get("url", "")))
        if info["kind"] == "youtube":
            info["player_url"] = self.server.player_url(info["video_id"], info["start"])
        return info

    async def cmd_youtube_from_browser(self, msg):
        ext = sys.modules.get("desktop.core.extension_server")
        if not ext or not ext.is_connected():
            raise ValueError("расширение браузера не подключено")
        info = await video_provider.take_from_browser(ext.send_command)
        info["player_url"] = self.server.player_url(info["video_id"], info["start"])
        return info

    async def cmd_youtube_to_browser(self, msg):
        url = video_provider.browser_url(str(msg["video_id"]), float(msg.get("time") or 0))
        import webbrowser
        webbrowser.open(url)
        return {"url": url}

    async def cmd_youtube_check(self, msg):
        return await asyncio.to_thread(video_provider.check_youtube, self.get("youtube_proxy"))

    async def cmd_yandex(self, msg):
        op = msg.get("op")
        y = self.yandex
        try:
            if op == "search":
                return {"items": await asyncio.to_thread(y.search, str(msg.get("q", "")))}
            if op == "liked":
                return {"items": await asyncio.to_thread(y.liked)}
            if op == "playlists":
                return {"items": await asyncio.to_thread(y.playlists)}
            if op == "playlist":
                return {"items": await asyncio.to_thread(y.playlist_tracks, int(str(msg["id"]).removeprefix("ym:")))}
            if op == "wave":
                return {"items": await asyncio.to_thread(y.wave)}
            if op == "stream":
                return {"src": await asyncio.to_thread(y.stream_url, str(msg["id"]))}
            if op == "like":
                return {"ok": await asyncio.to_thread(y.like, str(msg["id"]), bool(msg.get("on", True)))}
        except ProviderError as e:
            from desktop.core.api.server import ApiError
            raise ApiError("yandex_unavailable", str(e)) from None
        raise ValueError(f"op {op}")

    async def cmd_level(self, msg):
        # Уровень с AnalyserNode встроенного плеера → эквалайзер главной и сфера оверлея.
        bars = [max(0.0, min(1.0, float(b))) for b in (msg.get("bars") or [])][:32]
        self._emit({"type": "audio_level", "bars": bars, "source": "builtin"})

    async def cmd_settings(self, msg):
        if "key" in msg:
            return self.set(str(msg["key"]), msg.get("value"))
        return self.snapshot()

    async def cmd_external(self, msg):
        op = msg.get("op", "now_playing")
        if op == "now_playing":
            return {"track": await remote_smtc.now_playing()}
        if op in ("play_pause", "next", "prev"):
            return {"ok": await remote_smtc.control(op)}
        raise ValueError(f"op {op}")

    async def cmd_clear_covers(self, msg):
        return {"removed": self.library.clear_cover_cache()}
