"""desktop.core.media.smtc_watch — мгновенное определение трека Яндекс.Музыки по событиям SMTC.

Подписка: SessionsChanged, CurrentSessionChanged и у сессии Яндекс.Музыки MediaPropertiesChanged,
PlaybackInfoChanged, TimelinePropertiesChanged. События приходят в поток WinRT — переносятся в цикл
asyncio, пачка событий схлопывается в одно чтение (DEBOUNCE_S). Опрос раз в секунду — только сторож
на случай пропущенного события. Цель: смена трека в панели ≤ 300 мс (p95 ≤ 500 мс).

Состояния (оптимистичные): ok — есть сессия; starting — процесс есть, сессии ещё нет («Запускается…»);
нет сессии — только если процесса нет или сессия пропала больше LOST_S назад (до того держим прошлое).
Повтор трека — та же пара (artist, title), позиция упала к началу (restarted).
"""
import asyncio
import logging
import time

log = logging.getLogger("sakura.music")

DEBOUNCE_S = 0.03
WATCHDOG_S = 1.0
LOST_S = 3.0


def track_key(info: dict) -> tuple:
    return (info.get("artist", ""), info.get("title", ""), info.get("album", ""))


class TrackState:
    """Чистая логика: из снимков SMTC — изменения для панели (тестируется без WinRT)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last: dict | None = None
        self.lost_at: float | None = None
        self.seq = 0

    def update(self, info: dict | None, process_running: bool) -> dict | None:
        """Новое состояние для окна или None (ничего не изменилось)."""
        now = self.clock()
        if not info or not info.get("title"):
            if process_running and self.last and self.last.get("status") == "ok":
                if self.lost_at is None:
                    self.lost_at = now
                if now - self.lost_at < LOST_S:
                    return None  # сессия мигнула — держим прошлое состояние
            status = "starting" if process_running else "not_running"
            if self.last and self.last.get("status") == status:
                return None
            self.lost_at = None
            return self._emit({"status": status})
        self.lost_at = None
        st = {"status": "ok", "title": info.get("title", ""), "artist": info.get("artist", ""),
              "album": info.get("album", ""), "playing": bool(info.get("playing")),
              "position_s": info.get("position_s"), "duration_s": info.get("duration_s"),
              "updated_age_s": info.get("updated_age_s")}
        prev = self.last or {}
        same_track = prev.get("status") == "ok" and track_key(prev) == track_key(st)
        restarted = bool(same_track and (prev.get("position_s") or 0) > 5 and (st.get("position_s") or 0) < 2)
        if same_track and not restarted and prev.get("playing") == st["playing"] \
                and abs((prev.get("position_s") or 0) - (st.get("position_s") or 0)) < 3 \
                and prev.get("duration_s") == st.get("duration_s"):
            self.last = {**prev, **st}
            return None
        st["changed"] = "restart" if restarted else ("track" if not same_track else "playback")
        return self._emit(st)

    def _emit(self, st: dict) -> dict:
        self.seq += 1
        st["seq"] = self.seq
        self.last = st
        return st


class SmtcWatch:
    """Подписка на события SMTC; on_change(state, t_event) вызывается в цикле asyncio."""

    def __init__(self, on_change, read_info=None, process_running=None, clock=time.monotonic):
        self.on_change = on_change
        self.clock = clock
        self.state = TrackState(clock)
        self._read = read_info
        self._running = process_running
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mgr = None
        self._session = None
        self._tokens: list = []
        self._pending: float | None = None
        self._task: asyncio.Task | None = None

    async def start(self):
        self._loop = asyncio.get_running_loop()
        if self._read is None:
            from desktop.core import music
            self._read = music._smtc_get_info
        if self._running is None:
            from desktop.core.media.yandex_remote import _app_running
            self._running = _app_running
        try:
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            self._mgr = await M.request_async()
            self._mgr.add_sessions_changed(lambda *_: self._event())
            self._mgr.add_current_session_changed(lambda *_: self._event())
            self._bind()
        except Exception as e:  # noqa: BLE001
            log.info("[music] события SMTC недоступны (%s) — только сторож", type(e).__name__)
        self._event()
        asyncio.ensure_future(self._watchdog())

    def _bind(self):
        from desktop.core.music import _pick_yamusic_session
        s = _pick_yamusic_session(self._mgr) if self._mgr else None
        if s is None or s is self._session:
            return
        self._session = s
        cb = lambda *_: self._event()  # noqa: E731
        s.add_media_properties_changed(cb)
        s.add_playback_info_changed(cb)
        s.add_timeline_properties_changed(cb)

    def _event(self):
        """Вызывается из потока WinRT — переносим в цикл."""
        t = self.clock()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._schedule, t)

    def _schedule(self, t_event: float):
        if self._pending is None or t_event < self._pending:
            self._pending = t_event
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._refresh())

    async def _refresh(self):
        await asyncio.sleep(DEBOUNCE_S)
        t_event, self._pending = self._pending, None
        try:
            self._bind()
        except Exception:  # noqa: BLE001
            pass
        info = await self._read()
        running = await asyncio.to_thread(self._running) if not info else True
        st = self.state.update(info, running)
        if st is not None:
            self.on_change(st, t_event)

    async def _watchdog(self):
        while True:
            await asyncio.sleep(WATCHDOG_S)
            if self._task is None or self._task.done():
                self._pending = None
                self._task = asyncio.ensure_future(self._refresh())
