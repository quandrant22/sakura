"""desktop.core.service — сборка ядра: Agent + ServerLink + локальный API.

Шина событий агента (EventBus) переводится в события локального API
(PROTOCOL.md, «Ядро ↔ интерфейс»); команды интерфейса вызывают агента,
hands и ServerLink. Всё живёт в одном asyncio-цикле с агентом.
"""
import asyncio
import logging
import os
import uuid

from desktop.core import config
from desktop.core.api.server import ApiError, LocalApiServer, default_token_path
from desktop.core.server_link import ServerLink

log = logging.getLogger("sakura.service")

STATES = ("idle", "listening", "thinking", "speaking")
DEFAULT_SETTINGS = {
    "quick_prompts": ["Что у меня сегодня?", "Погода", "Включи музыку"],
    "language": "ru",
    "theme": "sakura-night",
}
# Ключи настроек, которые интерфейс может менять (остальное — через .env).
SETTINGS_KEYS = frozenset(DEFAULT_SETTINGS) | {"autostart", "game_processes", "wake_sensitivity",
                                               "stt_model", "hotkey_talk", "input_device",
                                               "output_device", "music_accessibility"}
# Встроенный сценарий «Фокус» на сервере.
FOCUS_SCENARIO_ID = "focus"


# Допустимые источники send_text (метка сообщения в чате).
TEXT_SOURCES = ("ui", "e2e", "api")


