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
from desktop.core import results as R
from desktop.core.dep_check import check_critical_packages
from desktop.core.eyes import get_active_window, get_system_info
from desktop.core.hands import execute_command, init_index, scan_apps
from desktop.core.hands import focus_window as _focus_window
from desktop.core.hands import hotkey as _hotkey
from desktop.core.hands import nudge_volume as _nudge_volume
from desktop.core.hands import powershell as _powershell
from desktop.core.hands import switch_to_app as _switch_to_app
from desktop.core.hands import type_text as _type_text
from desktop.core.hearing import Hearing
from desktop.core.outbox import Outbox, log_send_result
from desktop.core.tasks import spawn
from desktop.core.voice import Player

log = logging.getLogger("sakura.agent")

# speaking и idle задаёт плеер: Player.on_start — звук ответа пошёл из колонок, Player.on_end — доиграл
# (флаг из колбэка звука + задержка устройства), без опроса буфера.
# Уровень звука для ядра-графики — не чаще 30 раз в секунду.
LEVEL_PERIOD_SEC = 1 / 30
_LEVEL_STEP = 0.02       # меньшие изменения уровня окну не шлём

# Страховка от зависших состояний (сервер не прислал tts_end / ответ)
_WATCH_PERIOD_SEC   = 0.5
_SPEAK_STALL_SEC    = 2.5    # speaking, буфер пуст, звука не было столько
_THINK_TIMEOUT_SEC  = 25.0   # thinking дольше — ответа не будет

# ping не реже раза в столько секунд, даже без смены окна: сервер судит о присутствии по input_idle_s.
PING_MAX_SEC = 10
# «Секунд без ввода» больше суток — платформа не знает (IDLE_UNKNOWN), поле не шлём.
_IDLE_MAX_SEC = 86400.0


def input_idle_seconds(platform=None) -> float | None:
    """Секунды с последнего ввода мыши/клавиатуры (GetLastInputInfo) с точностью 0,1 с; None — неизвестно."""
    try:
        if platform is None:
            from desktop.core.platform import get_platform
            platform = get_platform()
        idle = float(platform.idle_seconds())
    except Exception:
        return None
    if not 0 <= idle < _IDLE_MAX_SEC:
        return None
    return round(idle, 1)


# ── Музыка (v3, этап 3): канонические имена и явный выбор бэкенда ────────
# Канонические имена v3 (music.*) принимаются В ДОПОЛНЕНИЕ к старым
# (music_* / music:*) — поддержка старых удаляется на этапе 8.
_MUSIC_SMTC_VERBS = (
    # глагол → имя для core.music.music_command (= легаси-имя на проводе)
    ("next", "music_next"),
    ("prev", "music_prev"),
    ("restart", "music_restart"),   # «трек сначала» (п. 7); prev — умный двойной шаг
    ("play_pause", "music_play_pause"),
    ("like", "music_like"),
    ("dislike", "music_dislike"),
    ("now_playing", "music_info"),
    ("history", "music_history"),
    ("liked_tracks", "music_liked_tracks"),
    ("playlists", "music_playlists"),
)
_MUSIC_BROWSER_VERBS = (
    # пульт приложения Яндекс.Музыки: SMTC и сессия (media.yandex_remote, _REMOTE_OPS)
    "shuffle", "repeat", "seek_forward", "seek_back",
    "podcasts", "mute", "volume_up", "volume_down",
)

# Те же глаголы — операции пульта приложения Яндекс.Музыки (media.yandex_remote).
_REMOTE_OPS = {"seek_forward": ("seek_by", 10), "seek_back": ("seek_by", -10)}


