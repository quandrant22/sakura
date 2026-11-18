"""desktop.core.media.yandex_commands — голосовые команды Яндекс.Музыки для встроенного плеера.

Ядро находит музыку через провайдер, а играет окно: команды уходят событием media_command
(ym_play, ym_enqueue, ym_show, queue_clear, queue_remove, seek, volumeSet). run() возвращает
(ok, текст ответа) либо None — выполнить внешним путём (приложение Яндекс.Музыки).
"""
import asyncio
import logging
import re
from collections import deque

from .providers import ProviderError
from .providers.yandex import WAVE_STATION, _norm, best_match

log = logging.getLogger("sakura.media")

# Глаголы, которые исполняются здесь, пока встроенная Яндекс.Музыка включена.
VERBS = ("play_track", "play_artist", "play_album", "play_playlist", "wave", "liked_tracks", "station", "similar",
         "chart", "new_releases", "playlist_of_day", "queue_add", "play_next", "queue_show", "queue_clear",
         "queue_remove", "search", "playlists", "history", "lyrics", "unlike", "like_album", "like_artist",
         "playlist_add", "playlist_remove", "playlist_create", "playlist_delete", "seek_to", "volume_set")
# При сбое API эти команды может выполнить установленное приложение.
EXTERNAL_FALLBACK = frozenset({"play_track", "wave", "liked_tracks", "playlists", "history"})

NOTHING_PLAYING = "Сейчас из Яндекс Музыки ничего не играет"
_SHUFFLE = re.compile(r"\s*\b(?:вперемешку|в случайном порядке)\b\s*", re.IGNORECASE)
_KIND = re.compile(r"^(альбом|плейлист|исполнител[яь]|артиста?)\s+(.+)$", re.IGNORECASE)
_TO_PLAYLIST = re.compile(r"^(.*?)\s*\bв\s+плейлист\s+(.+)$", re.IGNORECASE)
_FROM_PLAYLIST = re.compile(r"^(?:.*?\bиз\s+плейлиста\s+)?(.+)$", re.IGNORECASE)
_LIKED_NAMES = ("мне нравится", "любимое", "любимые", "любимые треки")


def parse_seek(arg: str) -> tuple[str, int] | None:
    """«1:30» → ("seek", 90), «начало» → ("seek", 0), «30 секунд вперёд» → ("seekBy", 30), «минуту назад» → ("seekBy", -60)."""
    text = (arg or "").strip().lower().replace("ё", "е")
    if text in ("начало", "самое начало"):
        return "seek", 0
    m = re.fullmatch(r"(.*?)\s*(вперед|назад)", text)
    if m:
        sec = _seconds(m.group(1) or "10")
        return None if sec is None else ("seekBy", sec if m.group(2) == "вперед" else -sec)
    sec = _seconds(text)
    return None if sec is None else ("seek", sec)


