"""desktop.core.media.yandex_api — доступ к Яндекс.Музыке по токену (yandex-music, ClientAsync).

Библиотека yandex-music (LGPLv3) только вызывается; API неофициальный — ответы могут меняться:
ошибки 401/403, сети и несовпадения схемы не роняют панель, а дают статус «недоступно».
Токен — только из .env (config.YANDEX_MUSIC_TOKEN); не пишется в журнал и не возвращается.
Личные данные библиотеки остаются локальными: наружу — только счётчики и статусы (inventory) или
ответ на явную команду пользователя. Аудио не скачивается и по прямым ссылкам не воспроизводится.
"""
import asyncio
import logging

from desktop.core import results as R

log = logging.getLogger("sakura.media.yandex")
TIMEOUT_S = 8.0


def _token() -> str:
    from desktop.core import config
    return (config.YANDEX_MUSIC_TOKEN or "").strip()


def _err(e: Exception) -> str:
    text = f"{type(e).__name__} {e}".lower()
    if "unauthorized" in text or "401" in text:
        return "токен не принят (401) — обновите YANDEX_MUSIC_TOKEN"
    if "forbidden" in text or "403" in text:
        return "доступ запрещён (403) — возможно, нужна подписка Плюс"
    if "timeout" in text or "network" in text or "connect" in text:
        return "нет связи с Яндекс.Музыкой"
    return f"ошибка API ({type(e).__name__})"


class _ThreadedClient:
    """Синхронный yandex_music.Client за асинхронным интерфейсом: вызовы — в потоке.

    ClientAsync требует aiohttp, которого нет в общем venv агента; ставить пакеты в него не стали
    (DECISIONS №48). Методы возвращают корутины, атрибуты (me) — как есть.
    """

    def __init__(self, client):
        self._c = client
        self.me = client.me

    def __getattr__(self, name):
        fn = getattr(self._c, name)
        if not callable(fn):
            return fn

        async def call(*a, **k):
            return await asyncio.to_thread(fn, *a, **k)
        return call


async def _make_client():
    try:
        import aiohttp  # noqa: F401
        from yandex_music import ClientAsync
        return await ClientAsync(_token(), report_unknown_fields=False).init()
    except ImportError:
        from yandex_music import Client
        return _ThreadedClient(await asyncio.to_thread(lambda: Client(_token(), report_unknown_fields=False).init()))


