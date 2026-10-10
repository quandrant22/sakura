"""yandex — Яндекс.Музыка во встроенном плеере (опция MUSIC_YANDEX=1, по умолчанию выкл.).

Неофициальная библиотека yandex-music (MarshalX, LGPL-3.0; API получен обратной
разработкой и может меняться). Токен — YANDEX_MUSIC_TOKEN из .env; в логах и
сообщениях об ошибках его нет. Воспроизведение — прямые ссылки из
get_download_info(get_direct_links=True). Любая ошибка → ProviderError с понятным
текстом; вызывающий откатывается на remote_smtc.
"""
import logging
import threading

from . import ProviderError

log = logging.getLogger("sakura.media")

UNOFFICIAL_NOTE = "неофициальный доступ"


def _track_dict(t) -> dict:
    artists = ", ".join(a.name for a in (getattr(t, "artists", None) or []) if getattr(a, "name", None))
    albums = getattr(t, "albums", None) or []
    album = albums[0] if albums else None
    cover = getattr(t, "cover_uri", None) or (getattr(album, "cover_uri", None) if album else None)
    return {"id": f"ym:{t.id}" if not str(t.id).startswith("ym:") else str(t.id), "source": "yandex",
            "title": getattr(t, "title", "") or "", "artist": artists,
            "album": getattr(album, "title", "") if album else "",
            "duration": (getattr(t, "duration_ms", 0) or 0) / 1000.0,
            "cover": f"https://{cover.replace('%%', '200x200')}" if cover else None}


class YandexProvider:
    def __init__(self, token: str, enabled: bool, client_factory=None):
        self.enabled = bool(enabled and token)
        self._token = token
        self._factory = client_factory
        self._client = None
        self._lock = threading.Lock()

    def _get(self):
        if not self.enabled:
            raise ProviderError("Яндекс.Музыка выключена (MUSIC_YANDEX=0 или нет токена)")
        with self._lock:
            if self._client is None:
                try:
                    if self._factory:
                        self._client = self._factory(self._token)
                    else:
                        from yandex_music import Client
                        self._client = Client(self._token).init()
                except Exception as e:
                    raise ProviderError(f"Яндекс.Музыка недоступна: {type(e).__name__}") from None
            return self._client

    def _call(self, what: str, fn):
        try:
            return fn(self._get())
        except ProviderError:
            raise
        except Exception as e:  # сеть, блокировка, изменение API — без деталей с токеном
            log.warning("[yandex] %s: %s", what, type(e).__name__)
            raise ProviderError(f"Яндекс.Музыка: не удалось ({what})") from None

    def search(self, q: str, limit: int = 30) -> list[dict]:
        def f(c):
            r = c.search(q, type_="track")
            items = (r.tracks.results if r and r.tracks else []) or []
            return [_track_dict(t) for t in items[:limit]]
        return self._call("поиск", f)

    def liked(self, limit: int = 200) -> list[dict]:
        def f(c):
            likes = c.users_likes_tracks()
            short = list(likes)[:limit] if likes else []
            tracks = c.tracks([s.track_id for s in short]) if short else []
            return [_track_dict(t) for t in tracks]
        return self._call("«Мне нравится»", f)

    def playlists(self) -> list[dict]:
        def f(c):
            return [{"id": f"ym:{p.kind}", "name": p.title, "tracks": p.track_count or 0}
                    for p in (c.users_playlists_list() or [])]
        return self._call("плейлисты", f)

    def playlist_tracks(self, kind: int) -> list[dict]:
        def f(c):
            p = c.users_playlists(kind)
            return [_track_dict(s.track or s.fetch_track()) for s in (p.tracks or [])]
        return self._call("плейлист", f)

    def wave(self, count: int = 10) -> list[dict]:
        """«Моя волна» (rotor, станция user:onyourwave)."""
        def f(c):
            r = c.rotor_station_tracks("user:onyourwave")
            return [_track_dict(s.track) for s in (r.sequence or [])[:count] if getattr(s, "track", None)]
        return self._call("«Моя волна»", f)

    def stream_url(self, track_id: str) -> str:
        tid = str(track_id).removeprefix("ym:")

        def f(c):
            infos = c.tracks_download_info(tid, get_direct_links=True)
            mp3 = [i for i in infos if getattr(i, "codec", "") == "mp3"] or list(infos)
            if not mp3:
                raise ProviderError("Яндекс.Музыка: нет ссылки на трек")
            best = max(mp3, key=lambda i: getattr(i, "bitrate_in_kbps", 0) or 0)
            return best.direct_link
        return self._call("ссылка на трек", f)

    def like(self, track_id: str, on: bool = True) -> bool:
        tid = str(track_id).removeprefix("ym:")
        return bool(self._call("лайк", lambda c: c.users_likes_tracks_add(tid) if on
                               else c.users_dislikes_tracks_add(tid)))
