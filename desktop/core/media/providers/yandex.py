"""yandex — Яндекс.Музыка во встроенном плеере (опция MUSIC_YANDEX=1, по умолчанию выкл.).

Неофициальная библиотека yandex-music (MarshalX, LGPL-3.0; API получен обратной
разработкой и может меняться). Токен — YANDEX_MUSIC_TOKEN из .env; в логах и
сообщениях об ошибках его нет. Воспроизведение — прямые ссылки из
get_download_info(get_direct_links=True), окно получает их через локальный медиасервер
(media_server, маршрут /yandex/<id>). Любая ошибка → ProviderError с понятным
текстом; вызывающий откатывается на remote_smtc.
"""
import logging
import threading
import time

from . import ProviderError

log = logging.getLogger("sakura.media")

UNOFFICIAL_NOTE = "неофициальный доступ"
WAVE_STATION = "user:onyourwave"
LINK_TTL_S = 45.0       # прямая ссылка живёт недолго: дольше не кэшируем


def _track_dict(t) -> dict:
    artists = ", ".join(a.name for a in (getattr(t, "artists", None) or []) if getattr(a, "name", None))
    albums = getattr(t, "albums", None) or []
    album = albums[0] if albums else None
    cover = getattr(t, "cover_uri", None) or (getattr(album, "cover_uri", None) if album else None)
    return {"id": f"ym:{t.id}" if not str(t.id).startswith("ym:") else str(t.id), "source": "yandex",
            "title": getattr(t, "title", "") or "", "artist": artists,
            "album": getattr(album, "title", "") if album else "",
            "album_id": str(album.id) if getattr(album, "id", None) else None,
            "duration": (getattr(t, "duration_ms", 0) or 0) / 1000.0,
            "cover": f"https://{cover.replace('%%', '200x200')}" if cover else None}


def _album_dict(a) -> dict:
    artists = ", ".join(x.name for x in (getattr(a, "artists", None) or []) if getattr(x, "name", None))
    return {"id": str(a.id), "title": getattr(a, "title", "") or "", "artist": artists,
            "year": getattr(a, "year", None), "tracks": getattr(a, "track_count", None) or 0}


def _artist_dict(a) -> dict:
    return {"id": str(a.id), "name": getattr(a, "name", "") or ""}


def _playlist_dict(p) -> dict:
    owner = getattr(getattr(p, "owner", None), "uid", None) or getattr(p, "uid", None)
    return {"id": f"ym:{owner}:{p.kind}" if owner else f"ym:{p.kind}", "name": getattr(p, "title", "") or "",
            "tracks": getattr(p, "track_count", None) or 0}


def parse_playlist_id(pid) -> tuple[str | None, int]:
    """ym:<kind> или ym:<владелец>:<kind> → (владелец | None, kind)."""
    parts = str(pid).removeprefix("ym:").split(":")
    return (parts[0], int(parts[1])) if len(parts) == 2 else (None, int(parts[0]))


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("ё", "е").split())


def best_match(items: list[dict], query: str, key: str) -> dict | None:
    """Точное совпадение → начало названия → вхождение; иначе None."""
    q = _norm(query)
    if not q:
        return None
    for test in (lambda n: n == q, lambda n: n.startswith(q), lambda n: q in n):
        for it in items:
            if test(_norm(it.get(key, ""))):
                return it
    return None


