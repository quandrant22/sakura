"""desktop.core.media.autoplay — «включи музыку»: запустить Яндекс.Музыку и начать воспроизведение.

music.autoplay, target: wave | liked | playlist_of_day | last | any (по умолчанию wave).
  a) уже играет (SMTC Playing) — noop «уже играет»;
  b) не запущена — запуск с параметрами (app_launch); запущена без ключа доступности и не играет —
     перезапуск с ключом (без вопроса; выбор «всегда» — настройка music_accessibility);
  c) ожидание окна и сессии — до WAIT_APP_S;
  d) лестница, успех — Playing за PLAY_CHECK_S:
     1) SMTC TryPlayAsync (только last/any и только если сессия есть: волну SMTC не выбирает);
     2) диплинки yandexmusic:// — по диагностике (CONTROL.md) воспроизведение не запускают, не используются;
     3) UI Automation: wave — ссылка «Моя волна» + первая «Воспроизведение» в основной области;
        liked — ссылка «Плейлист Мне нравится» + то же; last/any — «Воспроизведение» в панели плеера;
     4) иначе failed «приложение открыто, но воспроизведение не началось: нажми «Моя волна»».
  e) повтор за IDEMPOTENT_S — без второго запуска.
liked и playlist_of_day — только с токеном; playlist_of_day — пока unsupported (нет подтверждённого способа
открыть его в приложении). Зависимости подменяются в тестах (Deps).
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from desktop.core import results as R

log = logging.getLogger("sakura.music")

TARGETS = ("wave", "liked", "playlist_of_day", "last", "any")
WAIT_APP_S = 15.0
PLAY_CHECK_S = 5.0
IDEMPOTENT_S = 10.0
DONE_TEXT = {"wave": "включила «Мою волну»", "liked": "включила любимые треки"}
FAIL_TEXT = "приложение открыто, но воспроизведение не началось: нажми «Моя волна»"


@dataclass
class Deps:
    status: object          # async () → "playing" | "paused" | "stopped" | None (нет сессии)
    smtc_play: object       # async () → bool
    app_state: object       # () → {"running", "with_flag", "a11y"}
    launch: object          # () → dict (results)
    restart: object         # () → dict
    ui: object              # play_bar() / open_link(name) / play_main() → bool
    has_token: object       # () → bool
    window_ready: object    # () → bool (окно приложения видно UI Automation)
    sleep: object = asyncio.sleep
    clock: object = time.monotonic


def _default_deps() -> Deps:
    from desktop.core import app_launch, music
    from desktop.core.media.ym_ui import YmWindowButtons

    launcher = app_launch.AppLauncher()
    ui = YmWindowButtons()

    async def status():
        s = await music._session()
        if s is None:
            return None
        return {4: "playing", 5: "paused", 3: "stopped"}.get(int(s.get_playback_info().playback_status), "stopped")

    async def smtc_play():
        s = await music._session()
        return bool(s) and bool(await s.try_play_async())

    def has_token():
        from desktop.core import config
        return bool(config.YANDEX_MUSIC_TOKEN.strip())

    return Deps(status=status, smtc_play=smtc_play, app_state=lambda: launcher.state("yandex_music"),
                launch=lambda: launcher.launch("yandex_music"), restart=lambda: launcher.restart("yandex_music"),
                ui=ui, has_token=has_token, window_ready=lambda: ui._window() is not None)


class Autoplay:
    def __init__(self, deps: Deps | None = None):
        self._deps = deps
        self._last: tuple[float, dict] | None = None

    @property
    def d(self) -> Deps:
        if self._deps is None:
            self._deps = _default_deps()
        return self._deps

    async def _playing_within(self, seconds: float) -> bool:
        d = self.d
        end = d.clock() + seconds
        while True:
            if await d.status() == "playing":
                return True
            if d.clock() >= end:
                return False
            await d.sleep(0.25)

    async def run(self, target: str = "wave") -> dict:
        d = self.d
        target = (target or "wave").strip().lower()
        if target not in TARGETS:
            return R.failed(f"что включить: {', '.join(TARGETS)}")
        if target in ("liked", "playlist_of_day") and not d.has_token():
            return R.unsupported("Для «любимых» и «плейлиста дня» нужен YANDEX_MUSIC_TOKEN — "
                                 "включаю только «Мою волну»")
        if target == "playlist_of_day":
            return R.unsupported("«Плейлист дня» пока не умею открыть в приложении — скажи «включи мою волну»")
        now = d.clock()
        if self._last and now - self._last[0] < IDEMPOTENT_S:
            return R.noop("уже включаю музыку")
        t0 = now
        marks: list[str] = []

        def mark(stage: str):
            marks.append(f"{stage} {int((d.clock() - t0) * 1000)} мс")

        if await d.status() == "playing":
            return R.noop("уже играет")
        self._last = (now, {})
        try:
            res = await self._start(target, mark)
        finally:
            log.info("[music] autoplay %s: %s", target, "; ".join(marks) or "—")
        self._last = (d.clock(), res)
        return res

    async def _start(self, target: str, mark) -> dict:
        d = self.d
        st = await asyncio.to_thread(d.app_state)
        if not st.get("running"):
            r = await asyncio.to_thread(d.launch)
            mark("запуск")
            if r.get("status") not in ("done", "noop"):
                return r
        elif not st.get("with_flag") and await d.status() != "playing":
            r = await asyncio.to_thread(d.restart)
            mark("перезапуск с ключом")
            if not r.get("ok"):
                log.info("[music] autoplay: перезапуск не удался — %s", r.get("detail"))
        # c) окно приложения
        end = d.clock() + WAIT_APP_S
        while not await asyncio.to_thread(d.window_ready):
            if d.clock() >= end:
                return R.failed("Яндекс.Музыка не открылась за 15 с")
            await d.sleep(0.5)
        mark("окно")
        # d1) SMTC — только «продолжить» (last/any) и при живой сессии
        if target in ("last", "any") and await d.status() is not None:
            if await d.smtc_play() and await self._playing_within(PLAY_CHECK_S):
                mark("SMTC")
                return R.done("включила музыку")
        # d3) UI Automation
        steps = {"wave": [("open_link", "Моя волна"), ("play_main", None)],
                 "liked": [("open_link", "Плейлист Мне нравится"), ("play_main", None)],
                 "last": [("play_bar", None)],
                 "any": [("play_bar", None)]}[target]
        for _attempt in range(2):  # окно могло ещё дорисовываться
            ok = True
            for fn, arg in steps:
                done = await asyncio.to_thread(getattr(d.ui, fn), *([arg] if arg else []))
                ok = ok and bool(done)
                if fn == "open_link" and done:
                    await d.sleep(1.5)
            if ok and await self._playing_within(PLAY_CHECK_S):
                mark("UI Automation")
                return R.done(DONE_TEXT.get(target, "включила музыку"))
            await d.sleep(1.0)
        if target == "any":
            r = await self._start("wave", mark)
            if r.get("ok"):
                return r
        mark("не началось")
        return R.failed(FAIL_TEXT)
