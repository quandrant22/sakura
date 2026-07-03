"""core/agent.py — нервная система тела: связь с VPS и оркестрация органов.

Тело не знает про интерфейс. О своём состоянии и репликах оно сообщает через
шину событий (bus); оболочка/оверлей на неё подписана.

v2.0: Uses typed protocol for IPC communication.
"""

import asyncio
import base64
import json
import logging
import time

import websockets

import config
from core.eyes import get_active_window, get_system_info
from core.hands import execute_command, scan_start_menu
from core.hearing import Hearing
from core.voice import Player
from core.protocol import (
    Event, Registered, Ping, VoiceCommand, CommandResult, AppsList,
    Action, Command, TTSChunk, TTSEnd, Reply, MoodUpdate,
    Capabilities, parse_action,
)

log = logging.getLogger("sakura.agent")


class Agent:
    def __init__(self, bus):
        self.bus     = bus
        self.state   = "idle"
        self.player  = Player(config.TTS_RATE)
        self.hearing = Hearing(self)
        self._ws     = None
        self._loop   = None
        self._capabilities = Capabilities.detect()
        self._request_counter = 0

    # ── состояние для оболочки ──────────────────────────────────────
    def set_state(self, state: str):
        self.state = state
        self.bus.emit("state", value=state)

    # ── единая точка ввода: голос и текст идут одним путём ──────────
    def submit_user_text(self, text: str):
        text = text.strip()
        if not text:
            return
        self.bus.emit("user_text", text=text)
        self.set_state("thinking")
        event = VoiceCommand(
            device_id=config.DEVICE_ID,
            text=text,
            active_window=get_active_window(),
            context=[],
        )
        self.send_threadsafe(json.loads(event.to_json()))

    def send_threadsafe(self, obj: dict):
        """Отправка из фоновых потоков (слух, UI) в asyncio-цикл связи."""
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(obj)), self._loop)

    # ── телеметрия ──────────────────────────────────────────────────
    def _make_event(self, event_class, **kwargs):
        """Create a typed event with device_id and system_info."""
        return event_class(
            device_id=config.DEVICE_ID,
            active_window=get_active_window(),
            system_info=get_system_info(),
            **kwargs,
        )

    async def _heartbeat(self):
        last_window, last_ping = None, 0.0
        while True:
            await asyncio.sleep(config.WINDOW_POLL)
            if not self._ws:
                continue
            window, now = get_active_window(), time.monotonic()
            if window != last_window or (now - last_ping) >= config.PING_INTERVAL:
                try:
                    event = Ping(
                        device_id=config.DEVICE_ID,
                        active_window=window,
                        system_info=get_system_info(),
                    )
                    await self._ws.send(event.to_json())
                    last_window, last_ping = window, now
                except Exception:
                    pass

    async def _recv_loop(self):
        async for raw in self._ws:
            try:
                data = json.loads(raw)
                action = parse_action(data)

                if action is None:
                    log.warning(f"Unknown action type: {data.get('type')}")
                    continue

                if isinstance(action, Command):
                    asyncio.create_task(self._run_command(action))
                elif isinstance(action, TTSChunk):
                    self.set_state("speaking")
                    self.player.feed(base64.b64decode(action.audio))
                elif isinstance(action, TTSEnd):
                    self.set_state("idle")
                elif isinstance(action, Reply):
                    text = (action.text or "").strip()
                    if text:
                        self.bus.emit("sakura_text", text=text)
                elif isinstance(action, MoodUpdate):
                    self.bus.emit("mood_update", params=action.params)
                else:
                    log.debug(f"Unhandled action: {type(action).__name__}")

            except Exception as e:
                log.error(f"recv: {e}")

    async def _run_command(self, action: Command):
        """Execute a command received from VPS."""
        if not action.target:
            return

        log.info(f"command: {action.target}:{action.args}")

        # Build the full action string for legacy execute_command
        full_action = f"{action.target}:{action.args}" if action.args else action.target

        out = await asyncio.to_thread(execute_command, full_action)

        # Send result back to VPS
        result = CommandResult(
            device_id=config.DEVICE_ID,
            action=full_action,
            result=out.get("result", ""),
            success=not out.get("error"),
            screenshot=out.get("screenshot", ""),
        )
        try:
            await self._ws.send(result.to_json())
        except Exception as e:
            log.error(f"Failed to send command result: {e}")

        if out.get("result"):
            log.info(f"→ {out['result']}")

    async def run(self):
        self._loop = asyncio.get_running_loop()
        asyncio.create_task(self._heartbeat())
        self.hearing.start()

        while True:
            try:
                async with websockets.connect(
                    config.VPS_WS_URL,
                    ping_interval=20,
                    proxy=None,
                    max_size=None,
                ) as ws:
                    self._ws = ws

                    # Send registration with capabilities
                    register = Registered(
                        device_id=config.DEVICE_ID,
                        active_window=get_active_window(),
                        system_info=get_system_info(),
                        capabilities=self._capabilities,
                        version="2.0",
                    )
                    if config.WS_TOKEN:
                        register_dict = json.loads(register.to_json())
                        register_dict["token"] = config.WS_TOKEN
                        await ws.send(json.dumps(register_dict))
                    else:
                        await ws.send(register.to_json())

                    # Send apps list
                    apps = scan_start_menu()
                    if apps:
                        apps_event = AppsList(
                            device_id=config.DEVICE_ID,
                            apps=apps,
                        )
                        await ws.send(apps_event.to_json())

                    self.bus.emit("connection", online=True)
                    log.info(f"Подключено. Приложений: {len(apps)}. Capabilities: {self._capabilities}")
                    await self._recv_loop()

            except Exception as e:
                log.warning(f"WS обрыв: {e} — реконнект через {config.RECONNECT_SEC}с")
            self._ws = None
            self.bus.emit("connection", online=False)
            await asyncio.sleep(config.RECONNECT_SEC)
