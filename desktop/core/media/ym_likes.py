"""desktop.core.media.ym_likes — лайк и дизлайк текущего трека через API yandex-music (нужен токен).

Трек находится поиском «исполнитель название»; track_id кэшируется по паре (artist, title).
Состояние сердца — по списку лайков пользователя (обновляется не чаще раза в LIKES_TTL_S и сразу
после нажатия). Клиент API подменяется в тестах; все вызовы блокирующие — звать из потока.
"""
import logging
import time

from desktop.core import results as R

log = logging.getLogger("sakura.media.yandex")

LIKES_TTL_S = 60.0
NOT_FOUND = "Трек не найден в каталоге Яндекс.Музыки — лайк поставьте в приложении"
API_DOWN = "Яндекс.Музыка не ответила — проверьте интернет и попробуйте ещё раз"


def _default_client():
    from desktop.core.music import _get_ym_client
    return _get_ym_client()


class YmLikes:
    def __init__(self, client_factory=_default_client, clock=time.monotonic):
        self._factory = client_factory
        self._clock = clock
        self._client = None
        self._ids: dict[tuple[str, str], str | None] = {}
        self._liked: set[str] = set()
        self._liked_at = None

    def _c(self):
        if self._client is None:
            self._client = self._factory()
        return self._client

    def _uid(self):
        return self._c().me.account.uid

    def track_id(self, title: str, artist: str) -> str | None:
        key = (artist.strip().lower(), title.strip().lower())
        if key not in self._ids:
            res = self._c().search(f"{artist} {title}".strip(), type_="track")
            hits = (res.tracks.results if res and res.tracks else None) or []
            self._ids[key] = str(hits[0].id) if hits else None
        return self._ids[key]

    def _refresh_liked(self, force=False) -> None:
        now = self._clock()
        if force or self._liked_at is None or now - self._liked_at >= LIKES_TTL_S:
            likes = self._c().users_likes_tracks(user_id=self._uid())
            self._liked = {str(t.id).split(":")[0] for t in (likes.tracks if likes else None) or []}
            self._liked_at = now

    def liked(self, title: str, artist: str) -> bool | None:
        """True/False — состояние сердца; None — трек не найден или API не ответил."""
        try:
            tid = self.track_id(title, artist)
            if not tid:
                return None
            self._refresh_liked()
            return tid.split(":")[0] in self._liked
        except Exception as e:  # noqa: BLE001
            log.warning("[yandex] состояние лайка: %s", type(e).__name__)
            return None

    def toggle_like(self, title: str, artist: str) -> dict:
        """Лайк, а если уже стоит — снять лайк (как сердце в приложении)."""
        try:
            tid = self.track_id(title, artist)
            if not tid:
                return R.failed(NOT_FOUND)
            self._refresh_liked()
            uid = self._uid()
            if tid.split(":")[0] in self._liked:
                ok = self._c().users_likes_tracks_remove(tid, user_id=uid)
                msg = "убрала лайк"
            else:
                ok = self._c().users_likes_tracks_add(tid, user_id=uid)
                msg = "поставила лайк"
            self._refresh_liked(force=True)
            return R.done(msg, liked=tid.split(":")[0] in self._liked) if ok else \
                R.failed("Яндекс.Музыка не приняла лайк — попробуйте ещё раз")
        except Exception as e:  # noqa: BLE001
            log.warning("[yandex] лайк: %s", type(e).__name__)
            return R.failed(API_DOWN)

    def lyrics(self, title: str, artist: str) -> dict:
        try:
            tid = self.track_id(title, artist)
            if not tid:
                return R.failed(NOT_FOUND.replace("лайк поставьте", "текст посмотрите"))
            tl = self._c().tracks_lyrics(tid.split(":")[0], format_="TEXT")
            text = (tl.fetch_lyrics() if tl else "") or ""
        except Exception as e:  # noqa: BLE001
            log.info("[yandex] текст: %s", type(e).__name__)
            return R.unsupported("У этой песни в Яндекс.Музыке нет текста")
        return R.done("текст песни", lyrics=text[:6000]) if text.strip() else \
            R.unsupported("У этой песни в Яндекс.Музыке нет текста")

    def queue(self, limit: int = 30) -> dict:
        """Очередь, которую Яндекс синхронизирует между устройствами: [{title, artist, current}]."""
        try:
            c = self._c()
            items = c.queues_list() or []
            if not items:
                return R.noop("Очередь пуста — включите что-нибудь в Яндекс.Музыке")
            q = c.queue(items[0].id)
            ids = list(getattr(q, "tracks", None) or [])
            cur = getattr(q, "current_index", None) or 0
            start = max(0, cur - 2)
            window = ids[start:start + limit]
            tracks = c.tracks([f"{t.track_id}:{t.album_id}" if t.album_id else str(t.track_id) for t in window]) or []
        except Exception as e:  # noqa: BLE001
            log.info("[yandex] очередь: %s", type(e).__name__)
            return R.failed(API_DOWN)
        rows = [{"title": t.title or "", "artist": ", ".join(a.name for a in (t.artists or []) if a.name),
                 "current": start + i == cur} for i, t in enumerate(tracks)]
        return R.done(f"в очереди {len(ids)}", queue=rows)

    def dislike(self, title: str, artist: str) -> dict:
        try:
            tid = self.track_id(title, artist)
            if not tid:
                return R.failed(NOT_FOUND)
            ok = self._c().users_dislikes_tracks_add(tid, user_id=self._uid())
            if ok:
                self._refresh_liked(force=True)  # дизлайк снимает лайк
            return R.done("дизлайк: трек больше не попадётся в «Моей волне»") if ok else \
                R.failed("Яндекс.Музыка не приняла дизлайк — попробуйте ещё раз")
        except Exception as e:  # noqa: BLE001
            log.warning("[yandex] дизлайк: %s", type(e).__name__)
            return R.failed(API_DOWN)