class CoreService:
    def __init__(self, agent_factory=None, api: LocalApiServer | None = None,
                 settings=None, hands=None, media=None):
        from desktop.core.events import EventBus
        self.bus = EventBus()
        self.link = ServerLink(auth=self._auth, on_push=self._on_push, on_state=self._emit)
        self.api = api or LocalApiServer(token_path=default_token_path(),
                                         restrict=self._restrict, snapshot=self.snapshot)
        self.api._snapshot = self.snapshot
        # Без фабрики агент создаётся в run() после старта API: конструктор грузит
        # модели распознавания (~1 мин), интерфейс за это время уже подключается.
        self._agent_factory = agent_factory
        self._agent = agent_factory(self.bus, server_link=self.link) if agent_factory else None
        if settings is None:
            from desktop.core.settings import Settings
            settings = Settings(os.path.join(config.DATA_DIR, "ui_settings.json"))
        self.settings = settings
        if hands is None:
            from desktop.core import hands
        self.hands = hands
        # Встроенные плееры (desktop.core.media). media=False — без них (тесты).
        if media is None:
            from desktop.core.media.service import MediaService
            media = MediaService(self._emit, self.settings)
        self.media = media or None
        if self._agent is not None:
            self._agent.media = self.media
        self._state = "idle"
        # Ходы чата: все реплики Сакуры, результаты команд, заглушка «звук без текста».
        from desktop.core.chat_turns import ChatTurns
        self.chat = ChatTurns(self._chat_emit, device=config.DEVICE_ID, schedule=self._later)
        self.bus.subscribe(self._on_bus)
        self._register_commands()

    # ── вспомогательное ────────────────────────────────────────────
    @property
    def agent(self):
        if self._agent is None:
            raise ApiError("starting", "ядро ещё запускается")
        return self._agent

    @staticmethod
    def _auth() -> dict:
        return {"device_id": config.DEVICE_ID, "token": config.WS_TOKEN.strip()}

    @staticmethod
    def _restrict(path: str):
        from desktop.core.platform import get_platform
        get_platform().restrict_to_current_user(path)

    def _emit(self, event: dict):
        self.api.emit_threadsafe(event)

    def settings_snapshot(self) -> dict:
        from desktop.core import app_launch
        saved = self.settings.items().get("music_accessibility")
        if saved is not None:
            app_launch.PREFS["yandex_music"] = bool(saved)
        out = dict(DEFAULT_SETTINGS)
        out.update({k: v for k, v in self.settings.items().items() if k in SETTINGS_KEYS})
        out["music_accessibility"] = app_launch.PREFS.get("yandex_music", True)
        out["device_id"] = config.DEVICE_ID
        out["extension_id"] = os.getenv("SAKURA_EXTENSION_ID", "")
        hearing = getattr(self._agent, "hearing", None)
        out["mic_enabled"] = bool(getattr(hearing, "mic_enabled", True))
        out["core_ready"] = self._agent is not None
        return out

    def snapshot(self) -> list[dict]:
        snap = [self.link.state_event(),
                {"type": "state", "value": self._state, "level": 0},
                {"type": "settings", "settings": self.settings_snapshot()}]
        if self.media is not None:
            snap.append({"type": "media_settings", "settings": self.media.snapshot()})
        return snap

    # ── шина → API ─────────────────────────────────────────────────
    def _chat_emit(self, event: dict):
        # Сервер v2 сам шлёт chat_message с репликами — их не дублируем; строки команд
        # и заглушка «звук без текста» — только от клиента, их показываем всегда.
        msg = event.get("message") or {}
        if self.link.proto == 2 and msg.get("kind") not in ("command", "voice_only") and msg.get("role") != "system":
            return
        self._emit(event)

    @staticmethod
    def _later(delay: float, fn):
        import threading
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()

    def _on_bus(self, event: str, data: dict):
        if event == "state" and data.get("value") in STATES:
            # Агент повторяет «speaking» на каждый аудио-чанк — интерфейсу нужна только смена.
            if data["value"] == self._state:
                return
            self._state = data["value"]
            if self.media is not None:
                self.media.on_voice_state(self._state)
            self._emit({"type": "state", "value": self._state, "level": 0})
            if self._state == "speaking":
                self.chat.audio()
        elif event == "user_text":
            source = data.get("source", "mic")
            self._emit({"type": "transcript", "text": data.get("text", ""), "final": True, "source": source})
            self.chat.user(data.get("text", ""), source)
        elif event == "sakura_text":
            self.chat.reply(data.get("text", ""), kind=data.get("kind"), turn_id=data.get("turn_id"),
                            ts=data.get("ts"))
        elif event == "command_result":
            self.chat.command(data.get("detail", ""), data.get("status", "failed"), data.get("action", ""))
        elif event == "tts_end":
            self.chat.tts_end()
        elif event == "power_pending":
            what = "Перезагружаю" if data.get("action") == "restart" else "Выключаю"
            seconds = int(data.get("seconds") or 0)
            self._emit({"type": "power_pending", "action": data.get("action"), "seconds": seconds})
            self.chat.reply(f"{what} компьютер через {seconds} секунд. Скажи «отмени», чтобы остановить.",
                            kind="proactive")
        elif event == "power_cancelled":
            self._emit({"type": "power_cancelled"})
        elif event == "pc_action":
            # Индикатор в трее на время действия с компьютером.
            self._emit({"type": "pc_action", "active": bool(data.get("active"))})
        elif event == "agent_alert":
            self._emit({"type": "notify", "text": data.get("text", ""), "level": "warn"})
        elif event == "game_mode":
            self._emit({"type": "game_mode", "on": bool(data.get("on"))})
        elif event in ("orb_arrival", "orb_departure"):
            self._emit({"type": event})
        elif event == "mood_update":
            self._emit({"type": "mood", "params": data.get("params") or {}})

    def _on_push(self, msg: dict):
        self._emit(msg)

    # ── команды интерфейса ─────────────────────────────────────────
    def _register_commands(self):
        c = self.api.command
        c("send_text", self.cmd_send_text)
        c("mic_toggle", self.cmd_mic_toggle)
        c("stop_speaking", self.cmd_stop_speaking)
        c("listen_now", self.cmd_listen_now)
        c("window_ask", self.cmd_window_ask)
        c("power_cancel", self.cmd_power_cancel)
        c("quick_action", self.cmd_quick_action)
        c("list_apps", self.cmd_list_apps)
        c("list_audio_devices", self.cmd_list_audio_devices)
        c("settings_set", self.cmd_settings_set)
        c("game_mode", self.cmd_game_mode)
        c("apps_state", self.cmd_apps_state)
        c("music_ui_ack", self.cmd_music_ui_ack)
        c("music_metrics", self.cmd_music_metrics)
        c("app_restart", self.cmd_app_restart)
        c("secrets_status", self.cmd_secrets_status)
        c("secrets_set", self.cmd_secrets_set)
        c("core_restart", self.cmd_core_restart)
        if os.getenv("SAKURA_LIVECHECK") == "1":
            c("run_action", self.cmd_run_action)
        if self.media is not None:
            self.media.register(c)
        c("server", self.cmd_server)

    async def cmd_send_text(self, msg: dict):
        text = str(msg.get("text") or "").strip()
        if not text:
            raise ApiError("bad_request", "пустое сообщение")
        # Источник виден в чате: окно (ui), проверка (e2e) или другой клиент API.
        source = msg.get("source") if msg.get("source") in TEXT_SOURCES else "api"
        self.agent.submit_user_text(text, channel="text", source=source)

    async def cmd_mic_toggle(self, msg: dict):
        hearing = self.agent.hearing
        on = msg.get("on")
        hearing.mic_enabled = (not hearing.mic_enabled) if on is None else bool(on)
        self._emit({"type": "settings", "settings": self.settings_snapshot()})
        return {"mic": hearing.mic_enabled}

    async def cmd_stop_speaking(self, msg: dict):
        # «стоп»: озвучка прерывается, встроенные плееры — на паузу.
        self.agent.player.interrupt()
        self.agent.set_state("idle")
        if self.media is not None:
            self.media.audio.stop_all()

    async def cmd_listen_now(self, msg: dict):
        # «Говорить сейчас» (короткий клик по ядру): без слова «Сакура» — открываем окно
        # дослушивания; если Сакура говорит, озвучка прерывается.
        hearing = self.agent.hearing
        if not hearing.mic_enabled:
            raise ApiError("mic_off", "микрофон выключен")
        self.agent.player.interrupt()
        hearing.open_followup()
        self.agent.set_state("listening")

    # Один кадр окна — серверу на описание, только по явному нажатию «Спросить про окно».
    # Кадр не пишется на диск и не попадает в лог; размер ограничен.
    WINDOW_ASK_MAX_B64 = 2_000_000

    async def cmd_window_ask(self, msg: dict):
        image = str(msg.get("image") or "")
        question = str(msg.get("question") or "Что в этом окне?").strip()[:500]
        if not image or len(image) > self.WINDOW_ASK_MAX_B64:
            raise ApiError("bad_request", "нет кадра или он слишком большой")
        if self.link.proto != 2:
            raise ApiError("unsupported", "сервер не поддерживает")
        log.info("[window_ask] кадр %d КиБ отправлен по запросу пользователя", len(image) * 3 // 4 // 1024)
        return await self.link.request({"type": "vision_request", "image": image, "question": question})

    async def cmd_run_action(self, msg: dict):
        """Живая проверка: действие напрямую в диспетчер агента (только при SAKURA_LIVECHECK=1)."""
        action = str(msg.get("action") or "").strip()
        if not action:
            raise ApiError("bad_request", "нет действия")
        cmd_id = f"local:{uuid.uuid4().hex[:8]}"
        fut = asyncio.get_running_loop().create_future()
        if not hasattr(self.agent, "_local_results"):
            self.agent._local_results = {}
        self.agent._local_results[cmd_id] = fut
        log.info("[livecheck] %s", action)
        await self.agent._run_command(action, cmd_id, str(msg.get("arg") or ""), confirmed=msg.get("confirmed") is True)
        try:
            return await asyncio.wait_for(fut, timeout=30)
        except asyncio.TimeoutError:
            return {"ok": False, "status": "failed", "detail": "нет ответа от действия за 30 с"}
        finally:
            self.agent._local_results.pop(cmd_id, None)

    # ── Настройки → Приложения: параметры запуска (белый список) ──
    async def cmd_apps_state(self, msg: dict):
        from desktop.core import app_launch
        st = await asyncio.to_thread(app_launch.AppLauncher().state, "yandex_music")
        return {"yandex_music": {**st, "enabled": app_launch.PREFS.get("yandex_music", True),
                                 "args": app_launch.default_args("yandex_music")}}

    async def cmd_app_restart(self, msg: dict):
        from desktop.core import app_launch
        key = app_launch.app_key(str(msg.get("app") or "yandex_music"))
        if key is None:
            raise ApiError("bad_request", "это приложение нельзя перезапускать из Сакуры")
        return await asyncio.to_thread(app_launch.AppLauncher().restart, key)

    # ── «Секреты»: только «задан / не задан» и запись; значения не возвращаются и не журналируются ──
    async def cmd_secrets_status(self, msg: dict):
        from desktop.core import envfile
        path = envfile.env_path()
        return {"env_file": path, "exists": bool(path and os.path.isfile(path)), "keys": envfile.status(path)}

    async def cmd_secrets_set(self, msg: dict):
        from desktop.core import envfile
        path = envfile.env_path()
        if not path:
            raise ApiError("unsupported", "файл .env не найден — запустите Сакуру ярлыком или задайте SAKURA_ENV_FILE")
        try:
            await asyncio.to_thread(envfile.set_secret, path, str(msg.get("key") or ""), msg.get("value"),
                                    self._restrict)
        except envfile.SecretError as e:
            raise ApiError("bad_request", str(e)) from None
        return {"keys": envfile.status(path), "restart_suggested": True}

    async def cmd_core_restart(self, msg: dict):
        """Перезапуск ядра (новые значения .env): окно (CoreSupervisor) запустит ядро заново."""
        log.info("[core] перезапуск по запросу интерфейса")
        asyncio.get_running_loop().call_later(0.3, os._exit, 0)
        return {"restarting": True}

    async def cmd_power_cancel(self, msg: dict):
        """Кнопка «Отмена» в тосте выключения — то же, что «отмени выключение»."""
        from desktop.core.platform import get_platform
        await asyncio.to_thread(get_platform().power, "shutdown_cancel")
        self._emit({"type": "power_cancelled"})
        self.chat.command("выключение отменено", "done")
        return {"ok": True}

    async def cmd_quick_action(self, msg: dict):
        kind, arg = msg.get("id"), msg.get("arg")
        if kind == "screenshot":
            jpeg_b64 = await asyncio.to_thread(self.hands.take_screenshot)  # base64 JPEG
            if not jpeg_b64:
                raise ApiError("failed", "скриншот не получился")
            return {"image": jpeg_b64}
        if kind == "open_app":
            if not arg:
                raise ApiError("bad_request", "не указано приложение")
            return {"text": await asyncio.to_thread(self.hands.open_app, str(arg))}
        if kind == "focus_mode":
            return await self.link.request({"type": "scenario_run", "id": FOCUS_SCENARIO_ID})
        if kind == "run_scenario":
            if not arg:
                raise ApiError("bad_request", "не указан сценарий")
            return await self.link.request({"type": "scenario_run", "id": str(arg)})
        raise ApiError("bad_request", f"неизвестное быстрое действие: {kind}")

    async def cmd_list_apps(self, msg: dict):
        apps = self.hands._app_cache or await asyncio.to_thread(self.hands.scan_apps)
        return {"apps": [{"name": n} for n in sorted(apps)]}

    async def cmd_list_audio_devices(self, msg: dict):
        try:
            import sounddevice as sd
        except ImportError:
            raise ApiError("unavailable", "sounddevice недоступен") from None
        devs = sd.query_devices()
        default_in, default_out = sd.default.device
        inputs = [{"id": i, "name": d["name"], "default": i == default_in}
                  for i, d in enumerate(devs) if d["max_input_channels"] > 0]
        outputs = [{"id": i, "name": d["name"], "default": i == default_out}
                   for i, d in enumerate(devs) if d["max_output_channels"] > 0]
        return {"inputs": inputs, "outputs": outputs}

    async def cmd_settings_set(self, msg: dict):
        key = msg.get("key")
        if key not in SETTINGS_KEYS:
            raise ApiError("bad_request", f"нельзя менять настройку: {key}")
        self.settings.set(key, msg.get("value"))
        if key == "music_accessibility":
            from desktop.core import app_launch
            app_launch.PREFS["yandex_music"] = bool(msg.get("value"))
        snap = self.settings_snapshot()
        self._emit({"type": "settings", "settings": snap})
        return {"settings": snap}

    async def cmd_game_mode(self, msg: dict):
        # Тот же путь, что команда сервера game_mode:on/off — событие шины (оверлей, трей).
        on = bool(msg.get("on"))
        self.bus.emit("game_mode", on=on)
        return {"on": on}

    async def cmd_server(self, msg: dict):
        inner = msg.get("message")
        if not isinstance(inner, dict) or not inner.get("type"):
            raise ApiError("bad_request", "нет message.type")
        return await self.link.request(inner)

    # ── запуск ─────────────────────────────────────────────────────
    # ── мгновенный трек (события SMTC → окно ≤ 300 мс) ──
    MUSIC_METRIC_N = 200

    def _on_music_state(self, st: dict, t_event: float | None):
        import collections
        if not hasattr(self, "_music_t"):
            self._music_t, self._music_ms = {}, collections.deque(maxlen=self.MUSIC_METRIC_N)
            self._covers = {}
        if t_event is not None:
            self._music_t[st["seq"]] = t_event
            while len(self._music_t) > 50:
                self._music_t.pop(next(iter(self._music_t)))
        self._emit({"type": "music_state", "state": st})
        if st.get("status") == "ok":
            track = {k: st.get(k) for k in ("title", "artist", "album")}
            track["status"] = "играет" if st.get("playing") else "пауза"
            agent = self._agent
            if agent is not None:
                agent._current_track = {**getattr(agent, "_current_track", {}), **track}
                if st.get("changed") in ("track", "restart"):
                    push = getattr(agent, "push_current_track", None)
                    if push is not None:
                        asyncio.ensure_future(push())
            if st.get("changed") == "track":
                asyncio.ensure_future(self._music_cover(st))

    async def _music_cover(self, st: dict):
        """Обложка — асинхронно, после текста; кэш по (artist, title, album)."""
        from desktop.core.media.smtc_watch import track_key
        key = track_key(st)
        cover = self._covers.get(key)
        if cover is None:
            try:
                from desktop.core import music
                from desktop.core.media.yandex_remote import _cover_url
                cover = _cover_url(await music.smtc_cover()) or ""
            except Exception:  # noqa: BLE001
                cover = ""
            if len(self._covers) > 64:
                self._covers.pop(next(iter(self._covers)))
            self._covers[key] = cover
        if cover:
            self._emit({"type": "music_cover", "seq": st["seq"], "cover": cover})

    async def cmd_music_ui_ack(self, msg: dict):
        """Окно применило music_state: время «событие SMTC → окно»."""
        import time as _t
        t0 = getattr(self, "_music_t", {}).pop(msg.get("seq"), None)
        if t0 is None:
            return None
        ms = int((_t.monotonic() - t0) * 1000)
        self._music_ms.append(ms)
        log.info("[music] event→ui %d ms", ms)
        return {"ms": ms}

    async def cmd_music_metrics(self, msg: dict):
        vals = sorted(getattr(self, "_music_ms", []))
        if not vals:
            return {"count": 0}
        pick = lambda q: vals[min(len(vals) - 1, int(q * len(vals)))]  # noqa: E731
        return {"count": len(vals), "p50": pick(0.5), "p95": pick(0.95), "max": vals[-1]}

    async def _start_music_watch(self):
        if os.name != "nt":
            return
        try:
            from desktop.core.media.smtc_watch import SmtcWatch
            self._music_watch = SmtcWatch(self._on_music_state)
            await self._music_watch.start()
        except Exception as e:  # noqa: BLE001
            log.warning("[music] наблюдатель SMTC не запущен: %s", type(e).__name__)

    async def run(self, api_port: int = 0):
        await self.api.start(api_port)
        asyncio.ensure_future(self._start_music_watch())
        if self.media is not None:
            self.media.start()
            self._emit({"type": "media_settings", "settings": self.media.snapshot()})
        if self._agent is None:
            from desktop.core.agent import Agent
            factory = self._agent_factory or Agent
            # Конструктор тяжёлый (модели STT) — в потоке, чтобы API отвечал.
            self._agent = await asyncio.to_thread(factory, self.bus, server_link=self.link)
            self._agent.media = self.media
            self._emit({"type": "settings", "settings": self.settings_snapshot()})
        await self._agent.run()
