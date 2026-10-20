"""desktop.core.media.yandex_remote — пульт приложения Яндекс.Музыки (режим remote, по умолчанию).

Всё через Windows SMTC (desktop.core.music) и громкость сессии приложения (платформа), без
клавиш в чужие окна. Лайк, дизлайк и текст песни — только с YANDEX_MUSIC_TOKEN (API); без
токена кнопки неактивны с подсказкой. Бэкенды подменяются в тестах.

state() — снимок для панели: готовое состояние наблюдателя SMTC (smtc_watch, с seq), SMTC заново
не читается; громкость — в потоке, с кэшем VOLUME_TTL_S; лайк — из кэша (его в фоне после смены трека
обновляет liked_for → событие music_like); обложки в ответе нет — только событием music_cover.
control(op, value) — {ok, status, detail}. Системные вызовы (громкость, UI Automation, psutil) — в потоке.
"""
import asyncio
import base64
import logging
import time

from desktop.core import results as R

log = logging.getLogger("sakura.media.yandex")

APP_NAMES = ("яндекс", "yandex")
ENV_PATH = r"C:\sakura-git\agent\.env"
TOKEN_HINT = f"Нужен доступ к Яндекс.Музыке. Добавь YANDEX_MUSIC_TOKEN в {ENV_PATH} и перезапусти Сакуру"
NO_SOUND = "Звук Яндекс.Музыки не найден: включите трек — повторю через 2 с"
NO_PLAYER = "Яндекс.Музыка ничего не воспроизводит — включите трек в приложении"
SEEK_NO = "Приложение Яндекс.Музыки не даёт перематывать через Windows — перемотайте в окне приложения"
MODES_TTL_S = 10.0
VOLUME_TTL_S = 2.0
RETRY_MS = 2000
REPEAT_CYCLE = {"none": "list", "list": "track", "track": "none"}


def _default_smtc():
    from desktop.core import music
    return music


def _default_platform():
    from desktop.core.platform import get_platform
    return get_platform()


def _smtc_available() -> bool:
    try:
        import winsdk.windows.media.control  # noqa: F401
        return True
    except Exception:
        return False


