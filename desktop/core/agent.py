"""
core/agent.py — нервная система тела (Фаза 6: высокопроизводительный голос).

Изменения:
  - Бинарный приём TTS: isinstance(raw, bytes) → feed_binary()
  - Отображение буфера в ms при воспроизведении (для отладки)
  - Остальное без изменений
"""

import asyncio
import base64
import json
import os as _os

_EXTENSION_SERVER = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "extension_server.py")
import logging
import threading
import time

import websockets

from desktop.core import config
from desktop.core.tasks import spawn
from desktop.core.eyes import get_active_window, get_system_info
from desktop.core.hands import execute_command, scan_apps, init_index
from desktop.core.hands import hotkey as _hotkey, type_text as _type_text
from desktop.core.hands import focus_window as _focus_window, powershell as _powershell
from desktop.core.hands import switch_to_app as _switch_to_app
from desktop.core.hands import nudge_volume as _nudge_volume
from desktop.core.hearing import Hearing
from desktop.core.voice import Player
from desktop.core.local_mood import LocalMood
from desktop.core.dep_check import check_critical_packages
from desktop.core.outbox import Outbox, log_send_result

log = logging.getLogger("sakura.agent")

# Возврат в idle после tts_end: ждём опустошения буфера плеера
_DRAIN_POLL_SEC = 0.08   # опрос буфера
_DRAIN_MAX_SEC  = 15.0   # дольше не ждём
_DRAIN_TAIL_SEC = 0.15   # хвост в звуковой карте после пустого буфера

# Страховка от зависших состояний (сервер не прислал tts_end / ответ)
_WATCH_PERIOD_SEC   = 0.5
_SPEAK_STALL_SEC    = 2.5    # speaking, буфер пуст, звука не было столько
_THINK_TIMEOUT_SEC  = 25.0   # thinking дольше — ответа не будет


# ── Музыка (v3, этап 3): канонические имена и явный выбор бэкенда ────────
# Канонические имена v3 (music.*) принимаются В ДОПОЛНЕНИЕ к старым
# (music_* / music:*) — поддержка старых удаляется на этапе 8.
_MUSIC_SMTC_VERBS = (
    # глагол → имя для core.music.music_command (= легаси-имя на проводе)
    ("next", "music_next"),
    ("prev", "music_prev"),
    ("play_pause", "music_play_pause"),
    ("like", "music_like"),
    ("dislike", "music_dislike"),
    ("now_playing", "music_info"),
    ("history", "music_history"),
    ("liked_tracks", "music_liked_tracks"),
    ("playlists", "music_playlists"),
)
_MUSIC_BROWSER_VERBS = (
    # идут через расширение браузера (core.browser.music_action, имя music:<verb>)
    "shuffle", "repeat", "seek_forward", "seek_back",
    "podcasts", "mute", "volume_up", "volume_down",
)

# Приложение (yamusic_app): волна и легаси play/pause
_MUSIC_APP_ACTIONS = ("music.wave", "music.play", "music.pause")

# Единая входная карта: имя на проводе (любое написание) →
# (бэкенд, канонический id, легаси-имя для бэкенда).
_MUSIC_INBOUND = {}
for _v, _lg in _MUSIC_SMTC_VERBS:
    _c = f"music.{_v}"
    _MUSIC_INBOUND[_c] = _MUSIC_INBOUND[f"music_{_lg[6:]}"] = \
        _MUSIC_INBOUND[f"music:{_v}"] = ("smtc", _c, _lg)
for _v in _MUSIC_BROWSER_VERBS:
    _c = f"music.{_v}"
    _MUSIC_INBOUND[_c] = _MUSIC_INBOUND[f"music:{_v}"] = ("browser", _c, f"music:{_v}")
for _a in _MUSIC_APP_ACTIONS:
    _MUSIC_INBOUND[_a] = ("app", _a, _a)
_MUSIC_INBOUND["music:wave"] = ("app", "music.wave", "music:wave")
_MUSIC_INBOUND["music:play"] = ("app", "music.play", "music:play")
_MUSIC_INBOUND["music:pause"] = ("app", "music.pause", "music:pause")
# легаси-имя волны из LLM-роутера v2: в v2 шло в music_command, которая его# не знала (мёртвый путь); теперь — в приложение, как music:wave
_MUSIC_INBOUND["music_play_wave"] = ("app", "music.wave", "music_play_wave")