def _yamusic_remote():
    from desktop.core.media import yandex_remote
    return yandex_remote.shared()


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
    if action in ("app.switch", "app.switch_open"):
        return f"switch_to_app:{arg}" if arg else "switch_to_app:"
    # kettle.* — id реестра; сервер шлёт kettle:<verb>[:<градусы>] — клиент принимает оба.
    if domain == "kettle" and verb in ("boil", "off", "status", "heat", "boil_heat"):
        return f"kettle:{verb}:{arg}" if arg and verb in ("heat", "boil_heat") else f"kettle:{verb}"
    # system.* → system:<verb> (execute_command, verb "system"): опасные
    # системные действия переехали в реестр на этапе 5, подтверждение
    # спрашивает сервер (executor, confirm: true) — агент выключает сразу.
    # shutdown_cancel в старом агенте не переводился и давал «неизвестная команда».
    if domain == "system" and verb in ("shutdown", "restart", "sleep", "lock", "shutdown_cancel"):
        return f"system:{verb}"
    # Сервер шлёт громкость legacy-именем «volume» + число; id реестра system.volume — синоним.
    # «+N»/«-N» — относительно текущей (hands: volume_up/volume_down).
    if action == "music.restart_playing":
        return "music.restart"
    if action == "system.volume":
        a = (arg or "").strip()
        if a[:1] in ("+", "-") and a[1:].isdigit():
            return f"volume_{'up' if a[0] == '+' else 'down'}:{a[1:]}"
        return "volume"
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
    def __init__(self, bus, server_link=None):
        # Запросы протокола v2 (desktop.core.server_link); None — как старый агент.
        self.server_link = server_link
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
        self._seen_kinds: set = set()  # типы сообщений сервера, уже записанные в лог
        self._state_lock  = threading.Lock()
        self.player  = Player(config.TTS_RATE)
        self._bind_player()
        self.hearing = Hearing(self)
        self._ws     = None
        self._loop   = None
        self._outbox = Outbox()
        self.last_voice_prosody = None
        self._last_window    = ""
        self._window_since   = time.monotonic()
        self._activity_level = 0.0
        self._current_track = {}     # текущий трек (обновляет CoreService._on_music_state)

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

    # ── озвучка: состояние по реальному звуку ─────────────────────────
    def _bind_player(self):
        """Колбэки плеера приходят из его потока-уведомителя — переносим в цикл событий."""
        def hop(fn):
            def call(seq):
                loop = getattr(self, "_loop", None)
                if loop is not None and loop.is_running():
                    loop.call_soon_threadsafe(fn, seq)
            return call
        self.player.on_start = hop(self._on_audio_start)
        self.player.on_end = hop(self._on_audio_end)

    def _tts_chunk(self, interrupt_old: bool = False):
        """Пришёл чанк озвучки. speaking здесь не ставится — только когда звук пошёл (_on_audio_start)."""
        if not getattr(self, "_tts_open", False):
            # Первый чанк нового ответа: хвост прошлого ответа сбрасываем, если он уже не звучит.
            if interrupt_old and self._state != "speaking":
                self.player.interrupt()
            self._tts_open = True

    def _on_audio_start(self, seq: int):
        self._set_state("speaking")

    def _on_audio_end(self, seq: int):
        """Звук ответа доиграл (после tts_end): idle, затем окно дослушивания."""
        if getattr(self, "_tts_open", False):
            return  # уже звучит или пришёл следующий ответ
        state = self._state
        if state != "speaking" and not (state == "thinking"
                                        and self._turn_gen == getattr(self, "_tts_end_gen", None)):
            return  # пользователь уже начал новую реплику
        listen, self._tts_listen = getattr(self, "_tts_listen", None), None
        self._set_state("idle")
        if listen is not None and self._media_playing():
            log.info("[voice] окно дослушивания не открываю: играет музыка или видео")
        elif listen is not None:
            try:
                self.hearing.open_followup(float(listen))
            except (TypeError, ValueError):
                log.warning("Некорректное окно прослушивания: %r", listen)

    async def _level_loop(self):
        """Уровень звука окну (ядро-графика): озвучка — громкость выведенного звука, listening — микрофон."""
        last = -1.0
        while True:
            await asyncio.sleep(LEVEL_PERIOD_SEC)
            state = self._state
            if state == "speaking":
                value = getattr(self.player, "level", 0.0)
            elif state == "listening":
                value = getattr(self.hearing, "level", 0.0)
            else:
                value = 0.0
            value = round(min(1.0, max(0.0, float(value))), 2)
            if abs(value - last) >= _LEVEL_STEP or (value == 0.0 and last != 0.0):
                last = value
                self.bus.emit("level", value=value)

    def submit_user_text(self, text: str, wake_detected_at: float | None = None,
                         timeline: dict | None = None, channel: str | None = None,
                         source: str = "mic"):
        """source — откуда фраза: mic (голос), ui (окно чата), e2e (проверка), api (прочие клиенты)."""
        text = text.strip()
        if source == "mic":  # таблица замен распознанного (Настройки → Голос): «вал хейм» → «Valheim»
            from desktop.core.voice_tuning import apply_replacements
            text = apply_replacements(text, getattr(self, "stt_replacements", None)).strip()
        if not text:
            return
        self.bus.emit("user_text", text=text, source=source)
        self._set_state("thinking")
        # Нет связи с сервером — локальный разбор команд компьютера (в очередь не ставим: иначе после
        # переподключения команда выполнилась бы второй раз).
        loop = getattr(self, "_loop", None)
        if getattr(self, "_ws", None) is None and loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._offline_text(text), loop)
            return
        msg = {
            "type":          "voice_command",
            "device_id":     config.DEVICE_ID,
            "token":         config.WS_TOKEN.strip(),
            "text":          text,
            "active_window": self._window_for_send(),
            "context":       [],
        }
        if channel:  # протокол v2: voice | text (по умолчанию сервер считает voice)
            msg["channel"] = channel
        self.send_threadsafe(msg, wake_detected_at=wake_detected_at, timeline=timeline)

    def _window_for_send(self) -> str:
        """Окно для voice_command: из цикла событий — последнее известное (heartbeat, ≤ 2 с),
        из потока слуха — свежее (get_active_window — синхронный системный вызов)."""
        loop = getattr(self, "_loop", None)
        try:
            in_loop = loop is not None and asyncio.get_running_loop() is loop
        except RuntimeError:
            in_loop = False
        return getattr(self, "_last_window", "") if in_loop else get_active_window()

    async def _offline_text(self, text: str) -> dict:
        """Офлайн-режим: команда из реестра — выполнить локально и ответить шаблоном; иначе «нужна связь»."""
        from desktop.core import offline_intent as OI
        intents = getattr(self, "_offline_intents", None)
        if intents is None:
            intents = self._offline_intents = OI.OfflineIntents()
        hit = intents.match(text)
        if hit is None:
            reply = {"ok": False, "status": "unsupported", "detail": OI.REPLY_NEED_SERVER}
            self.bus.emit("sakura_text", text=OI.REPLY_NEED_SERVER, kind="error")
        else:
            action, arg = hit
            cmd_id = f"offline:{action}"
            fut = asyncio.get_running_loop().create_future()
            if not hasattr(self, "_local_results"):
                self._local_results = {}
            self._local_results[cmd_id] = fut
            await self._run_command(action, cmd_id, arg)
            try:
                reply = await asyncio.wait_for(fut, 30)
            except asyncio.TimeoutError:
                reply = {"ok": False, "status": "failed", "detail": "нет ответа от действия"}
            finally:
                self._local_results.pop(cmd_id, None)
            tpl = OI.REPLY_DONE if reply.get("ok") else OI.REPLY_FAIL
            self.bus.emit("sakura_text", text=tpl.format(detail=reply.get("detail", "")), kind="template")
            log.info("[offline] %s → %s", action, reply.get("status"))
        self._set_state("idle")
        return reply

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

    async def _payload_async(self, kind: str) -> dict:
        """_payload в потоке: окно, psutil и датчики — синхронные системные вызовы, циклу событий их нельзя."""
        return await asyncio.to_thread(self._payload, kind)

    def _payload(self, kind: str) -> dict:
        # Расширенная системная информация (температуры, диск)
        try:
            from desktop.core.presence import get_extended_system_info
            sys_info = get_extended_system_info()
        except Exception:
            sys_info = get_system_info()

        # Текущее окно + время в нём. Играет встроенное видео — сервер видит плеер
        # («… - YouTube — Sakura Player»), чтобы работал контекст window:youtube.
        media = getattr(self, "media", None)
        window = (media.active_window_hint() if media is not None else None) or get_active_window()
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
        if kind == "register":
            payload["proto"] = 2
        # Секунды с последнего ввода мыши/клавиатуры (сервер §10.1, §10.6); неизвестно — поля нет.
        idle = input_idle_seconds()
        if idle is not None:
            payload["input_idle_s"] = idle
        # Текущий трек — из события SMTC (CoreService._on_music_state), SMTC здесь не читаем.
        track = self._current_track
        # Встроенная музыка играет — её трек в том же формате (контекст playing:music).
        builtin = media.current_track() if media is not None else None
        if builtin:
            track = builtin
        if track and track.get("title"):
            payload["current_track"] = track
        return payload

    async def push_current_track(self):
        """Смена трека — сразу ping с current_track (не ждать heartbeat; цель ≤ 300 мс)."""
        ws = getattr(self, "_ws", None)
        if ws is None:
            return
        try:
            await ws.send(json.dumps(await self._payload_async("ping")))
        except Exception:  # noqa: BLE001
            pass

    async def _heartbeat(self):
        """ping при смене окна и не реже PING_MAX_SEC, даже если окно то же (input_idle_s растёт).
        SMTC не читается: трек приходит событием в CoreService._on_music_state."""
        last_window, last_ping = None, 0.0
        every = min(config.PING_INTERVAL, PING_MAX_SEC)
        while True:
            await asyncio.sleep(min(config.WINDOW_POLL, every))
            ws = self._ws
            if not ws:
                continue
            window, now = await asyncio.to_thread(get_active_window), time.monotonic()
            if window != last_window or (now - last_ping) >= every:
                try:
                    await ws.send(json.dumps(await self._payload_async("ping")))
                    last_window, last_ping = window, now
                except Exception:
                    pass

    async def _recv_loop(self):
        async for raw in self._ws:
            try:
                # ── Бинарный TTS-чанк (новый формат) ──────────────────────
                if isinstance(raw, bytes):
                    self._tts_chunk()
                    self.player.feed_binary(raw)
                    continue

                data = json.loads(raw)
                kind = data.get("type")
                # Диагностика протокола: тип и имена полей (без значений) — один раз на тип.
                seen = self.__dict__.setdefault("_seen_kinds", set())
                if kind not in seen:
                    seen.add(kind)
                    log.info("[server] сообщение type=%s поля=%s", kind, sorted(data))
                link = getattr(self, "server_link", None)
                if link is not None and link.handle(data):
                    continue

                if kind == "command":
                    _cmd_id = data.get("id")
                    _action = data.get("action", "")
                    _arg = data.get("arg", "")
                    # confirmed — сервер уже спросил подтверждение (действия с confirm в control).
                    spawn(self._run_command(_action, _cmd_id, _arg, confirmed=data.get("confirmed") is True),
                          name="command-execution")

                elif kind == "tts_chunk":
                    self._tts_chunk(interrupt_old=True)
                    self.player.feed(base64.b64decode(data["audio"]), data.get("sample_rate"), fmt="tts_chunk")

                elif kind == "tts_end":
                    # idle — когда звук реально доиграет (Player.on_end), окно дослушивания — после idle
                    log.info(f"[state] tts_end получен (буфер {self.player.buffer_bytes()} байт)")
                    self.bus.emit("tts_end")
                    self._tts_open = False
                    self._tts_listen = data.get("listen")
                    self._tts_end_gen = self._turn_gen
                    self.player.flush()

                elif kind == "reply":
                    text = (data.get("text") or "").strip()
                    log.info("[server] reply: %d симв. kind=%s turn=%s", len(text),
                             data.get("kind"), data.get("turn_id"))
                    if text:
                        # kind (llm|ack|template|error|proactive), turn_id, ts — когда сервер их шлёт.
                        self.bus.emit("sakura_text", text=text, kind=data.get("kind"),
                                      turn_id=data.get("turn_id"), ts=data.get("ts"))

                elif kind == "presence":
                    # proto 2 (сервер §10.4): arrival — Сакура перешла на этот ПК, departure — ушла с него.
                    event = data.get("event")
                    if event in ("arrival", "departure"):
                        log.info("[presence] %s: %s → %s", event, data.get("from"), data.get("to"))
                        self.bus.emit("orb_" + event)
                        self.bus.emit("presence", move={"event": event, "from": data.get("from"),
                                                        "to": data.get("to")})

                elif kind == "mood_update":
                    # proto 1: от настроения остались только флаги перехода между ПК.
                    params = data.get("params") or {}
                    if params.get("is_arrival"):
                        self.bus.emit("orb_arrival")
                    elif params.get("is_departure"):
                        self.bus.emit("orb_departure")

            except Exception as e:
                log.error(f"recv: {e}")

    def _media_playing(self) -> bool:
        """Играют встроенные плееры Сакуры (музыка, видео)."""
        media = getattr(self, "media", None)
        try:
            return bool(media and any(media.audio.playing.values()))
        except Exception:
            return False

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
                self._tts_open = False
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
                           arg: str = "", confirmed: bool = False):
        if not action:
            # Пустое действие — не «готово»: сервер должен узнать, что ничего не сделано.
            if cmd_id:
                await self._send_result(cmd_id, R.failed("пустое действие"))
            return
        # Канонические имена (browser.*, youtube.*, ext.*, open.app …) —
        # в дополнение к старым (этап 5), до всей диспетчеризации.
        action = _legacy_action(action, arg)
        log.info(f"command: {action} (id={cmd_id})")

        async def _send_ack(res: dict, extra: dict | None = None):
            """command_result по контракту {ok, status, detail} (desktop.core.results)."""
            await self._send_result(cmd_id, res, extra)

        # computer.do (выполнение задачи по шагам) — только вместе с серверным computer_step (решение владельца).
        if action == "computer.do":
            await _send_ack(R.unsupported("пока не поддерживается: нужен серверный computer_step"))
            return

        # «Включи музыку» (шаг Ж): запустить Яндекс.Музыку и начать воспроизведение.
        if action == "music.autoplay":
            ap = getattr(self, "autoplay", None)
            if ap is None:
                from desktop.core.media.autoplay import Autoplay
                ap = self.autoplay = Autoplay()
            await _send_ack(await ap.run(arg or "wave"))
            return

        # Игровой режим — переключаем через bus
        # Встроенные плееры (desktop.core.media): если активен встроенный —
        # действие music.*/youtube.* исполняет он, иначе — прежний внешний путь ниже.
        media = getattr(self, "media", None)
        if media is not None:
            handled = await media.handle_command(action, arg)
            if handled is not None:
                ok, detail = handled
                await _send_ack(R.from_legacy({"ok": ok, "result": detail}))
                return

        # Яндекс.Музыка не запущена — запуск с параметрами из Настроек (шаг Е: кнопки окна).
        # app_launcher выставляет run() (в тестах его нет — старый путь без системных вызовов).
        launcher = getattr(self, "app_launcher", None)
        if launcher is not None and action.startswith(("open_app:", "switch_to_app:", "app.switch_open")):
            from desktop.core import app_launch
            target = action.split(":", 1)[1] if ":" in action else arg
            key = app_launch.app_key(target)
            if key is not None:
                if not await asyncio.to_thread(lambda: launcher.state(key)["running"]):
                    await _send_ack(await asyncio.to_thread(launcher.launch, key))
                    return

        # Управление ПК (п. 2.3): окна, питание, процессы, буфер, экран и звук, сеть, клавиши, файлы.
        from desktop.core import control
        if action in control.ACTIONS:
            bus = getattr(self, "bus", None)
            # Опасное действие без подтверждения сервера — видимый запрос в окне (до 60 с).
            asker = getattr(self, "confirmations", None)
            if control.ACTIONS[action].confirm and not confirmed and asker is not None:
                confirmed = await asker.ask(action, arg)
                if not confirmed:
                    await _send_ack(R.unsupported("пользователь не подтвердил действие"))
                    return
            if bus is not None:
                bus.emit("pc_action", active=True)
            try:
                res = await asyncio.to_thread(control.execute, action, arg, confirmed)
            finally:
                if bus is not None:
                    bus.emit("pc_action", active=False)
            await _send_ack(res)
            return

        if action == "game_mode:on":
            self.bus.emit("game_mode", on=True)
            await _send_ack(R.done("игровой режим включён"))
            return
        if action == "game_mode:off":
            self.bus.emit("game_mode", on=False)
            await _send_ack(R.done("игровой режим выключен"))
            return

        # ── Новые примитивы (этап 4) ────────────────────────────────
        if action.startswith("hotkey:"):
            result = await asyncio.to_thread(_hotkey, action[7:])
            await _send_ack(R.from_legacy(result))
            return

        if action.startswith("type_text:"):
            result = await asyncio.to_thread(_type_text, action[10:])
            await _send_ack(R.from_legacy(result))
            return

        if action.startswith("focus_window:"):
            result = await asyncio.to_thread(_focus_window, action[13:])
            await _send_ack(R.from_legacy(result))
            return

        if action.startswith("switch_to_app:"):
            result = await asyncio.to_thread(_switch_to_app, action[14:])
            await _send_ack(R.from_legacy(result))
            return

        if action.startswith("powershell:"):
            result = await asyncio.to_thread(_powershell, action[11:])
            await _send_ack(R.from_legacy(result))
            return

        # ── Музыка: единый блок диспетчеризации (v3, этап 3) ──────────────
        # Один блок вместо трёх (SMTC / браузер / yamusic_app): бэкенд
        # выбирается по каноническому действию. Канонические имена v3
        # (music.*) принимаются в дополнение к старым — до этапа 8.
        # Громкость музыки — громкость СЕССИИ приложения Яндекс.Музыки на N% (VOLUME_STEP);
        # общая громкость Windows — только system.volume. Нет сессии — честно «noop».
        if action in ("music.volume_up", "music.volume_down",
                      "music:volume_up", "music:volume_down"):
            n = int(arg) if arg.isdigit() and 1 <= int(arg) <= 100 else config.VOLUME_STEP
            up = action.endswith("up")
            await _send_ack(await _yamusic_remote().control("volume_by", n if up else -n))
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
                    # Раньше здесь всегда было ok: true — «Готово» даже при «Нет активного плеера».
                    await _send_ack(R.from_legacy(result), extra={"music": result})
                    log.info(f"[music] command_result отправлен серверу (id={cmd_id})")
                elif _mbackend == "browser":
                    # Перемешать, повтор, перемотка, звук — пульт приложения через SMTC и сессию
                    # (раньше — горячие клавиши в окно Opera, которые до приложения не доходили).
                    verb = _mcanon.split(".", 1)[1]
                    op, value = _REMOTE_OPS.get(verb, (verb, None))
                    await _send_ack(await _yamusic_remote().control(op, value))
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
                        ok, detail = False, f"неизвестная команда: {_mcanon}"
                    res = R.done(detail) if ok else R.from_legacy({"ok": False, "result": detail})
                    await _send_ack(res, extra={"yamusic": True})
            except asyncio.TimeoutError:
                log.error(f"[music] таймаут обработки {_mcanon} (id={cmd_id})")
                await _send_ack(R.failed(f"{_mcanon}: таймаут обработки"))
            except Exception as e:
                log.error(f"music error: {e}")
                await _send_ack(R.failed(f"ошибка музыки: {e}"))
            return

        # Команды через расширение браузера
        if action.startswith("ext:"):
            try:
                import sys as _s
                _ext = _s.modules.get('desktop.core.extension_server')
                if not _ext:
                    log.warning("[ext] Модуль расширения не загружен")
                    await _send_ack(R.unsupported("расширение браузера не загружено"))
                    return
                send_command  = _ext.send_command
                is_connected  = _ext.is_connected
                if not is_connected():
                    log.warning("[ext] Расширение не подключено")
                    await _send_ack(R.unsupported("расширение браузера не подключено"))
                    return
                parts     = action[4:].split(":", 1)
                ext_action = parts[0]
                ext_arg    = parts[1] if len(parts) > 1 else ""
                result    = await send_command(ext_action, ext_arg)
                log.info(f"[ext] {ext_action} → {result}")
                await _send_ack(R.from_legacy(result), extra={"ext": result})
            except Exception as e:
                log.error(f"ext command error: {e}")
                await _send_ack(R.failed(f"ошибка расширения: {e}"))
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
                    # Без расширения — только безопасный путь (см. browser.youtube_player_cmd).
                    from desktop.core.browser import youtube_player_cmd
                    result = await asyncio.to_thread(youtube_player_cmd, action)
                    log.info(f"[yt] {action} без расширения → {result}")
                await _send_ack(R.from_legacy(result))
            except Exception as e:
                log.error(f"youtube error: {e}")
                await _send_ack(R.failed(f"ошибка YouTube: {e}"))
            return

        # Чайник — BLE
        if action.startswith("kettle:"):
            kettle_action = action[len("kettle:"):]
            try:
                from desktop.core.kettle import kettle_command
                result = await kettle_command(kettle_action)
                res = R.from_legacy(result)
                await _send_ack(res, extra={"kettle": result})
                # «Чайник вскипел» — только после успешного включения (раньше `a and b or c`
                # запускал наблюдение и после неудачного boil).
                if res["ok"] and kettle_action.split(":")[0] in ("boil", "boil_heat"):
                    spawn(self._kettle_watch(), name="kettle-watch")
            except Exception as e:
                log.error(f"kettle error: {e}")
                await _send_ack(R.failed(f"ошибка чайника: {e}"))
            return

        # ── Фолбэк: execute_command (hands.py) ──────────────────────
        try:
            # arg приходит отдельно («volume» + «70») — склеиваем в «volume:70»
            full = f"{action}:{arg}" if arg and ":" not in action else action
            out = await asyncio.to_thread(execute_command, full)
            if full in ("system:shutdown", "system:restart") and R.from_legacy(out.get("result"))["ok"]:
                self.bus.emit("power_pending", action=full.split(":")[1], seconds=config.SHUTDOWN_DELAY_S)
            elif full == "system:shutdown_cancel":
                self.bus.emit("power_cancelled")
            if "screenshot" in out:
                if out["screenshot"]:
                    await _send_ack(R.done("скриншот"), extra={"screenshot": out["screenshot"]})
                else:
                    await _send_ack(R.failed("скриншот не получился"))
            else:
                log.info(f"→ {out.get('result')}")
                await _send_ack(R.from_legacy(out.get("result")))
        except Exception as e:
            log.error(f"execute_command error: {e}")
            await _send_ack(R.failed(f"ошибка: {e}"))

    async def _send_result(self, cmd_id: str | None, res: dict, extra: dict | None = None):
        """command_result серверу: {ok, status, detail} + доп. поля. Без id — некуда отвечать."""
        if not cmd_id:
            return
        # Локальный раннер живой проверки (desktop.tools.run_action): ответ — ему, не серверу.
        local = getattr(self, "_local_results", {}).pop(cmd_id, None)
        if local is not None:
            bus = getattr(self, "bus", None)
            if bus is not None:
                bus.emit("command_result", detail=res["detail"], status=res["status"])
            if not local.done():
                local.set_result({**res, **(extra or {})})
            return
        msg = {
            "type": "command_result", "id": cmd_id,
            "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
            "ok": res["ok"], "status": res["status"], "detail": res["detail"],
        }
        if extra:
            msg.update(extra)
        # Строка «действие» в чате (п. 1): «Громкость 70%», «Не получилось: …».
        bus = getattr(self, "bus", None)
        if bus is not None:
            bus.emit("command_result", detail=res["detail"], status=res["status"])
        try:
            await self._ws.send(json.dumps(msg))
        except Exception:
            pass

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
        offline = bool(getattr(config, "OFFLINE", False))
        if not offline and not str(getattr(config, "WS_TOKEN", "") or "").strip():
            log.error("WS_TOKEN не задан в .env")
            # Окно не закрываем — показываем причину в оверлее
            self.bus.emit("agent_alert",
                          text="Не задан WS_TOKEN (.env) — агент не подключается")
            return
        self._loop = asyncio.get_running_loop()
        from desktop.core.app_launch import AppLauncher
        self.app_launcher = AppLauncher()
        from desktop.core.control.confirm import Confirmations
        self.confirmations = Confirmations(lambda ev, **k: self.bus.emit(ev, **k))
        from desktop.core.presence import prime_system_info
        await asyncio.to_thread(prime_system_info)
        # Запускаем локальный WS сервер для расширения браузера
        try:
            import importlib.util as _ilu
            import threading as _th
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

        if not offline:
            spawn(self._heartbeat(), name="agent-heartbeat")
        spawn(self._state_watchdog(), name="state-watchdog")
        spawn(self._level_loop(), name="core-level")
        if not offline:
            spawn(self._screen_analysis_loop(), name="screen-analysis-loop")
        self.hearing.start()

        # Фоновый индекс — не блокируем event loop
        import threading as _th2
        _th2.Thread(target=init_index, daemon=True).start()

        if offline:
            log.info("[agent] SAKURA_OFFLINE: к VPS не подключаюсь (без register и apps_list)")
            self.bus.emit("connection", online=False)
            await asyncio.Event().wait()
            return

        # ── Основной цикл: подключение к VPS ──────────────────────────
        log.info("[agent] Запускаю подключение к VPS: %s", config.VPS_WS_URL)
        from desktop.core import transport as _tr
        try:
            _transport = _tr.make_transport(config.SERVER_TRANSPORT, config.VPS_WS_URL, config.SERVER_CERT_SHA256,
                                            pubkey_sha256=config.SERVER_PUBKEY_SHA256)
            self.transport = _transport
        except _tr.TransportError as e:
            log.error("[agent] транспорт: %s", e)
            self.bus.emit("agent_alert", text=f"Не удалось подключиться к серверу: {e}")
            return
        _backoff = config.RECONNECT_SEC
        while True:
            try:
                log.info("[agent] Подключаюсь к %s (%s)...", config.VPS_WS_URL, _transport.kind)
                async with _tr.session(_transport) as ws:
                    self.bus.emit("transport_state", **dict(getattr(_transport, "state", {}) or {}))
                    await ws.send(json.dumps(await self._payload_async("register")))
                    self._ws = ws
                    if self.server_link is not None:
                        async def _send_v2(msg, _ws=ws):
                            await _ws.send(json.dumps(msg, ensure_ascii=False))
                        self.server_link.on_connected(_send_v2)
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
            if self.server_link is not None:
                self.server_link.on_disconnected()
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
                        "active_window": await asyncio.to_thread(get_active_window),
                    }))
                    log.debug("[screen] Скриншот отправлен для анализа")
            except Exception as e:
                log.debug(f"[screen] Ошибка: {e}")
