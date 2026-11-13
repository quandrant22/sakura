"""desktop.core.game_director — Сакура в играх: от «заметила игру» до «итоги сессии».

Раз в WATCH_S проверяет активное окно (game_detect). Игра началась → сессия:
  • игровой режим включается сам (как раньше по списку), сцена держится поверх игры;
  • GameSense (desktop/core/gamesense.py — урон, вспышка, затемнение) получает уменьшенные кадры
    выбранного монитора SENSE_FPS раз в секунду — локально, без модели и без сети;
  • официальные API игр (game_integrations: CS2/Dota 2 GSI, LoL Live Client) дают точные события;
  • клип-буфер пишет последние секунды игры — победа, эйс и серия сохраняются сами (настройка);
  • смерти копит «тильт» — при серии Сакура один раз поддержит;
  • пока Сакура говорит, звук игры приглушается до DUCK_PCT и возвращается после;
  • эксклюзивный полноэкранный режим (fullscreen.py) — подсказка и починка по кнопке.
События: на сцену (всплывашка) — всегда; голосом — по уровню присутствия игры (game_presence)
через сервер (game_event → реплика в характере Сакуры). Конец сессии — game_session_end с итогами.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from desktop.core import game_presence as gp
from desktop.core.game_detect import GameInfo

log = logging.getLogger("sakura.games")

WATCH_S = 2.0
# Игра пропала из фокуса меньше чем на столько — та же сессия (Alt+Tab в браузер и обратно).
GRACE_S = 90.0
SENSE_FPS = 6.0
CLIP_FPS = 8.0
CLIP_WIDTH = 960
DUCK_PCT = 40
AUTOCLIP_EVENTS = frozenset({"victory", "ace", "multikill"})
SPEAK_TEXT = {
    "death": "смерть", "kill": "убийство", "multikill": "серия убийств", "ace": "эйс", "victory": "победа",
    "defeat": "поражение", "round_win": "выиграли раунд", "round_loss": "проиграли раунд",
    "bomb_planted": "бомба заложена", "objective": "взяли цель", "low_hp": "мало здоровья", "hurt": "получил урон",
    "flash": "яркая вспышка", "dark": "экран потемнел", "tilt": "серия смертей подряд", "achievement": "достижение",
}


@dataclass
class Session:
    game: GameInfo
    started: float
    level: str
    last_seen: float
    stats: dict = field(default_factory=lambda: {"kills": 0, "deaths": 0, "wins": 0, "losses": 0, "clips": 0})
    highlights: list = field(default_factory=list)
    gate: gp.SpeechGate = field(default_factory=gp.SpeechGate)
    tilt: gp.TiltMeter = field(default_factory=gp.TiltMeter)
    exclusive_warned: bool = False

    def minutes(self, now: float) -> int:
        return max(0, int((now - self.started) // 60))


class GameDirector:
    def __init__(self, settings, *, emit: Callable[[dict], None], send_server: Callable[[dict], None],
                 bus=None, platform=None, clips=None, detect=None, clock=time.monotonic):
        self.settings = settings
        self.emit = emit
        self.send_server = send_server
        self.bus = bus
        self._platform = platform
        self.clips = clips
        self._detect = detect
        self.clock = clock
        self.session: Optional[Session] = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._ducked: Optional[int] = None
        self._lock = threading.Lock()
        self._gsi = None
        self._lol = None
        self._sense = None

    # ── настройки ──
    def _get(self, key: str, default: Any = None) -> Any:
        try:
            v = self.settings.get(key, default)
        except Exception:  # noqa: BLE001
            return default
        return default if v is None else v

    def level_for(self, game: GameInfo) -> str:
        per_game = self._get("game_presence", {}) or {}
        return gp.level_for(game.key, per_game, self._get("game_presence_default", gp.DEFAULT_LEVEL))

    @property
    def platform(self):
        if self._platform is None:
            from desktop.core.platform import get_platform
            self._platform = get_platform()
        return self._platform

    # ── запуск ──
    def start(self):
        if self.bus is not None:
            self.bus.subscribe(self._on_bus)
        self._start_integrations()
        t = threading.Thread(target=self._watch_loop, name="game-watch", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self):
        self._stop.set()
        if self._gsi:
            self._gsi.stop()
        if self._lol:
            self._lol.stop()

    def _start_integrations(self):
        try:
            from desktop.core.game_integrations import GsiServer, LolPoller
            token = str(self._get("gsi_token", "") or "")
            self._gsi = GsiServer(self.on_api_event, token=token or None)
            if not token:
                try:
                    self.settings.set("gsi_token", self._gsi.token)
                except Exception:  # noqa: BLE001
                    pass
            self._gsi.start()
            self._lol = LolPoller(self.on_api_event)
        except Exception:  # noqa: BLE001
            log.exception("[games] игровые API не запущены")

    @property
    def gsi_token(self) -> str:
        return self._gsi.token if self._gsi else ""

    # ── слежение за активным окном ──
    def _watch_loop(self):
        while not self._stop.wait(WATCH_S):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("[games] слежение")

    def detect(self) -> tuple[Optional[GameInfo], Optional[dict]]:
        if self._detect is not None:
            return self._detect()
        from desktop.core.game_detect import foreground_game
        return foreground_game(self._get("game_processes", []) or [], self._get("game_not_processes", []) or [])

    def tick(self):
        now = self.clock()
        game, fg = self.detect()
        with self._lock:
            s = self.session
        if game is not None:
            if s is None or s.game.key != game.key:
                if s is not None:
                    self.end_session("другая игра")
                self.begin_session(game, fg)
            else:
                s.last_seen = now
                self._check_exclusive(s, fg)
        elif s is not None and now - s.last_seen > GRACE_S:
            self.end_session("игра закрыта")

    # ── сессия ──
    def begin_session(self, game: GameInfo, fg: Optional[dict] = None):
        now = self.clock()
        level = self.level_for(game)
        s = Session(game=game, started=now, level=level, last_seen=now)
        with self._lock:
            self.session = s
        log.info("[games] сессия: %s (%s), присутствие %s", game.name, game.reason, level)
        if self.bus is not None:
            self.bus.emit("game_mode", on=True)
        self.emit({"type": "game_session", "state": "start", "game": game.name, "key": game.key, "level": level,
                   "reason": game.reason})
        self.emit({"type": "game_event", "event": "session_start", "title": game.name,
                   "text": f"Я рядом · {gp.LEVEL_NAMES[level]}"})
        if game.key in ("league of legends.exe",) and self._lol:
            self._lol.start()
        if level != "silent" or self._get("game_autoclip", True):
            self._start_sense(s)
        self._send("game_session_start", s, {"reason": game.reason})
        self._check_exclusive(s, fg)

    def end_session(self, why: str = ""):
        with self._lock:
            s, self.session = self.session, None
        if s is None:
            return
        self._sense = None  # цикл кадров сам увидит, что сессии нет
        if self._lol:
            self._lol.stop()
        self._unduck(s)
        now = self.clock()
        log.info("[games] конец сессии %s (%s): %d мин, %s", s.game.name, why, s.minutes(now), s.stats)
        if self.bus is not None:
            self.bus.emit("game_mode", on=False)
        self.emit({"type": "game_session", "state": "end", "game": s.game.name, "key": s.game.key,
                   "minutes": s.minutes(now), "stats": dict(s.stats), "highlights": list(s.highlights[-10:])})
        if s.minutes(now) >= 5:
            self._send("game_session_end", s, {"minutes": s.minutes(now), "highlights": s.highlights[-10:],
                                               "speak": s.level != "silent"})

    def set_level(self, key: str, level: str) -> str:
        """Уровень присутствия для игры (голосом «в Доте комментируй» или в настройках)."""
        level = gp.normalize(level)
        per = dict(self._get("game_presence", {}) or {})
        per[key] = level
        self.settings.set("game_presence", per)
        with self._lock:
            s = self.session
        if s is not None and s.game.key == key:
            s.level = level
            if self._sense is None and level != "silent":
                self._start_sense(s)
        return level

    # ── события ──
    def on_api_event(self, source: str, kind: str, detail: str = ""):
        self.on_event(kind, detail, source=source)

    def on_event(self, kind: str, detail: str = "", source: str = "sense"):
        with self._lock:
            s = self.session
        if s is None:
            return
        now = self.clock()
        if kind == "kill":
            s.stats["kills"] += 1
        elif kind in ("multikill", "ace"):
            s.stats["kills"] += 1
            s.highlights.append(f"{SPEAK_TEXT.get(kind, kind)} {detail}".strip())
        elif kind == "death":
            s.stats["deaths"] += 1
            if s.tilt.death(now):
                self.on_event("tilt", f"{s.tilt.threshold}+ смертей за 10 минут", source="director")
        elif kind == "victory":
            s.stats["wins"] += 1
            s.tilt.win()
            s.highlights.append(f"победа {detail}".strip())
        elif kind == "defeat":
            s.stats["losses"] += 1
        # Затемнение экрана GameSense — ещё не смерть: катсцены и загрузки тоже тёмные.
        self.emit({"type": "game_event", "event": kind, "text": detail or "", "source": source})
        if kind in AUTOCLIP_EVENTS and self._get("game_autoclip", True):
            threading.Thread(target=self._autoclip, args=(s, kind), daemon=True).start()
        if s.gate.should_speak(s.level, kind, now):
            self._send("game_event", s, {"event": kind, "event_text": SPEAK_TEXT.get(kind, kind), "detail": detail,
                                         "source": source})

    def _send(self, kind: str, s: Session, extra: dict):
        msg = {"type": kind, "game": s.game.name, "game_key": s.game.key, "level": s.level,
               "minutes": s.minutes(self.clock()), "stats": dict(s.stats), **extra}
        try:
            self.send_server(msg)
        except Exception:  # noqa: BLE001
            log.debug("[games] сервер недоступен для %s", kind)

    def _autoclip(self, s: Session, kind: str):
        if self.clips is None:
            return
        try:
            path = self.clips.save_clip(20)
        except Exception:  # noqa: BLE001
            path = None
        if path:
            s.stats["clips"] += 1
            self.emit({"type": "game_event", "event": "clip_saved",
                       "text": f"{SPEAK_TEXT.get(kind, kind)} · {path.name}", "path": str(path)})

    # ── кадры: GameSense + клип-буфер ──
    def _start_sense(self, s: Session):
        token = object()
        self._sense = token
        threading.Thread(target=self._sense_loop, args=(s, token), name="game-sense", daemon=True).start()

    def _sense_loop(self, s: Session, token: object):
        try:
            from desktop.core.gamesense import GameSenseDetector
            from desktop.core.screens import FastGrabber
        except Exception:  # noqa: BLE001
            return
        grabber = FastGrabber()
        detector = GameSenseDetector(on_event=lambda ev: self.on_event(ev.kind, "", source="sense"))
        clip_every = 1.0 / CLIP_FPS
        sense_every = 1.0 / SENSE_FPS
        last_clip = last_sense = 0.0
        log.info("[games] кадры: %s", grabber.backend)
        try:
            while not self._stop.is_set() and self._sense is token and self.session is s:
                t = time.monotonic()
                want_clip = self.clips is not None and self._get("game_autoclip", True) and t - last_clip >= clip_every
                want_sense = s.level != "silent" and t - last_sense >= sense_every
                if want_clip or want_sense:
                    img = grabber.grab()
                    if want_sense:
                        small = img.convert("RGB").resize((160, 90))
                        detector.feed_frame(small.convert("RGBA").tobytes("raw", "BGRA"), 160, 90)
                        last_sense = t
                    if want_clip:
                        self._clip_frame(img)
                        last_clip = t
                time.sleep(max(0.01, min(clip_every, sense_every) - (time.monotonic() - t)))
        except Exception:  # noqa: BLE001
            log.exception("[games] цикл кадров остановлен")
        finally:
            grabber.close()

    def _clip_frame(self, img):
        w, h = img.size
        if w > CLIP_WIDTH:
            img = img.resize((CLIP_WIDTH, max(1, int(h * CLIP_WIDTH / w))))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        self.clips.add_frame(buf.getvalue())

    # ── приглушение игры, пока Сакура говорит ──
    def _on_bus(self, event: str, data: dict):
        if event != "state":
            return
        with self._lock:
            s = self.session
        if s is None or not self._get("game_duck", True):
            return
        if data.get("value") == "speaking":
            self._duck(s)
        elif data.get("value") in ("idle", "listening"):
            self._unduck(s)

    def _duck(self, s: Session):
        if self._ducked is not None:
            return
        try:
            cur = self.platform.app_volume_get((s.game.exe.rsplit(".", 1)[0].lower(),))
            if cur is not None and cur > DUCK_PCT:
                self.platform.app_volume_set((s.game.exe.rsplit(".", 1)[0].lower(),), DUCK_PCT)
                self._ducked = cur
        except Exception:  # noqa: BLE001
            pass

    def _unduck(self, s: Session):
        if self._ducked is None:
            return
        try:
            self.platform.app_volume_set((s.game.exe.rsplit(".", 1)[0].lower(),), self._ducked)
        except Exception:  # noqa: BLE001
            pass
        self._ducked = None

    # ── эксклюзивный полноэкранный режим ──
    def _check_exclusive(self, s: Session, fg: Optional[dict]):
        if s.exclusive_warned:
            return
        try:
            from desktop.core import fullscreen
            exclusive = fullscreen.exclusive_active()
            if not exclusive:
                return
            adv = fullscreen.advice(s.game.path, True)
        except Exception:  # noqa: BLE001
            return
        s.exclusive_warned = True
        log.info("[games] %s — эксклюзивный полноэкранный режим (%s)", s.game.name, adv.get("fix"))
        self.emit({"type": "fullscreen_hint", "game": s.game.name, "key": s.game.key, "path": s.game.path, **adv})
        self.emit({"type": "notify", "text": adv["text"], "level": "warn"})
        # Поверх эксклюзивной игры всплывашку не видно — совет голосом (один раз за сессию, кроме «Молчит»).
        if s.level != "silent":
            self._send("game_event", s, {"event": "fullscreen_blocked", "say": adv["text"]})

    def snapshot(self) -> dict:
        with self._lock:
            s = self.session
        if s is None:
            return {"active": False}
        return {"active": True, "game": s.game.name, "key": s.game.key, "level": s.level, "reason": s.game.reason,
                "minutes": s.minutes(self.clock()), "stats": dict(s.stats)}