# ── Канонические имена доменов (v3, этап 5) ─────────────────────────────
# Реестр отдаёт домены на провод каноническим id (browser.tab_next,
# youtube.forward, ext.page_content …). Агент принимает их В ДОПОЛНЕНИЕ
# к старым написаниям; старые удаляются на этапе 8.
# Маппинг: канонический id → легаси-имя, которое уже обрабатывает агент.

# browser.* → browser:<verb> (execute_command, verb "browser")
BROWSER_VERBS = {
    "back": "back", "forward": "forward",
    "scroll_down": "scroll_down", "scroll_up": "scroll_up",
    "tab_close": "tab_close", "tab_dup": "tab_dup",
    "tab_new": "tab_new", "tab_next": "tab_next",
    "tab_prev": "tab_prev", "tab_reload": "tab_reload",
}

# youtube.* → youtube_<verb> (execute_command / extension)
YOUTUBE_VERBS = {
    "forward": "forward", "fullscreen": "fullscreen", "like": "like",
    "mini": "mini", "next": "next", "pause": "pause", "rewind": "rewind",
    "speed_down": "speed_down", "speed_up": "speed_up",
    "sub_toggle": "sub_toggle", "theater": "theater", "trending": "trending",
}

# ext.* → ext:<name> (ветка расширения)
EXT_NAMES = {
    "page_content": "page_content",
    "page_content_youtube": "page_content_youtube",
}


def _legacy_action(action: str, arg: str = "") -> str:
    """Канонический id → легаси-имя действия агента (этап 5).

    Возвращает легаси-действие либо сам action, если канонического
    маппинга нет (тогда старое поведение сохраняется без изменений).
    """
    domain, _, verb = action.partition(".")
    if domain == "browser" and verb in BROWSER_VERBS:
        return f"browser:{BROWSER_VERBS[verb]}"
    if domain == "youtube" and verb in YOUTUBE_VERBS:
        return f"youtube_{YOUTUBE_VERBS[verb]}"
    if domain == "ext" and verb in EXT_NAMES:
        return f"ext:{EXT_NAMES[verb]}"
    if action == "close_window.браузер":
        return "close_window:браузер"
    if action == "game_mode.on":
        return "game_mode:on"
    if action == "game_mode.off":
        return "game_mode:off"
    if action == "screenshot.run":
        return "screenshot:"
    if action == "screenshot.describe":
        return "screenshot:"
    if action == "open.app":
        target = arg or "яндекс музыка"
        return f"open_app:{target}"
    if action == "app.switch":
        return f"switch_to_app:{arg}" if arg else "switch_to_app:"
    # system.* → system:<verb> (execute_command, verb "system"): опасные
    # системные действия переехали в реестр на этапе 5, подтверждение
    # спрашивает сервер (executor, confirm: true) — агент выключает сразу.
    if domain == "system" and verb in ("shutdown", "restart", "sleep", "lock"):
        return f"system:{verb}"
    return action


def _music_canonical(action: str):
    """Привести имя музыкального действия к каноническому.

    Возвращает (бэкенд, канонический id, легаси-имя для бэкенда) либо None,
    если это не музыка. Неизвестные music_* (music_recommendations,
    music_search:…) идут в SMTC как есть — их поведение не менялось.
    """
    if action.startswith(("music.", "music_", ":".join(("music", "")))):
        hit = _MUSIC_INBOUND.get(action)
        if hit is not None:
            return hit
        if action.startswith("music_"):
            return "smtc", "music.legacy", action
        return None
    return None