def _seconds(text: str) -> int | None:
    """«2:40», «160», «2 минуты 40 секунд», «минуту», «40 секунд»."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    if text.isdigit():
        return int(text)
    if re.fullmatch(r"минут[ауы]?", text):
        return 60
    parts = re.findall(r"(\d+)\s*(мин\w*|сек\w*)", text)
    if not parts or re.sub(r"\d+\s*(?:мин\w*|сек\w*)|\bи\b|\s", "", text):
        return None
    return sum(int(n) * (60 if unit.startswith("мин") else 1) for n, unit in parts)


def _who(t: dict) -> str:
    return f"{t['artist']} — {t['title']}" if t.get("artist") else t.get("title", "")


class YandexCommands:
    def __init__(self, provider, emit, router):
        self._provider = provider       # () → YandexProvider: провайдер пересоздаётся при смене токена
        self._emit = emit
        self._router = router
        self.queue: list[dict] = []
        self.index = -1
        self.recent: deque[dict] = deque(maxlen=20)
        self._background: set[asyncio.Future] = set()   # держим ссылки, иначе задачу может собрать GC

    @property
    def y(self):
        return self._provider()

    def set_queue(self, items: list[dict], index: int):
        self.queue, self.index = items, index

    def note_played(self, title: str, artist: str):
        self.recent.appendleft({"title": title, "artist": artist})

    def _send(self, cmd: str, arg=None):
        self._emit({"type": "media_command", "player": "music", "cmd": cmd, "arg": arg})

    def _current(self) -> str | None:
        st = self._router.players["music"]
        return st.extra.get("ym_id") if st.status in ("playing", "paused") else None

    async def run(self, verb: str, arg: str = ""):
        try:
            return await getattr(self, f"_{verb}")((arg or "").strip())
        except ProviderError as e:
            log.info("[yandex] %s: %s", verb, e)
            return None if verb in EXTERNAL_FALLBACK else (False, str(e))

    # ── запуск музыки ──────────────────────────────────────────────
    def _play(self, tracks: list[dict], label: str, station: str | None = None, batch_id: str | None = None,
              shuffle: bool = False):
        if not tracks:
            return False, f"Не нашла треков: {label}"
        self._send("ym_play", {"tracks": tracks, "station": station, "batch_id": batch_id, "shuffle": shuffle})
        return True, f"Включила {label}"

    async def _play_track(self, q: str):
        if not q:
            return False, "Какой трек включить?"
        hits = await asyncio.to_thread(self.y.search, q, 1)
        if not hits:
            return False, f"Не нашла трек «{q}»"
        tid = str(hits[0]["id"]).removeprefix("ym:")
        return self._play(hits[:1], _who(hits[0]), station=f"track:{tid}")

    async def _play_artist(self, q: str):
        name, shuffle = self._shuffle(q)
        artist = await asyncio.to_thread(self.y.find_artist, name)
        if not artist:
            return False, f"Не нашла исполнителя «{name}»"
        tracks = await asyncio.to_thread(self.y.artist_tracks, artist["id"])
        return self._play(tracks, artist["name"], shuffle=shuffle)

    async def _play_album(self, q: str):
        name, shuffle = self._shuffle(q)
        album = await asyncio.to_thread(self.y.find_album, name)
        if not album:
            return False, f"Не нашла альбом «{name}»"
        tracks = await asyncio.to_thread(self.y.album_tracks, album["id"])
        return self._play(tracks, f"альбом «{album['title']}»", shuffle=shuffle)

    async def _play_playlist(self, q: str):
        name, shuffle = self._shuffle(q)
        if _norm(name) in _LIKED_NAMES:
            return await self._liked_tracks(q)
        pl = await asyncio.to_thread(self.y.find_playlist, name)
        if not pl:
            return False, f"Не нашла плейлист «{name}»"
        tracks = await asyncio.to_thread(self.y.playlist_tracks, pl["id"])
        return self._play(tracks, f"плейлист «{pl['name']}»", shuffle=shuffle)

    async def _wave(self, _arg: str):
        return await self._start_station(WAVE_STATION, "«Мою волну»")

    async def _start_station(self, station: str, label: str):
        batch = await asyncio.to_thread(self.y.station_tracks, station)
        res = self._play(batch["items"], label, station=station, batch_id=batch.get("batch_id"))
        if res[0]:
            task = asyncio.ensure_future(self._feedback(station, "started", batch_id=batch.get("batch_id")))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        return res

    async def _feedback(self, station: str, event: str, **kw):
        try:
            await asyncio.to_thread(self.y.station_feedback, station, event, **kw)
        except ProviderError:
            pass  # отзыв станции не должен мешать музыке

    async def _liked_tracks(self, arg: str):
        _, shuffle = self._shuffle(arg)
        tracks = await asyncio.to_thread(self.y.liked)
        return self._play(tracks, "«Мне нравится»", shuffle=shuffle)

    async def _station(self, q: str):
        if not q:
            return False, "Какую станцию включить?"
        items = await asyncio.to_thread(self.y.stations)
        tagged = [{**s, "tag": s["id"].split(":", 1)[-1]} for s in items]
        hit = best_match(tagged, q, "name") or best_match(tagged, q, "tag")
        if not hit:
            return False, f"Не нашла станцию «{q}»"
        return await self._start_station(hit["id"], f"станцию «{hit['name']}»")

    async def _similar(self, _arg: str):
        tid = self._current()
        if not tid:
            return False, NOTHING_PLAYING
        tracks = await asyncio.to_thread(self.y.similar, tid)
        return self._play(tracks, "похожую музыку", station=f"track:{str(tid).removeprefix('ym:')}")

    async def _chart(self, _arg: str):
        return self._play(await asyncio.to_thread(self.y.chart), "чарт Яндекс Музыки")

    async def _new_releases(self, _arg: str):
        return self._play(await asyncio.to_thread(self.y.new_releases), "новинки")

    async def _playlist_of_day(self, _arg: str):
        pl = await asyncio.to_thread(self.y.playlist_of_day)
        if not pl:
            return False, "Плейлиста дня сегодня нет в ленте"
        tracks = await asyncio.to_thread(self.y.playlist_tracks, pl["id"])
        return self._play(tracks, "плейлист дня")

    @staticmethod
    def _shuffle(text: str) -> tuple[str, bool]:
        clean, n = _SHUFFLE.subn(" ", text or "")
        return clean.strip(), n > 0

    # ── очередь ────────────────────────────────────────────────────
    async def _resolve(self, q: str) -> tuple[list[dict], str]:
        """«альбом X» / «плейлист X» / «исполнителя X» / просто трек → (треки, подпись)."""
        m = _KIND.match(q)
        kind, name = (m.group(1).lower(), m.group(2)) if m else ("", q)
        if kind == "альбом":
            album = await asyncio.to_thread(self.y.find_album, name)
            if album:
                return await asyncio.to_thread(self.y.album_tracks, album["id"]), f"альбом «{album['title']}»"
        elif kind == "плейлист":
            pl = await asyncio.to_thread(self.y.find_playlist, name)
            if pl:
                return await asyncio.to_thread(self.y.playlist_tracks, pl["id"]), f"плейлист «{pl['name']}»"
        elif kind:
            artist = await asyncio.to_thread(self.y.find_artist, name)
            if artist:
                return await asyncio.to_thread(self.y.artist_tracks, artist["id"], 20), artist["name"]
        else:
            hits = await asyncio.to_thread(self.y.search, name, 1)
            if hits:
                return hits[:1], _who(hits[0])
        return [], name

    async def _enqueue(self, q: str, play_next: bool):
        if not q:
            return False, "Что добавить в очередь?"
        tracks, label = await self._resolve(q)
        if not tracks:
            return False, f"Не нашла «{label}»"
        self._send("ym_enqueue", {"tracks": tracks, "next": play_next})
        return True, f"Поставила следующим: {label}" if play_next else f"Добавила в очередь: {label}"

    async def _queue_add(self, q: str):
        return await self._enqueue(q, False)

    async def _play_next(self, q: str):
        return await self._enqueue(q, True)

    async def _queue_show(self, _arg: str):
        upcoming = self.queue[self.index + 1:self.index + 6] if self.index >= 0 else []
        if not upcoming:
            return True, "В очереди больше ничего нет"
        rest = len(self.queue) - self.index - 1 - len(upcoming)
        tail = f" и ещё {rest}" if rest > 0 else ""
        return True, "Дальше: " + "; ".join(_who(t) for t in upcoming) + tail

    async def _queue_clear(self, _arg: str):
        self._send("queue_clear")
        return True, "Очистила очередь"

    async def _queue_remove(self, q: str):
        upcoming = list(enumerate(self.queue))[self.index + 1:]
        if q.isdigit():
            n = int(q)
            hit = upcoming[n - 1] if 1 <= n <= len(upcoming) else None
        else:
            needle = _norm(q)
            hit = next((p for p in upcoming if needle and (needle in _norm(p[1].get("title", ""))
                                                           or needle in _norm(p[1].get("artist", "")))), None)
        if hit is None:
            return False, f"В очереди не нашла «{q}»"
        self._send("queue_remove", hit[0])
        return True, f"Убрала из очереди: {_who(hit[1])}"

    # ── библиотека ─────────────────────────────────────────────────
    async def _search(self, q: str):
        if not q:
            return False, "Что найти?"
        r = await asyncio.to_thread(self.y.search_all, q)
        self._send("ym_show", {"view": "search", "q": q})
        parts = []
        if r["tracks"]:
            parts.append("треки: " + "; ".join(_who(t) for t in r["tracks"][:3]))
        if r["artists"]:
            parts.append("исполнители: " + ", ".join(a["name"] for a in r["artists"][:3]))
        if r["albums"]:
            parts.append("альбомы: " + ", ".join(a["title"] for a in r["albums"][:3]))
        if r["playlists"]:
            parts.append("плейлисты: " + ", ".join(p["name"] for p in r["playlists"][:3]))
        return (True, "Нашла " + ". ".join(parts)) if parts else (False, f"Ничего не нашла по запросу «{q}»")

    async def _playlists(self, _arg: str):
        items = await asyncio.to_thread(self.y.playlists)
        self._send("ym_show", {"view": "playlists"})
        return True, ("Плейлисты: " + ", ".join(p["name"] for p in items[:20])) if items else "Плейлистов пока нет"

    async def _history(self, _arg: str):
        if not self.recent:
            return True, "Пока ничего не играло"
        return True, "Недавно: " + "; ".join(_who(t) for t in list(self.recent)[:5])

    async def _lyrics(self, _arg: str):
        tid = self._current()
        if not tid:
            return False, NOTHING_PLAYING
        text = await asyncio.to_thread(self.y.lyrics, tid)
        if not text:
            return False, "У этой песни нет текста"
        title = self._router.players["music"].title
        # Текст показывается только в окне и на сервер не уходит.
        self._send("ym_show", {"view": "lyrics", "title": title, "text": text})
        return True, f"Показала текст песни «{title}»"

    async def _unlike(self, _arg: str):
        tid = self._current()
        if not tid:
            return False, NOTHING_PLAYING
        await asyncio.to_thread(self.y.unlike, tid)
        self._send("ym_liked", {"id": tid, "on": False})
        return True, "Убрала лайк"

    async def _like_album(self, _arg: str):
        tid = self._current()
        if not tid:
            return False, NOTHING_PLAYING
        refs = await asyncio.to_thread(self.y.track_refs, tid)
        if not refs["album_id"]:
            return False, "У этого трека нет альбома"
        await asyncio.to_thread(self.y.like_album, refs["album_id"])
        return True, f"Добавила в коллекцию альбом «{refs['album']}»"

    async def _like_artist(self, _arg: str):
        tid = self._current()
        if not tid:
            return False, NOTHING_PLAYING
        refs = await asyncio.to_thread(self.y.track_refs, tid)
        if not refs["artist_id"]:
            return False, "У этого трека нет исполнителя"
        await asyncio.to_thread(self.y.like_artist, refs["artist_id"])
        return True, f"Добавила в любимые исполнителя {refs['artist']}"

    # ── свои плейлисты ─────────────────────────────────────────────
    async def _own_playlist(self, name: str) -> dict | None:
        return best_match(await asyncio.to_thread(self.y.playlists), name, "name")

    async def _playlist_add(self, arg: str):
        m = _TO_PLAYLIST.match(arg)
        track_q, name = (m.group(1).strip(), m.group(2).strip()) if m else ("", arg)
        if not name:
            return False, "В какой плейлист добавить?"
        pl = await self._own_playlist(name)
        if not pl:
            return False, f"Не нашла у тебя плейлист «{name}»"
        if track_q:
            hits = await asyncio.to_thread(self.y.search, track_q, 1)
            if not hits:
                return False, f"Не нашла трек «{track_q}»"
            tid, label = hits[0]["id"], _who(hits[0])
        else:
            tid, label = self._current(), self._router.players["music"].title
            if not tid:
                return False, NOTHING_PLAYING
        await asyncio.to_thread(self.y.playlist_add, pl["id"], tid)
        return True, f"Добавила «{label}» в плейлист «{pl['name']}»"

    async def _playlist_remove(self, arg: str):
        m = _FROM_PLAYLIST.match(arg)
        name = m.group(1).strip() if m else arg
        tid = self._current()
        if not tid:
            return False, NOTHING_PLAYING
        pl = await self._own_playlist(name)
        if not pl:
            return False, f"Не нашла у тебя плейлист «{name}»"
        if not await asyncio.to_thread(self.y.playlist_remove, pl["id"], tid):
            return False, f"Этого трека нет в плейлисте «{pl['name']}»"
        return True, f"Убрала трек из плейлиста «{pl['name']}»"

    async def _playlist_create(self, name: str):
        if not name:
            return False, "Как назвать плейлист?"
        pl = await asyncio.to_thread(self.y.playlist_create, name)
        return True, f"Создала плейлист «{pl['name']}»"

    async def _playlist_delete(self, name: str):
        # Удаление необратимо: только точное совпадение названия, без поиска «похожего».
        items = await asyncio.to_thread(self.y.playlists)
        hit = next((p for p in items if _norm(p["name"]) == _norm(name)), None)
        if not hit:
            return False, f"Не нашла у тебя плейлист с точным названием «{name}»"
        await asyncio.to_thread(self.y.playlist_delete, hit["id"])
        return True, f"Удалила плейлист «{hit['name']}»"

    # ── плеер ──────────────────────────────────────────────────────
    async def _seek_to(self, arg: str):
        target = parse_seek(arg)
        if target is None:
            return False, "На какое время перемотать?"
        if not self._router.active("music"):
            return False, NOTHING_PLAYING
        cmd, sec = target
        self._send(cmd, sec)
        if cmd == "seekBy":
            return True, f"Перемотала {'вперёд' if sec > 0 else 'назад'} на {abs(sec)} с"
        return True, f"Перемотала на {sec // 60}:{sec % 60:02d}"

    async def _volume_set(self, arg: str):
        m = re.search(r"\d+", arg)
        if not m or int(m.group(0)) > 100:
            return False, "Громкость музыки — число от 0 до 100"
        self._send("volumeSet", int(m.group(0)))
        return True, f"Громкость музыки {int(m.group(0))}%"