class YandexApi:
    def __init__(self, client_factory=None, token=None):
        self._factory = client_factory
        self._token = token
        self._client = None
        self._uid = None

    def has_token(self) -> bool:
        return bool(self._token if self._token is not None else _token())

    async def client(self):
        if self._client is None:
            if self._factory is not None:
                self._client = await self._factory()
            else:
                self._client = await asyncio.wait_for(_make_client(), TIMEOUT_S)
            try:
                self._uid = self._client.me.account.uid
            except Exception:  # noqa: BLE001
                self._uid = None
        return self._client

    async def _call(self, coro):
        return await asyncio.wait_for(coro, TIMEOUT_S)

    # ── «Проверить токен»: что доступно — только счётчики и статусы ──
    async def inventory(self) -> dict:
        if not self.has_token():
            return {"token": False}
        try:
            c = await self.client()
        except Exception as e:  # noqa: BLE001
            return {"token": True, "ok": False, "error": _err(e)}
        uid = self._uid
        checks = {
            "аккаунт": lambda: c.account_status(),
            "лайки": lambda: c.users_likes_tracks(user_id=uid),
            "дизлайки": lambda: c.users_dislikes_tracks(user_id=uid),
            "плейлисты": lambda: c.users_playlists_list(user_id=uid),
            "ленточные плейлисты": lambda: c.feed(),
            "история": lambda: c.music_history(),
            "станции «Моей волны»": lambda: c.rotor_stations_list(),
            "поиск": lambda: c.search("Кино", type_="track"),
            "новинки": lambda: c.new_releases(),
        }
        out = {"token": True, "ok": True, "items": {}}
        for name, fn in checks.items():
            try:
                res = await self._call(fn())
                out["items"][name] = {"ok": True, "count": _count(res)}
            except Exception as e:  # noqa: BLE001
                out["items"][name] = {"ok": False, "error": _err(e)}
        for name, fn in (("текст", self._probe_lyrics), ("похожие", self._probe_similar),
                         ("детали трека", self._probe_details)):
            try:
                out["items"][name] = await fn(c)
            except Exception as e:  # noqa: BLE001
                out["items"][name] = {"ok": False, "error": _err(e)}
        try:
            out["plus"] = bool(getattr(getattr(await self._call(c.account_status()), "plus", None), "has_plus", False))
        except Exception:  # noqa: BLE001
            out["plus"] = None
        log.info("[yandex] проверка токена: %s", {k: v.get("ok") for k, v in out["items"].items()})
        return out

    async def _sample_track(self, c):
        res = await self._call(c.search("Кино Группа крови", type_="track"))
        hits = (res.tracks.results if res and res.tracks else None) or []
        return hits[0] if hits else None

    async def _probe_lyrics(self, c):
        t = await self._sample_track(c)
        lyr = await self._call(c.tracks_lyrics(t.id)) if t else None
        return {"ok": bool(lyr)}

    async def _probe_similar(self, c):
        t = await self._sample_track(c)
        sim = await self._call(c.tracks_similar(t.id)) if t else None
        return {"ok": sim is not None, "count": len(getattr(sim, "similar_tracks", None) or [])}

    async def _probe_details(self, c):
        t = await self._sample_track(c)
        det = await self._call(c.tracks([t.id])) if t else None
        return {"ok": bool(det)}

    # ── обогащение текущего трека (в фоне) ──
    async def enrich(self, title: str, artist: str) -> dict:
        """{track_id, album_id, year, genre, liked?} — без ошибок наружу."""
        if not self.has_token() or not title:
            return {}
        try:
            c = await self.client()
            res = await self._call(c.search(f"{artist} {title}".strip(), type_="track"))
            hits = (res.tracks.results if res and res.tracks else None) or []
            if not hits:
                return {}
            t = hits[0]
            alb = (t.albums or [None])[0]
            return {"track_id": str(t.id), "album_id": str(alb.id) if alb else None,
                    "year": getattr(alb, "year", None), "genre": getattr(alb, "genre", None)}
        except Exception as e:  # noqa: BLE001
            log.info("[yandex] обогащение: %s", _err(e))
            return {}

    # ── действия по явной команде ──
    async def playlists(self) -> dict:
        try:
            c = await self.client()
            pls = await self._call(c.users_playlists_list(user_id=self._uid)) or []
            names = [p.title for p in pls][:20]
            return R.done("Плейлисты: " + "; ".join(names) if names else "плейлистов нет", playlists=names)
        except Exception as e:  # noqa: BLE001
            return R.failed(_err(e))

    async def history(self) -> dict:
        try:
            c = await self.client()
            h = await self._call(c.music_history())
            return R.done(f"в истории {_count(h)} записей")
        except Exception as e:  # noqa: BLE001
            return R.failed(_err(e))

    async def similar(self, title: str, artist: str) -> dict:
        try:
            info = await self.enrich(title, artist)
            if not info.get("track_id"):
                return R.failed("трек не найден в каталоге")
            c = await self.client()
            sim = await self._call(c.tracks_similar(info["track_id"]))
            items = [f"{(t.artists or [None])[0].name if t.artists else ''} — {t.title}"
                     for t in (getattr(sim, "similar_tracks", None) or [])[:10]]
            return R.done("Похожее: " + "; ".join(items) if items else "похожих нет", tracks=items)
        except Exception as e:  # noqa: BLE001
            return R.failed(_err(e))

    async def playlist_of_day(self) -> dict:
        """Плейлист дня из ленты (только имя и id — открывает приложение через UI Automation)."""
        try:
            c = await self.client()
            feed = await self._call(c.feed())
            for gp in getattr(feed, "generated_playlists", None) or []:
                pl = getattr(gp, "data", None)
                if getattr(gp, "type", "") == "playlistOfTheDay" and pl is not None:
                    return R.done(f"плейлист дня: {pl.title}", title=pl.title, kind=pl.kind, uid=pl.uid)
            return R.failed("плейлиста дня нет в ленте")
        except Exception as e:  # noqa: BLE001
            return R.failed(_err(e))

    async def rotor_feedback_started(self, track_id: str) -> dict:
        """«Моя волна» узнаёт, что трек начался (по явному включению волны из Сакуры)."""
        try:
            c = await self.client()
            await self._call(c.rotor_station_feedback_track_started("user:onyourwave", track_id))
            return R.done("волна учла трек")
        except Exception as e:  # noqa: BLE001
            return R.failed(_err(e))


def _count(res) -> int | None:
    if res is None:
        return 0
    for attr in ("tracks", "items", "results", "new_releases", "generated_playlists", "stations"):
        v = getattr(res, attr, None)
        if isinstance(v, list):
            return len(v)
    if isinstance(res, list):
        return len(res)
    return None