class Agent:
    def __init__(self, bus):
        # Явная проверка критичных пакетов (winsdk и пр.) при старте:
        # отсутствующее пишется в лог как WARNING, а не падает молча.
        try:
            check_critical_packages()
        except Exception:
            log.exception("[agent] ошибка проверки зависимостей")
        self.bus     = bus
        self._state       = "idle"
        self._state_since = time.monotonic()
        self._turn_gen    = 0
        self._state_lock  = threading.Lock()
        self.player  = Player(config.TTS_RATE)
        self.hearing = Hearing(self)
        self._ws     = None
        self._loop   = None
        self._outbox = Outbox()
        self.last_voice_prosody = None
        self._last_window    = ""
        self._window_since   = time.monotonic()
        self._activity_level = 0.0
        self.local_mood = LocalMood()
        self._last_mood_update = {}  # последний mood_update от сервера
        self._current_track = {}     # кэш текущего трека (обновляет heartbeat)
        self._abort_flag = False     # аварийный тормоз (abort_all)

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str):
        """Единая точка смены состояния (вызывается и из потока слуха).

        При смене на thinking/speaking начинается новая реплика —
        растёт _turn_gen, отложенный idle от прошлой реплики устаревает.
        """
        with self._state_lock:
            if state != self._state:
                self._state_since = time.monotonic()
                if state in ("thinking", "speaking"):
                    self._turn_gen += 1
            self._state = state
        self.bus.emit("state", value=state)

    def set_state(self, state: str):
        # Публичное имя для hearing.py / presence.py
        self._set_state(state)

    def submit_user_text(self, text: str, wake_detected_at: float | None = None,
                         timeline: dict | None = None):
        text = text.strip()
        if not text:
            return
        self.bus.emit("user_text", text=text)
        self._set_state("thinking")
        self.send_threadsafe({
            "type":          "voice_command",
            "device_id":     config.DEVICE_ID,
            "token":         config.WS_TOKEN.strip(),
            "text":          text,
            "active_window": get_active_window(),
            "context":       [],
        }, wake_detected_at=wake_detected_at, timeline=timeline)

    def send_threadsafe(self, obj: dict, wake_detected_at: float | None = None,
                        timeline: dict | None = None):
        if not self._outbox.put(obj):
            return
        kind = obj.get("type", "unknown")
        if timeline is not None and wake_detected_at is None:
            wake_detected_at = timeline["wake"]

        def _log_timeline(sent_at: float, status: str):
            if timeline is None:
                return

            def elapsed(start, end):
                if start not in timeline or end not in timeline:
                    return None
                return (timeline[end] - timeline[start]) * 1000

            metrics = (
                ("wake_to_vad_start_ms", elapsed("wake", "vad_start")),
                ("vad_start_to_speech_end_ms", elapsed("vad_start", "speech_end")),
                ("speech_end_to_recording_end_ms", elapsed("speech_end", "recording_end")),
                ("recording_end_to_stt_ready_ms", elapsed("recording_end", "stt_ready")),
                ("stt_ready_to_sent_ms", (sent_at - timeline["stt_ready"]) * 1000
                 if "stt_ready" in timeline else None),
                ("speech_end_to_sent_ms", (sent_at - timeline["speech_end"]) * 1000
                 if "speech_end" in timeline else None),
                ("wake_to_sent_ms", (sent_at - timeline["wake"]) * 1000),
            )
            fields = " ".join(
                f"{name}={value:.1f}" for name, value in metrics if value is not None
            )
            log.info("[timeline] id=%s %s status=%s", timeline["id"], fields, status)

        ws, loop = self._ws, self._loop
        if ws is None or loop is None or not loop.is_running():
            log.warning("[outbox] deferred type=%s: disconnected", kind)
            if wake_detected_at is not None:
                log.info("[timeline] wake_to_send_ms=%.1f status=deferred",
                         (time.monotonic() - wake_detected_at) * 1000)
                _log_timeline(time.monotonic(), "deferred")
            return
        coro = self._outbox.flush(ws)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            log.exception("[outbox] scheduling failed type=%s; queued", kind)
            return
        def _on_send_done(done):
            log_send_result(done, kind)
            if wake_detected_at is not None:
                try:
                    done.result()
                except Exception:
                    status = "failed"
                else:
                    status = "sent"
                log.info("[timeline] wake_to_send_ms=%.1f status=%s",
                         (time.monotonic() - wake_detected_at) * 1000, status)
                _log_timeline(time.monotonic(), status)

        future.add_done_callback(_on_send_done)

    def _payload(self, kind: str) -> dict:
        # Расширенная системная информация (температуры, диск)
        try:
            from desktop.core.presence import get_extended_system_info
            sys_info = get_extended_system_info()
        except Exception:
            sys_info = get_system_info()

        # Текущее окно + время в нём
        window = get_active_window()
        now = time.monotonic()
        if window != self._last_window:
            self._last_window = window
            self._window_since = now
        focus_seconds = int(now - self._window_since)

        # Уровень активности (мышь/клавиатура)
        try:
            from desktop.core.presence import get_activity_level
            self._activity_level = get_activity_level()
        except Exception:
            pass

        payload = {
            "type":          kind,
            "device_id":     config.DEVICE_ID,
            "token":         config.WS_TOKEN.strip(),
            "active_window": window,
            "system_info":   sys_info,
            "focus_seconds": focus_seconds,
            "activity_level": round(self._activity_level, 2),
        }
        # Добавляем текущий трек — ТОЛЬКО из кэша heartbeat (не блокируем
        # loop-поток: SMTC-вызовы из loop давали задержки command_result)
        track = self._current_track
        if track and track.get("title"):
            payload["current_track"] = track
        return payload

    async def _heartbeat(self):
        last_window, last_ping = None, 0.0
        last_mood_emit = 0.0
        while True:
            await asyncio.sleep(config.WINDOW_POLL)
            if not self._ws:
                continue

            window, now = get_active_window(), time.monotonic()

            # Обновляем локальный mood каждые 2 секунды
            if (now - last_mood_emit) >= 2.0:
                last_mood_emit = now
                try:
                    from desktop.core.music import _smtc_get_info
                    # await внутри loop'а — НЕ блокируем поток loop'а
                    # синхронным SMTC-вызовом (прежний вариант
                    # run_coroutine_threadsafe().result() из loop'а
                    # взаимоблокировал heartbeat и задерживал
                    # отправку command_result на сервер)
                    track = await asyncio.wait_for(_smtc_get_info(), timeout=3.0)
                    # Кэшируем для _payload("ping") — там SMTC не вызываем
                    self._current_track = track or {}
                except Exception:
                    track = None

                # Температура ноутбука
                cpu_temp = None
                try:
                    from desktop.core.presence import get_extended_system_info
                    si = get_extended_system_info()
                    cpu_temp = si.get("cpu_temp")
                except Exception:
                    pass

                self.local_mood.update(
                    track=track,
                    activity=self._activity_level,
                    cpu_temp=cpu_temp,
                    server_mood=self._last_mood_update,
                )

                # Эмитим mood в орб
                orb_params = self.local_mood.get_orb_params()
                self.bus.emit("mood_update", params=orb_params)

            if window != last_window or (now - last_ping) >= config.PING_INTERVAL:
                try:
                    await self._ws.send(json.dumps(self._payload("ping")))
                    last_window, last_ping = window, now
                except Exception:
                    pass

    async def _recv_loop(self):
        async for raw in self._ws:
            try:
                # ── Бинарный TTS-чанк (новый формат) ──────────────────────
                if isinstance(raw, bytes):
                    self._set_state("speaking")
                    self.player.feed_binary(raw)
                    continue

                data = json.loads(raw)
                kind = data.get("type")

                if kind == "command":
                    _cmd_id = data.get("id")
                    _action = data.get("action", "")
                    if _action == "abort_all":
                        self._abort_flag = True
                        if _cmd_id:
                            await self._ws.send(json.dumps({
                                "type": "command_result", "id": _cmd_id,
                                "device_id": config.DEVICE_ID, "ok": True,
                                "detail": "abort принят",
                            }))
                        continue
                    self._abort_flag = False
                    _arg = data.get("arg", "")
                    spawn(self._run_command(_action, _cmd_id, _arg), name="command-execution")

                elif kind == "tts_chunk":
                    # При первом чанке нового ответа — сбрасываем буфер
                    if self._state != "speaking":
                        self.player.interrupt()
                    self._set_state("speaking")
                    self.player.feed(base64.b64decode(data["audio"]))

                elif kind == "tts_end":
                    # idle — только когда буфер плеера доиграет
                    log.info(f"[state] tts_end получен (буфер {self.player.buffer_bytes()} байт)")
                    self.player.flush()
                    spawn(self._idle_after_playback(self._turn_gen, data.get("listen")),
                          name="idle-after-playback")

                elif kind == "reply":
                    text = (data.get("text") or "").strip()
                    if text:
                        self.bus.emit("sakura_text", text=text)

                elif kind == "mood_update":
                    params = data.get("params", {})
                    if params.get("is_arrival") or params.get("is_departure"):
                        from desktop.core.platform import get_platform
                        log.info("[overlay] получен %s (ввод %.0f с назад)",
                                 "is_arrival" if params.get("is_arrival") else "is_departure",
                                 get_platform().idle_seconds())
                    if params.get("is_arrival"):
                        self.bus.emit("orb_arrival")
                    elif params.get("is_departure"):
                        self.bus.emit("orb_departure")
                    if params:
                        self.bus.emit("mood_update", params=params)
                        # Сохраняем для микширования с локальным mood
                        self._last_mood_update = {
                            "valence": params.get("valence", 0.0),
                            "arousal": params.get("arousal", 0.3),
                        }

                elif kind == "context_transfer":
                    text = data.get("text", "")
                    if text:
                        self.bus.emit("context_transfer", text=text)

            except Exception as e:
                log.error(f"recv: {e}")

    async def _idle_after_playback(self, gen: int, listen=None):
        """После tts_end: дождаться опустошения буфера, затем idle.

        Если за время ожидания началась новая реплика (_turn_gen
        изменился) — ничего не делаем. Окно дослушивания открываем
        только после idle.
        """
        deadline = time.monotonic() + _DRAIN_MAX_SEC
        while not self.player.is_drained() and time.monotonic() < deadline:
            await asyncio.sleep(_DRAIN_POLL_SEC)
        await asyncio.sleep(_DRAIN_TAIL_SEC)
        if self._turn_gen != gen:
            return
        self._set_state("idle")
        if listen is not None:
            try:
                self.hearing.open_followup(float(listen))
            except (TypeError, ValueError):
                log.warning("Некорректное окно прослушивания: %r", listen)

    def _check_state_stall(self, now: float | None = None):
        """Сбросить в idle зависшие speaking/thinking (с WARNING)."""
        now = time.monotonic() if now is None else now
        state = self._state
        if state == "speaking":
            if (self.player.is_drained()
                    and now - self.player.last_feed_ts >= _SPEAK_STALL_SEC):
                log.warning("[state] speaking без tts_end -> idle "
                            f"(последний чанк {now - self.player.last_feed_ts:.1f} с назад, "
                            f"буфер {self.player.buffer_bytes()} байт)")
                self.player.flush()
                self._set_state("idle")
        elif state == "thinking":
            if now - self._state_since >= _THINK_TIMEOUT_SEC:
                log.warning("[state] thinking без ответа -> idle")
                self._set_state("idle")

    async def _state_watchdog(self):
        while True:
            await asyncio.sleep(_WATCH_PERIOD_SEC)
            try:
                self._check_state_stall()
            except Exception:
                log.exception("[state] ошибка проверки состояния")

    async def _run_command(self, action: str, cmd_id: str | None = None,
                           arg: str = ""):
        if not action:
            return
        # Канонические имена (browser.*, youtube.*, ext.*, open.app …) —
        # в дополнение к старым (этап 5), до всей диспетчеризации.
        action = _legacy_action(action, arg)
        log.info(f"command: {action} (id={cmd_id})")

        async def _send_ack(ok: bool, detail: str, extra: dict | None = None):
            """Отправить command_result с id (если есть)."""
            if not cmd_id:
                return
            msg = {
                "type": "command_result", "id": cmd_id,
                "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                "ok": ok, "detail": detail,
            }
            if extra:
                msg.update(extra)
            try:
                await self._ws.send(json.dumps(msg))
            except Exception:
                pass

        # Игровой режим — переключаем через bus
        if action == "game_mode:on":
            self.bus.emit("game_mode", on=True)
            await _send_ack(True, "game_mode:on")
            return
        if action == "game_mode:off":
            self.bus.emit("game_mode", on=False)
            await _send_ack(True, "game_mode:off")
            return

        # ── Новые примитивы (этап 4) ────────────────────────────────
        if action.startswith("hotkey:"):
            result = await asyncio.to_thread(_hotkey, action[7:])
            await _send_ack(result.get("ok", False), result.get("detail", ""))
            return

        if action.startswith("type_text:"):
            result = await asyncio.to_thread(_type_text, action[10:])
            await _send_ack(result.get("ok", False), result.get("detail", ""))
            return

        if action.startswith("focus_window:"):
            result = await asyncio.to_thread(_focus_window, action[13:])
            await _send_ack(result.get("ok", False), result.get("detail", ""))
            return

        if action.startswith("switch_to_app:"):
            result = await asyncio.to_thread(_switch_to_app, action[14:])
            await _send_ack(result.get("ok", False), result.get("detail", ""))
            return

        if action.startswith("powershell:"):
            if self._abort_flag:
                await _send_ack(False, "прервано abort_all")
                return
            result = await asyncio.to_thread(_powershell, action[11:])
            await _send_ack(result.get("ok", False), result.get("detail", ""))
            return

        # ── Музыка: единый блок диспетчеризации (v3, этап 3) ──────────────
        # Один блок вместо трёх (SMTC / браузер / yamusic_app): бэкенд
        # выбирается по каноническому действию. Канонические имена v3
        # (music.*) принимаются в дополнение к старым — до этапа 8.
        # Громкость музыки — системным микшером на N% (медиаклавиша даёт лишь 2%)
        if action in ("music.volume_up", "music.volume_down",
                      "music:volume_up", "music:volume_down"):
            n = int(arg) if arg.isdigit() and 1 <= int(arg) <= 100 else config.VOLUME_STEP
            up = action.endswith("up")
            await asyncio.to_thread(_nudge_volume, n if up else -n)
            await _send_ack(True, f"{'громче' if up else 'тише'} на {n}%")
            return

        _music = _music_canonical(action)
        if _music:
            _mbackend, _mcanon, _mlegacy = _music
            _t0 = time.monotonic()
            try:
                if _mbackend == "smtc":
                    # SMTC + Яндекс Музыка API
                    from desktop.core.music import music_command
                    log.info(f"[music] начата обработка {_mcanon} → {_mlegacy} (id={cmd_id})")
                    result = await asyncio.wait_for(music_command(_mlegacy), timeout=15.0)
                    result["action"] = _mlegacy
                    _ms = int((time.monotonic() - _t0) * 1000)
                    log.info(f"[music] результат {_mlegacy} за {_ms}мс (id={cmd_id}): "
                             f"ok={result.get('ok')} detail={result.get('result','')!r}")
                    await self._ws.send(json.dumps({
                        "type": "command_result", "id": cmd_id,
                        "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                        "ok": True, "detail": result.get("result", ""),
                        "music": result,
                    }))
                    log.info(f"[music] command_result отправлен серверу (id={cmd_id})")
                elif _mbackend == "browser":
                    # Команды через расширение браузера
                    from desktop.core import browser as _br
                    result = await asyncio.to_thread(_br.music_action, _mlegacy)
                    await _send_ack(
                        result.get("ok", True),
                        result.get("detail", action),
                        extra={"browser": result},
                    )
                else:
                    # Приложение (yamusic_app): волна / легаси play / pause
                    from desktop.core import yamusic_app as _ym
                    if _mcanon == "music.wave":
                        ok = await asyncio.to_thread(_ym.open_wave)
                        detail = "Моя волна" if ok else "не удалось открыть"
                    elif _mcanon == "music.play":
                        ok = await asyncio.to_thread(_ym.play_pause)
                        detail = "играет" if ok else "SMTC сессия не найдена"
                    elif _mcanon == "music.pause":
                        ok = await asyncio.to_thread(_ym.play_pause)
                        detail = "пауза" if ok else "SMTC сессия не найдена"
                    else:
                        ok, detail = False, f"unknown: {_mcanon}"
                    await _send_ack(bool(ok), detail, extra={"yamusic": True})
            except asyncio.TimeoutError:
                log.error(f"[music] таймаут обработки {_mcanon} (id={cmd_id})")
                await _send_ack(False, f"{_mcanon}: таймаут обработки")
            except Exception as e:
                log.error(f"music error: {e}")
                await _send_ack(False, f"music error: {e}")
            return

        # Команды через расширение браузера
        if action.startswith("ext:"):
            try:
                import sys as _s
                _ext = _s.modules.get('desktop.core.extension_server')
                if not _ext:
                    log.warning("[ext] Модуль расширения не загружен")
                    await _send_ack(False, "расширение не загружено")
                    return
                send_command  = _ext.send_command
                is_connected  = _ext.is_connected
                if not is_connected():
                    log.warning("[ext] Расширение не подключено")
                    await _send_ack(False, "расширение не подключено")
                    return
                parts     = action[4:].split(":", 1)
                ext_action = parts[0]
                ext_arg    = parts[1] if len(parts) > 1 else ""
                result    = await send_command(ext_action, ext_arg)
                log.info(f"[ext] {ext_action} → {result}")
                await self._ws.send(json.dumps({
                    "type": "command_result", "id": cmd_id,
                    "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                    "ok": True, "detail": str(result.get("result", result.get("error", ""))),
                    "ext": result,
                }))
            except Exception as e:
                log.error(f"ext command error: {e}")
                await _send_ack(False, f"ext error: {e}")
            return

        # YouTube команды плеера
        if action.startswith("youtube_") and action not in (
            "youtube_search", "youtube_channel", "youtube_playlist", "youtube_trending"
        ):
            try:
                _ext = __import__('sys').modules.get('desktop.core.extension_server')
                if _ext and _ext.is_connected():
                    result = await _ext.send_command(action)
                    log.info(f"[yt] {action} via extension → {result}")
                else:
                    from desktop.core.browser import youtube_player_cmd
                    result = await asyncio.to_thread(youtube_player_cmd, action)
                    log.info(f"[yt] {action} via hotkey → {result}")
                await _send_ack(True, str(result))
            except Exception as e:
                log.error(f"youtube error: {e}")
                await _send_ack(False, f"youtube error: {e}")
            return

        # Чайник — BLE
        if action.startswith("kettle:"):
            kettle_action = action[len("kettle:"):]
            try:
                from desktop.core.kettle import kettle_command
                result = await kettle_command(kettle_action)
                await self._ws.send(json.dumps({
                    "type": "command_result", "id": cmd_id,
                    "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                    "ok": result.get("ok", False), "detail": result.get("result", ""),
                    "kettle": result,
                }))
                if result.get("ok") and kettle_action in ("boil", "boil_heat") or kettle_action.startswith("boil"):
                    spawn(self._kettle_watch(), name="kettle-watch")
            except Exception as e:
                log.error(f"kettle error: {e}")
                await _send_ack(False, f"kettle error: {e}")
            return

        # ── Фолбэк: execute_command (hands.py) ──────────────────────
        try:
            # arg приходит отдельно («volume» + «70») — склеиваем в «volume:70»
            full = f"{action}:{arg}" if arg and ":" not in action else action
            out = await asyncio.to_thread(execute_command, full)
            if out.get("screenshot"):
                await self._ws.send(json.dumps({
                    "type": "command_result", "id": cmd_id,
                    "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                    "ok": True, "detail": "скриншот",
                    "screenshot": out["screenshot"],
                }))
            elif out.get("result"):
                log.info(f"→ {out['result']}")
                await _send_ack(True, out["result"])
            else:
                await _send_ack(True, "выполнено")
        except Exception as e:
            log.error(f"execute_command error: {e}")
            await _send_ack(False, f"ошибка: {e}")

    async def _kettle_watch(self):
        """
        Мониторинг чайника.
        Redmond RK-G210S недоступен по BLE пока кипит — не поллим.
        Стратегия: ждём ~7 минут (среднее время кипячения),
        потом пробуем один раз подключиться и проверить статус.
        Если не получилось — просто уведомляем что должен быть готов.
        """
        log.info("[kettle] Мониторинг запущен, ждём ~7 минут")
        from desktop.core.kettle import kettle_command

        # Ждём пока чайник закипит (обычно 5-7 минут)
        await asyncio.sleep(420)  # 7 минут

        # Пробуем подключиться и проверить температуру
        temp = 100  # по умолчанию считаем что вскипел
        for attempt in range(3):
            try:
                st = await kettle_command("status")
                if st.get("ok"):
                    temp = st.get("temp_current", 100)
                    log.info(f"[kettle] Статус после кипячения: {st.get('status')} {temp}°C")
                    break
            except Exception as e:
                log.debug(f"[kettle] watch attempt {attempt+1}: {e}")
                await asyncio.sleep(30)

        # Отправляем уведомление в любом случае
        try:
            await self._ws.send(json.dumps({
                "type":      "kettle_ready",
                "device_id": config.DEVICE_ID,
                "token":     config.WS_TOKEN,
                "temp":      temp,
            }))
            log.info("[kettle] Уведомление отправлено")
        except Exception as e:
            log.error(f"[kettle] watch send error: {e}")

    async def run(self):
        # Без токена VPS не пустит — не стучимся вовсе (токен только из .env)
        if not str(getattr(config, "WS_TOKEN", "") or "").strip():
            log.error("WS_TOKEN не задан в .env")
            # Окно не закрываем — показываем причину в оверлее
            self.bus.emit("agent_alert",
                          text="Не задан WS_TOKEN (.env) — агент не подключается")
            return
        self._loop = asyncio.get_running_loop()
        from desktop.core.presence import prime_system_info
        prime_system_info()
        # Запускаем локальный WS сервер для расширения браузера
        try:
            import importlib.util as _ilu, threading as _th
            _spec = _ilu.spec_from_file_location('extension_server', _EXTENSION_SERVER)
            _mod  = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            import sys as _s; _s.modules['desktop.core.extension_server'] = _mod
            _mod.set_agent_loop(asyncio.get_running_loop())

            def _run_ext_server():
                # Цикл с нарастающим перезапуском живёт в extension_server
                # (run_forever): пауза при любом завершении start(), 5/10/30/60,
                # сброс после минуты стабильной работы. Тестируется напрямую.
                _mod.run_forever(start=_mod.start)

            _ext_thread = _th.Thread(target=_run_ext_server, daemon=True, name="extension-server")
            _ext_thread.start()
        except Exception as _ext_e:
            log.warning(f"[extension] Не удалось запустить сервер: {_ext_e}")

        spawn(self._heartbeat(), name="agent-heartbeat")
        spawn(self._state_watchdog(), name="state-watchdog")
        spawn(self._screen_analysis_loop(), name="screen-analysis-loop")
        self.hearing.start()

        # Фоновый индекс — не блокируем event loop
        import threading as _th2
        _th2.Thread(target=init_index, daemon=True).start()

        # ── Основной цикл: подключение к VPS ──────────────────────────
        log.info("[agent] Запускаю подключение к VPS: %s", config.VPS_WS_URL)
        _backoff = config.RECONNECT_SEC
        while True:
            try:
                log.info("[agent] Подключаюсь к %s...", config.VPS_WS_URL)
                async with websockets.connect(
                    config.VPS_WS_URL,
                    ping_interval=20,
                    proxy=None,
                    max_size=None,
                ) as ws:
                    await ws.send(json.dumps(self._payload("register")))
                    self._ws = ws
                    await self._outbox.flush(ws)
                    apps = await asyncio.to_thread(scan_apps)
                    if apps:
                        await ws.send(json.dumps({
                            "type":      "apps_list",
                            "device_id": config.DEVICE_ID,
                            "token":     config.WS_TOKEN,
                            "apps":      apps,
                        }))
                    self.bus.emit("connection", online=True)
                    _backoff = config.RECONNECT_SEC
                    log.info("[agent] Подключено к VPS! Приложений: %s", len(apps))
                    await self._recv_loop()
            except Exception as e:
                log.exception("[agent] WS ошибка: %s", e)
            self._ws = None
            self.bus.emit("connection", online=False)
            await asyncio.sleep(_backoff)
            _backoff = min(_backoff * 2, 60)

    async def _screen_analysis_loop(self):
        """
        Периодический анализ экрана — не для команды, а для понимания.
        Раз в 5 минут, когда пользователь активен.
        """
        import base64
        await asyncio.sleep(120)  # ждём 2 минуты после старта
        while True:
            await asyncio.sleep(300)  # каждые 5 минут

            # Только если пользователь активен
            if self._activity_level < 0.1:
                continue

            # Только если есть WS
            if not self._ws:
                continue

            try:
                from desktop.core.hands import execute_command
                result = await asyncio.to_thread(execute_command, "screenshot:")
                if result.get("screenshot"):
                    # Отправляем на VPS для анализа (не для команды)
                    await self._ws.send(json.dumps({
                        "type":      "screen_context",
                        "device_id": config.DEVICE_ID,
                        "token":     config.WS_TOKEN,
                        "screenshot": result["screenshot"],
                        "active_window": get_active_window(),
                    }))
                    log.debug("[screen] Скриншот отправлен для анализа")
            except Exception as e:
                log.debug(f"[screen] Ошибка: {e}")
