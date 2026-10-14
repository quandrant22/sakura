"""desktop.core.media.yandex_remote — пульт приложения Яндекс.Музыки (режим remote, по умолчанию).

Всё через Windows SMTC (desktop.core.music) и громкость сессии приложения (платформа), без
клавиш в чужие окна. Лайк, дизлайк и текст песни — только с YANDEX_MUSIC_TOKEN (API); без
токена кнопки неактивны с подсказкой. Бэкенды подменяются в тестах.

state() — снимок для панели; control(op, value) — {ok, status, detail}.
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


class YandexRemote:
    def __init__(self, smtc=None, platform=None, available=_smtc_available, running=_app_running,
                 token=None, open_link=None, likes=None, buttons=None, clock=time.monotonic):
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

    async def state(self) -> dict:
        """status: ok | idle (ничего не играет) | not_running | no_smtc."""
        token = self.has_token()
        base = {"can_like": token, "like_hint": None if token else TOKEN_HINT,
                "can_lyrics": token, "volume": None, "liked": None}
        if not self._available():
            return {**base, "status": "no_smtc"}
        info = await self.smtc._smtc_get_info()
        try:
            base["volume"] = self.platform.app_volume_get(APP_NAMES)
        except Exception:
            base["volume"] = None
        if not info or not info.get("title"):
            return {**base, "status": "idle" if self._running() else "not_running"}
        modes = await self.smtc.smtc_modes()
        if modes.get("shuffle") is None and modes.get("repeat") is None:
            win = await self._window_modes()
            modes = {"shuffle": win.get("shuffle"),
                     "repeat": None if win.get("repeat") is None else ("list" if win["repeat"] else "none")}
        cover = await self.smtc.smtc_cover()
        self._track = (info.get("title", ""), info.get("artist", ""))
        if token:
            base["liked"] = await asyncio.to_thread(self.likes.liked, *self._track)
        return {**base, "status": "ok",
                "title": info.get("title", ""), "artist": info.get("artist", ""), "album": info.get("album", ""),
                "playing": bool(info.get("playing")),
                "position_s": info.get("position_s"), "duration_s": info.get("duration_s"),
                "updated_age_s": info.get("updated_age_s"),
                "shuffle": modes.get("shuffle"), "repeat": modes.get("repeat"),
                "cover": _cover_url(cover)}

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
            cur = self.platform.app_volume_get(APP_NAMES)
            if cur is None:
                return R.noop(NO_SOUND, retry_ms=RETRY_MS)
            target = int(value) if op == "volume" else cur + int(value or 0)
            got = self.platform.app_volume_set(APP_NAMES, target)
            return R.done(f"громкость Яндекс.Музыки {got}%", volume=got) if got is not None else \
                R.noop(NO_SOUND, retry_ms=RETRY_MS)
        if op == "mute":
            cur = self.platform.app_volume_get(APP_NAMES)
            if cur is None:
                return R.noop(NO_SOUND, retry_ms=RETRY_MS)
            got = self.platform.app_volume_set(APP_NAMES, 0 if cur > 0 else int(value or 50))
            return R.done("звук Яндекс.Музыки выключен" if got == 0 else f"звук Яндекс.Музыки {got}%")
        if op in ("like", "dislike", "lyrics"):
            if not self.has_token():
                return R.unsupported(TOKEN_HINT, help="token")
            title, artist = self._track
            if not title:
                info = await s._smtc_get_info() or {}
                title, artist = info.get("title", ""), info.get("artist", "")
            if not title:
                return R.noop(NO_PLAYER)
            if op == "like":
                return await asyncio.to_thread(self.likes.toggle_like, title, artist)
            if op == "dislike":
                return await asyncio.to_thread(self.likes.dislike, title, artist)
            return await asyncio.to_thread(self.likes.lyrics, title, artist)
        if op == "open_app":
            opener = self._open_link or (lambda url: self.platform.open_path(url))
            if opener("yandexmusic://"):
                return R.done("открыла Яндекс.Музыку")
            return R.failed("Не удалось открыть Яндекс.Музыку — запустите приложение из меню «Пуск»")
        return R.unsupported(f"неизвестная операция: {op}")
