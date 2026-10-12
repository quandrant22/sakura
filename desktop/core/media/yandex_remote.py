"""desktop.core.media.yandex_remote — пульт приложения Яндекс.Музыки (режим remote, по умолчанию).

Всё через Windows SMTC (desktop.core.music) и громкость сессии приложения (платформа), без
клавиш в чужие окна. Лайк, дизлайк и текст песни — только с YANDEX_MUSIC_TOKEN (API); без
токена кнопки неактивны с подсказкой. Бэкенды подменяются в тестах.

state() — снимок для панели; control(op, value) — {ok, status, detail}.
"""
import base64
import logging

from desktop.core import results as R

log = logging.getLogger("sakura.media.yandex")

APP_NAMES = ("яндекс", "yandex")
TOKEN_HINT = "нужен YANDEX_MUSIC_TOKEN"
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
                 token=None, open_link=None):
        self._smtc = smtc
        self._platform = platform
        self._available = available
        self._running = running
        self._token = token
        self._open_link = open_link

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
                "can_lyrics": token, "volume": None}
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
        cover = await self.smtc.smtc_cover()
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
            return R.done("пауза/воспроизведение") if ok else R.noop("Нет активного плеера")
        if op == "next":
            return R.done("следующий трек") if await s._smtc_control("next") else R.noop("Нет активного плеера")
        if op == "prev":
            return await s.smart_prev()
        if op == "restart":
            return await s.restart_track()
        if op == "seek":
            return R.done("перемотка") if await s.smtc_set_position(float(value or 0)) else \
                R.unsupported("приложение не поддерживает перемотку")
        if op == "shuffle":
            modes = await s.smtc_modes()
            on = (not modes.get("shuffle")) if value is None else bool(value)
            return R.done("перемешивание включено" if on else "перемешивание выключено") \
                if await s.smtc_set_shuffle(on) else R.unsupported("приложение не поддерживает перемешивание")
        if op == "repeat":
            modes = await s.smtc_modes()
            mode = value if value in REPEAT_CYCLE else REPEAT_CYCLE.get(modes.get("repeat") or "none", "list")
            return R.done(f"повтор: {mode}") if await s.smtc_set_repeat(mode) else \
                R.unsupported("приложение не поддерживает повтор")
        if op in ("volume", "volume_by"):
            cur = self.platform.app_volume_get(APP_NAMES)
            if cur is None:
                return R.noop("Яндекс.Музыка не воспроизводит звук")
            target = int(value) if op == "volume" else cur + int(value or 0)
            got = self.platform.app_volume_set(APP_NAMES, target)
            return R.done(f"громкость Яндекс.Музыки {got}%") if got is not None else R.failed("громкость не изменилась")
        if op == "mute":
            cur = self.platform.app_volume_get(APP_NAMES)
            if cur is None:
                return R.noop("Яндекс.Музыка не воспроизводит звук")
            got = self.platform.app_volume_set(APP_NAMES, 0 if cur > 0 else int(value or 50))
            return R.done("звук Яндекс.Музыки выключен" if got == 0 else f"звук Яндекс.Музыки {got}%")
        if op in ("like", "dislike", "lyrics"):
            if not self.has_token():
                return R.unsupported(TOKEN_HINT)
            return R.unsupported("лайк и текст в панели — через API, ещё не подключено")
        if op == "open_app":
            opener = self._open_link or (lambda url: self.platform.open_path(url))
            if opener("yandexmusic://"):
                return R.done("открыла Яндекс.Музыку")
            return R.failed("не удалось открыть Яндекс.Музыку")
        return R.unsupported(f"неизвестная операция: {op}")
