"""desktop.core.service — сборка ядра: Agent + ServerLink + локальный API.

Шина событий агента (EventBus) переводится в события локального API
(PROTOCOL.md, «Ядро ↔ интерфейс»); команды интерфейса вызывают агента,
hands и ServerLink. Всё живёт в одном asyncio-цикле с агентом.
"""
import asyncio
import logging
import os
import time

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
                                               "output_device"}
# Встроенный сценарий «Фокус» на сервере.
FOCUS_SCENARIO_ID = "focus"


class CoreService:
    def __init__(self, agent_factory=None, api: LocalApiServer | None = None,
                 settings=None, hands=None):
        from desktop.core.events import EventBus
        self.bus = EventBus()
        self.link = ServerLink(auth=self._auth, on_push=self._on_push, on_state=self._emit)
        self.api = api or LocalApiServer(token_path=default_token_path(),
                                         restrict=self._restrict, snapshot=self.snapshot)
        self.api._snapshot = self.snapshot
        if agent_factory is None:
            from desktop.core.agent import Agent
            agent_factory = Agent
        self.agent = agent_factory(self.bus, server_link=self.link)
        if settings is None:
            from desktop.core.settings import Settings
            settings = Settings(os.path.join(config.DATA_DIR, "ui_settings.json"))
        self.settings = settings
        if hands is None:
            from desktop.core import hands
        self.hands = hands
        self._state = "idle"
        self.bus.subscribe(self._on_bus)
        self._register_commands()

    # ── вспомогательное ────────────────────────────────────────────
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
        out = dict(DEFAULT_SETTINGS)
        out.update({k: v for k, v in self.settings.items().items() if k in SETTINGS_KEYS})
        out["device_id"] = config.DEVICE_ID
        out["extension_id"] = os.getenv("SAKURA_EXTENSION_ID", "")
        out["mic_enabled"] = bool(getattr(self.agent.hearing, "mic_enabled", True))
        return out

    def snapshot(self) -> list[dict]:
        return [self.link.state_event(),
                {"type": "state", "value": self._state, "level": 0},
                {"type": "settings", "settings": self.settings_snapshot()}]

    # ── шина → API ─────────────────────────────────────────────────
    def _local_chat(self, role: str, text: str):
        # Сервер v1 не шлёт chat_message — собираем сообщение из событий агента.
        if self.link.proto == 2:
            return
        self._emit({"type": "chat_message", "message": {
            "id": f"local-{time.time_ns()}", "ts": time.time(), "role": role,
            "text": text, "channel": "voice", "device": config.DEVICE_ID}})

    def _on_bus(self, event: str, data: dict):
        if event == "state" and data.get("value") in STATES:
            self._state = data["value"]
            self._emit({"type": "state", "value": self._state, "level": 0})
        elif event == "user_text":
            self._emit({"type": "transcript", "text": data.get("text", ""), "final": True})
            self._local_chat("user", data.get("text", ""))
        elif event == "sakura_text":
            self._local_chat("assistant", data.get("text", ""))
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
        c("quick_action", self.cmd_quick_action)
        c("list_apps", self.cmd_list_apps)
        c("list_audio_devices", self.cmd_list_audio_devices)
        c("settings_set", self.cmd_settings_set)
        c("server", self.cmd_server)

    async def cmd_send_text(self, msg: dict):
        text = str(msg.get("text") or "").strip()
        if not text:
            raise ApiError("bad_request", "пустое сообщение")
        self.agent.submit_user_text(text, channel="text")

    async def cmd_mic_toggle(self, msg: dict):
        hearing = self.agent.hearing
        on = msg.get("on")
        hearing.mic_enabled = (not hearing.mic_enabled) if on is None else bool(on)
        self._emit({"type": "settings", "settings": self.settings_snapshot()})
        return {"mic": hearing.mic_enabled}

    async def cmd_stop_speaking(self, msg: dict):
        self.agent.player.interrupt()
        self.agent.set_state("idle")

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
        snap = self.settings_snapshot()
        self._emit({"type": "settings", "settings": snap})
        return {"settings": snap}

    async def cmd_server(self, msg: dict):
        inner = msg.get("message")
        if not isinstance(inner, dict) or not inner.get("type"):
            raise ApiError("bad_request", "нет message.type")
        return await self.link.request(inner)

    # ── запуск ─────────────────────────────────────────────────────
    async def run(self, api_port: int = 0):
        await self.api.start(api_port)
        await self.agent.run()