class YandexProvider:
    def __init__(self, token: str, enabled: bool, client_factory=None):
        self.enabled = bool(enabled and token)
        self._token = token
        self._factory = client_factory
        self._client = None
        self._lock = threading.Lock()
        self._links: dict[str, tuple[float, str]] = {}

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
            return [_playlist_dict(p) for p in (c.users_playlists_list() or [])]
        return self._call("плейлисты", f)

    def playlist_tracks(self, pid) -> list[dict]:
        owner, kind = parse_playlist_id(pid)

        def f(c):
            p = c.users_playlists(kind, owner) if owner else c.users_playlists(kind)
            return [_track_dict(s.track or s.fetch_track()) for s in (p.tracks or [])]
        return self._call("плейлист", f)

    # ── поиск по каталогу ──────────────────────────────────────────
    def search_all(self, q: str, limit: int = 8) -> dict:
        """Треки, альбомы, исполнители и плейлисты одним запросом."""
        def f(c):
            r = c.search(q, type_="all")
            pick = lambda block: ((getattr(block, "results", None) or [])[:limit] if block else [])  # noqa: E731
            return {"tracks": [_track_dict(t) for t in pick(r.tracks)] if r else [],
                    "albums": [_album_dict(a) for a in pick(r.albums)] if r else [],
                    "artists": [_artist_dict(a) for a in pick(r.artists)] if r else [],
                    "playlists": [_playlist_dict(p) for p in pick(r.playlists)] if r else []}
        return self._call("поиск", f)

    def find_artist(self, q: str) -> dict | None:
        def f(c):
            r = c.search(q, type_="artist")
            hits = (r.artists.results if r and r.artists else []) or []
            return _artist_dict(hits[0]) if hits else None
        return self._call("поиск исполнителя", f)

    def find_album(self, q: str) -> dict | None:
        def f(c):
            r = c.search(q, type_="album")
            hits = (r.albums.results if r and r.albums else []) or []
            return _album_dict(hits[0]) if hits else None
        return self._call("поиск альбома", f)

    def find_playlist(self, q: str) -> dict | None:
        """Сначала свои плейлисты, потом публичные из каталога."""
        own = best_match(self.playlists(), q, "name")
        if own:
            return own

        def f(c):
            r = c.search(q, type_="playlist")
            hits = (r.playlists.results if r and r.playlists else []) or []
            return _playlist_dict(hits[0]) if hits else None
        return self._call("поиск плейлиста", f)

    def artist_tracks(self, artist_id, limit: int = 50) -> list[dict]:
        def f(c):
            r = c.artists_tracks(artist_id, page_size=limit)
            return [_track_dict(t) for t in (r.tracks if r else []) or []]
        return self._call("треки исполнителя", f)

    def album_tracks(self, album_id) -> list[dict]:
        def f(c):
            a = c.albums_with_tracks(album_id)
            return [_track_dict(t) for vol in (getattr(a, "volumes", None) or []) for t in vol]
        return self._call("альбом", f)

    def similar(self, track_id: str, limit: int = 20) -> list[dict]:
        tid = str(track_id).removeprefix("ym:")

        def f(c):
            r = c.tracks_similar(tid)
            return [_track_dict(t) for t in (getattr(r, "similar_tracks", None) or [])[:limit]]
        return self._call("похожие треки", f)

    def lyrics(self, track_id: str) -> str | None:
        tid = str(track_id).removeprefix("ym:")

        def f(c):
            try:
                r = c.tracks_lyrics(tid)
            except Exception as e:  # у трека нет текста — это не сбой
                if type(e).__name__ == "NotFoundError":
                    return None
                raise
            return r.fetch_lyrics() if r else None
        return self._call("текст песни", f)

    def chart(self, limit: int = 50) -> list[dict]:
        def f(c):
            info = c.chart()
            shorts = (getattr(getattr(info, "chart", None), "tracks", None) or [])[:limit]
            return [_track_dict(s.track or s.fetch_track()) for s in shorts]
        return self._call("чарт", f)

    def new_releases(self, albums: int = 5) -> list[dict]:
        def f(c):
            ids = (getattr(c.new_releases(), "new_releases", None) or [])[:albums]
            out: list[dict] = []
            for aid in ids:
                a = c.albums_with_tracks(aid)
                out += [_track_dict(t) for vol in (getattr(a, "volumes", None) or []) for t in vol]
            return out
        return self._call("новинки", f)

    def playlist_of_day(self) -> dict | None:
        def f(c):
            for gp in getattr(c.feed(), "generated_playlists", None) or []:
                pl = getattr(gp, "data", None)
                if getattr(gp, "type", "") == "playlistOfTheDay" and pl is not None:
                    return _playlist_dict(pl)
            return None
        return self._call("плейлист дня", f)

    # ── станции и «Моя волна» ──────────────────────────────────────
    def stations(self) -> list[dict]:
        def f(c):
            out = []
            for r in c.rotor_stations_list() or []:
                st = getattr(r, "station", None)
                if st is not None and getattr(st, "id", None) is not None:
                    out.append({"id": f"{st.id.type}:{st.id.tag}", "name": getattr(st, "name", "") or ""})
            return out
        return self._call("станции", f)

    def station_tracks(self, station: str = WAVE_STATION, after: str | None = None, count: int = 10) -> dict:
        """Порция станции: {items, batch_id}. after — последний трек, чтобы волна шла дальше."""
        tid = str(after).removeprefix("ym:") if after else None

        def f(c):
            r = c.rotor_station_tracks(station, queue=tid) if tid else c.rotor_station_tracks(station)
            items = [_track_dict(s.track) for s in (r.sequence or [])[:count] if getattr(s, "track", None)]
            return {"items": items, "batch_id": getattr(r, "batch_id", None)}
        return self._call("станция", f)

    def wave(self, count: int = 10) -> list[dict]:
        """«Моя волна» (rotor, станция user:onyourwave)."""
        return self.station_tracks(WAVE_STATION, count=count)["items"]

    def station_feedback(self, station: str, event: str, track_id: str | None = None, played: float = 0.0,
                         batch_id: str | None = None) -> bool:
        """Станция учится на прослушиваниях: started | trackStarted | trackFinished | skip."""
        tid = str(track_id).removeprefix("ym:") if track_id else None

        def f(c):
            if event == "started":
                return c.rotor_station_feedback_radio_started(station, "sakura", batch_id=batch_id)
            if event == "trackStarted":
                return c.rotor_station_feedback_track_started(station, tid, batch_id=batch_id)
            if event == "trackFinished":
                return c.rotor_station_feedback_track_finished(station, tid, played, batch_id=batch_id)
            if event == "skip":
                return c.rotor_station_feedback_skip(station, tid, played, batch_id=batch_id)
            raise ProviderError(f"Яндекс.Музыка: неизвестное событие станции ({event})")
        return bool(self._call("отзыв станции", f))

    # ── поток ──────────────────────────────────────────────────────
    def stream_url(self, track_id: str, fresh: bool = False) -> str:
        tid = str(track_id).removeprefix("ym:")
        cached = self._links.get(tid)
        if cached and not fresh and time.monotonic() - cached[0] < LINK_TTL_S:
            return cached[1]

        def f(c):
            infos = c.tracks_download_info(tid, get_direct_links=True)
            mp3 = [i for i in infos if getattr(i, "codec", "") == "mp3"] or list(infos)
            if not mp3:
                raise ProviderError("Яндекс.Музыка: нет ссылки на трек")
            best = max(mp3, key=lambda i: getattr(i, "bitrate_in_kbps", 0) or 0)
            return best.direct_link
        link = self._call("ссылка на трек", f)
        self._links[tid] = (time.monotonic(), link)
        return link

    # ── лайки ──────────────────────────────────────────────────────
    def like(self, track_id: str, on: bool = True) -> bool:
        tid = str(track_id).removeprefix("ym:")
        return bool(self._call("лайк", lambda c: c.users_likes_tracks_add(tid) if on
                               else c.users_dislikes_tracks_add(tid)))

    def unlike(self, track_id: str) -> bool:
        tid = str(track_id).removeprefix("ym:")
        return bool(self._call("снятие лайка", lambda c: c.users_likes_tracks_remove(tid)))

    def like_album(self, album_id) -> bool:
        return bool(self._call("лайк альбома", lambda c: c.users_likes_albums_add(album_id)))

    def like_artist(self, artist_id) -> bool:
        return bool(self._call("лайк исполнителя", lambda c: c.users_likes_artists_add(artist_id)))

    def track_refs(self, track_id: str) -> dict:
        """{album_id, artist_id, title, artist} текущего трека."""
        tid = str(track_id).removeprefix("ym:")

        def f(c):
            t = (c.tracks([tid]) or [None])[0]
            if t is None:
                raise ProviderError("Яндекс.Музыка: трек не найден")
            albums, artists = t.albums or [], t.artists or []
            return {"album_id": str(albums[0].id) if albums else None,
                    "album": albums[0].title if albums else "",
                    "artist_id": str(artists[0].id) if artists else None,
                    "artist": artists[0].name if artists else "", "title": t.title}
        return self._call("данные трека", f)

    # ── свои плейлисты ─────────────────────────────────────────────
    def playlist_create(self, title: str) -> dict:
        return self._call("создание плейлиста",
                          lambda c: _playlist_dict(c.users_playlists_create(title, visibility="private")))

    def playlist_delete(self, pid) -> bool:
        _, kind = parse_playlist_id(pid)
        return bool(self._call("удаление плейлиста", lambda c: c.users_playlists_delete(kind)))

    def playlist_add(self, pid, track_id: str) -> bool:
        _, kind = parse_playlist_id(pid)
        tid = str(track_id).removeprefix("ym:")

        def f(c):
            t = (c.tracks([tid]) or [None])[0]
            albums = getattr(t, "albums", None) or []
            if not albums:
                raise ProviderError("Яндекс.Музыка: у трека нет альбома, в плейлист не добавить")
            p = c.users_playlists(kind)
            return c.users_playlists_insert_track(kind, tid, albums[0].id, at=p.track_count or 0,
                                                  revision=p.revision or 1)
        return bool(self._call("добавление в плейлист", f))

    def playlist_remove(self, pid, track_id: str) -> bool:
        """False — такого трека в плейлисте нет."""
        _, kind = parse_playlist_id(pid)
        tid = str(track_id).removeprefix("ym:")

        def f(c):
            p = c.users_playlists(kind)
            for i, s in enumerate(p.tracks or []):
                if str(getattr(s, "id", "")).split(":")[0] == tid:
                    return c.users_playlists_delete_track(kind, i, i + 1, revision=p.revision or 1)
            return False
        return bool(self._call("удаление из плейлиста", f))