def _app_running() -> bool:
    try:
        import psutil
        return any(any(n in (p.info["name"] or "").lower() for n in APP_NAMES)
                   for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def _cover_url(data: bytes | None) -> str | None:
    if not data:
        return None
    mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


_SHARED: list = []


def shared() -> "YandexRemote":
    """Пульт процесса: один кэш громкости и лайков для опроса панели и фонового лайка."""
    if not _SHARED:
        _SHARED.append(YandexRemote())
    return _SHARED[0]


def _default_watch():
    from desktop.core.media import smtc_watch
    return smtc_watch.active()


class YandexRemote:
    def __init__(self, smtc=None, platform=None, available=_smtc_available, running=_app_running,
                 token=None, open_link=None, likes=None, buttons=None, clock=time.monotonic,
                 watch=_default_watch):
        self._smtc = smtc
        self._platform = platform
        self._available = available
        self._running = running
        self._token = token
        self._open_link = open_link
        self._likes = likes
        self._buttons = buttons
        self._clock = clock
        self._win_modes: dict = {}
        self._win_modes_at = None
        self._track = ("", "")  # (title, artist) последнего снимка — для лайка
        self._watch = watch
        self._volume: tuple[float, int | None] | None = None   # (когда, значение)
        self._liked: dict[tuple[str, str], bool | None] = {}

    @property
    def likes(self):
        if self._likes is None:
            from desktop.core.media.ym_likes import YmLikes
            self._likes = YmLikes()
        return self._likes

    @property
    def buttons(self):
        if self._buttons is None:
            from desktop.core.media.ym_ui import YmWindowButtons
            self._buttons = YmWindowButtons()
        return self._buttons

    async def _window_modes(self) -> dict:
        """Перемешивание/повтор из кнопок окна (UI Automation) — не чаще раза в MODES_TTL_S."""
        now = self._clock()
        if self._win_modes_at is None or now - self._win_modes_at >= MODES_TTL_S:
            self._win_modes_at = now
            try:
                self._win_modes = {k: await asyncio.to_thread(self.buttons.state, k) for k in ("shuffle", "repeat")}
            except Exception:  # noqa: BLE001
                self._win_modes = {}
        return self._win_modes

    async def _press_window(self, kind: str, what: str) -> dict:
        from desktop.core.media.ym_ui import A11Y_HINT
        try:
            res = await asyncio.to_thread(self.buttons.press, kind)
        except Exception:  # noqa: BLE001
            res = "no_a11y"
        self._win_modes_at = None
        if res == "done":
            return R.done(f"{what}: нажала кнопку в окне Яндекс.Музыки")
        if res == "no_window":
            return R.unsupported(f"{what}: окно Яндекс.Музыки не найдено — откройте приложение")
        if res == "not_found":
            return R.unsupported(f"{what}: кнопка в окне Яндекс.Музыки не найдена — нажмите её в приложении")
        return R.unsupported(f"{what} недоступно. {A11Y_HINT}", help="a11y")

    @property
    def smtc(self):
        return self._smtc or _default_smtc()

    @property
    def platform(self):
        return self._platform or _default_platform()

    def has_token(self) -> bool:
        if self._token is not None:
            return bool(self._token)
        from desktop.core import config
        return bool(config.YANDEX_MUSIC_TOKEN.strip())

    async def _volume_get(self) -> int | None:
        """Громкость сессии приложения (COM) — в потоке, не чаще раза в VOLUME_TTL_S."""
        now = self._clock()
        if self._volume is None or now - self._volume[0] >= VOLUME_TTL_S:
            try:
                value = await asyncio.to_thread(self.platform.app_volume_get, APP_NAMES)
            except Exception:  # noqa: BLE001
                value = None
            self._volume = (now, value)
        return self._volume[1]

    async def _volume_set(self, percent: int) -> int | None:
        got = await asyncio.to_thread(self.platform.app_volume_set, APP_NAMES, percent)
        self._volume = (self._clock(), got)
        return got

    async def liked_for(self, title: str, artist: str) -> bool | None:
        """Сердце трека из API (в потоке) и в кэш — для фона после смены трека (событие music_like)."""
        if not self.has_token() or not title:
            return None
        liked = await asyncio.to_thread(self.likes.liked, title, artist)
        self._liked[(title, artist)] = liked
        while len(self._liked) > 64:
            self._liked.pop(next(iter(self._liked)))
        return liked

    async def _snapshot(self) -> dict | None:
        """Состояние наблюдателя SMTC; без наблюдателя (тесты, не Windows) — одно чтение и seq 0."""
        watch = self._watch() if callable(self._watch) else self._watch
        if watch is not None:
            return watch.snapshot()
        info = await self.smtc._smtc_get_info()
        if not info or not info.get("title"):
            return {"status": "idle" if await asyncio.to_thread(self._running) else "not_running", "seq": 0}
        return {"status": "ok", "seq": 0, **{k: info.get(k) for k in (
            "title", "artist", "album", "playing", "position_s", "duration_s", "updated_age_s",
            "shuffle", "repeat")}}

    async def state(self) -> dict:
        """status: ok | starting | idle (ничего не играет) | not_running | no_smtc; seq — номер снимка."""
        token = self.has_token()
        base = {"can_like": token, "like_hint": None if token else TOKEN_HINT,
                "can_lyrics": token, "volume": None, "liked": None}
        if not self._available():
            return {**base, "status": "no_smtc"}
        snap = await self._snapshot()
        base["volume"] = await self._volume_get()
        if snap is None:  # наблюдатель ещё не прочитал SMTC
            return {**base, "status": "starting", "seq": 0}
        if snap.get("status") != "ok":
            return {**base, "status": snap.get("status"), "seq": snap.get("seq", 0)}
        modes = {"shuffle": snap.get("shuffle"), "repeat": snap.get("repeat")}
        if modes["shuffle"] is None and modes["repeat"] is None:
            win = await self._window_modes()
            modes = {"shuffle": win.get("shuffle"),
                     "repeat": None if win.get("repeat") is None else ("list" if win["repeat"] else "none")}
        self._track = (snap.get("title", ""), snap.get("artist", ""))
        if token:
            base["liked"] = self._liked.get(self._track)
        return {**base, "status": "ok", "seq": snap.get("seq", 0), "track_seq": snap.get("track_seq"),
                "title": snap.get("title", ""), "artist": snap.get("artist", ""), "album": snap.get("album", ""),
                "playing": bool(snap.get("playing")),
                "position_s": snap.get("position_s"), "duration_s": snap.get("duration_s"),
                "updated_age_s": snap.get("updated_age_s"),
                "shuffle": modes.get("shuffle"), "repeat": modes.get("repeat")}

    async def control(self, op: str, value=None) -> dict:
        s = self.smtc
        if op == "play_pause":
            ok = await s._smtc_control("play_pause")
            return R.done("пауза/воспроизведение") if ok else R.noop(NO_PLAYER)
        if op == "next":
            return R.done("следующий трек") if await s._smtc_control("next") else R.noop(NO_PLAYER)
        if op == "prev":
            return await s.smart_prev()
        if op == "restart":
            return await s.restart_track()
        if op == "seek":
            return R.done("перемотка") if await s.smtc_set_position(float(value or 0)) else R.unsupported(SEEK_NO)
        if op == "seek_by":
            pos = await s.smtc_position()
            if pos is None:
                return R.noop(NO_PLAYER)
            target = max(0.0, pos + float(value or 0))
            if await s.smtc_set_position(target):
                return R.done(f"перемотка {'вперёд' if float(value or 0) > 0 else 'назад'}")
            return R.unsupported(SEEK_NO)
        if op == "podcasts":
            from desktop.core import config
            uid = getattr(config, "YANDEX_UID", "") or ""
            if not uid:
                return R.unsupported(f"Для подкастов нужен YANDEX_UID: добавь его в {ENV_PATH} и перезапусти Сакуру")
            opener = self._open_link or (lambda url: self.platform.open_path(url))
            ok = opener(f"https://music.yandex.ru/users/{uid}/podcast-subscriptions")
            return R.done("открыла подкасты") if ok else R.failed("Не удалось открыть подкасты в браузере")
        # Сначала SMTC; приложение его не поддерживает — кнопка окна (UI Automation); иначе честный отказ.
        if op == "shuffle":
            modes = await s.smtc_modes()
            on = (not modes.get("shuffle")) if value is None else bool(value)
            if await s.smtc_set_shuffle(on):
                return R.done("перемешивание включено" if on else "перемешивание выключено")
            return await self._press_window("shuffle", "Перемешивание")
        if op == "repeat":
            modes = await s.smtc_modes()
            mode = value if value in REPEAT_CYCLE else REPEAT_CYCLE.get(modes.get("repeat") or "none", "list")
            if await s.smtc_set_repeat(mode):
                return R.done(f"повтор: {mode}")
            return await self._press_window("repeat", "Повтор")
        if op in ("volume", "volume_by"):
            cur = await asyncio.to_thread(self.platform.app_volume_get, APP_NAMES)
            if cur is None:
                return R.noop(NO_SOUND, retry_ms=RETRY_MS)
            target = int(value) if op == "volume" else cur + int(value or 0)
            got = await self._volume_set(target)
            return R.done(f"громкость Яндекс.Музыки {got}%", volume=got) if got is not None else \
                R.noop(NO_SOUND, retry_ms=RETRY_MS)
        if op == "mute":
            cur = await asyncio.to_thread(self.platform.app_volume_get, APP_NAMES)
            if cur is None:
                return R.noop(NO_SOUND, retry_ms=RETRY_MS)
            got = await self._volume_set(0 if cur > 0 else int(value or 50))
            return R.done("звук Яндекс.Музыки выключен" if got == 0 else f"звук Яндекс.Музыки {got}%")
        if op in ("like", "dislike", "lyrics", "queue"):
            if not self.has_token():
                return R.unsupported(TOKEN_HINT, help="token")
            if op == "queue":
                return await asyncio.to_thread(self.likes.queue)
            title, artist = self._track
            if not title:
                info = await s._smtc_get_info() or {}
                title, artist = info.get("title", ""), info.get("artist", "")
            if not title:
                return R.noop(NO_PLAYER)
            if op == "like":
                res = await asyncio.to_thread(self.likes.toggle_like, title, artist)
                if "liked" in res:
                    self._liked[(title, artist)] = res["liked"]
                return res
            if op == "dislike":
                return await asyncio.to_thread(self.likes.dislike, title, artist)
            return await asyncio.to_thread(self.likes.lyrics, title, artist)
        if op == "open_app":
            opener = self._open_link or (lambda url: self.platform.open_path(url))
            if opener("yandexmusic://"):
                return R.done("открыла Яндекс.Музыку")
            return R.failed("Не удалось открыть Яндекс.Музыку — запустите приложение из меню «Пуск»")
        return R.unsupported(f"неизвестная операция: {op}")
