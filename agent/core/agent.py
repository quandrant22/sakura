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
import sys as _sys

# Гарантируем что корень Sakura/ в sys.path (нужно для core.* импортов в тредах)
_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _root not in _sys.path:
    _sys.path.insert(0, _root)
import logging
import time

import websockets

import config
from core.eyes import get_active_window, get_system_info
from core.hands import execute_command, scan_apps, init_index
from core.hands import hotkey as _hotkey, type_text as _type_text
from core.hands import focus_window as _focus_window, powershell as _powershell
from core.hearing import Hearing
from core.voice import Player
from core.local_mood import LocalMood

log = logging.getLogger("sakura.agent")


class Agent:
    def __init__(self, bus):
        self.bus     = bus
        self.state   = "idle"
        self.player  = Player(config.TTS_RATE)
        self.hearing = Hearing(self)
        self._ws     = None
        self._loop   = None
        self.last_voice_prosody = None
        self._last_window    = ""
        self._window_since   = time.monotonic()
        self._activity_level = 0.0
        self.local_mood = LocalMood()
        self._last_mood_update = {}  # последний mood_update от сервера
        self._abort_flag = False     # аварийный тормоз (abort_all)

    def set_state(self, state: str):
        self.state = state
        self.bus.emit("state", value=state)

    def submit_user_text(self, text: str):
        text = text.strip()
        if not text:
            return
        self.bus.emit("user_text", text=text)
        self.set_state("thinking")
        self.send_threadsafe({
            "type":          "voice_command",
            "device_id":     config.DEVICE_ID,
            "token":         config.WS_TOKEN.strip(),
            "text":          text,
            "active_window": get_active_window(),
            "context":       [],
        })

    def send_threadsafe(self, obj: dict):
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps(obj)), self._loop
            )

    def _payload(self, kind: str) -> dict:
        # Расширенная системная информация (температуры, диск)
        try:
            from core.presence import get_extended_system_info
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
            from core.presence import get_activity_level
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
        # Добавляем текущий трек через SMTC
        try:
            import asyncio as _aio
            from core.music import _smtc_get_info
            loop = _aio.get_event_loop()
            if loop.is_running():
                future = _aio.run_coroutine_threadsafe(_smtc_get_info(), loop)
                track = future.result(timeout=1.0)
                if track and track.get("title"):
                    payload["current_track"] = track
        except Exception:
            pass
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
                    from core.music import get_current_track
                    track = get_current_track()
                except Exception:
                    track = None

                # Температура ноутбука
                cpu_temp = None
                try:
                    from core.presence import get_extended_system_info
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
                    self.set_state("speaking")
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
                    asyncio.create_task(self._run_command(_action, _cmd_id))

                elif kind == "tts_chunk":
                    # При первом чанке нового ответа — сбрасываем буфер
                    if self.state != "speaking":
                        self.player.interrupt()
                    self.set_state("speaking")
                    self.player.feed(base64.b64decode(data["audio"]))

                elif kind == "tts_end":
                    self.player.flush()
                    self.set_state("idle")

                elif kind == "reply":
                    text = (data.get("text") or "").strip()
                    if text:
                        self.bus.emit("sakura_text", text=text)

                elif kind == "mood_update":
                    params = data.get("params", {})
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

    async def _run_command(self, action: str, cmd_id: str | None = None):
        if not action:
            return
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

        if action.startswith("powershell:"):
            if self._abort_flag:
                await _send_ack(False, "прервано abort_all")
                return
            result = await asyncio.to_thread(_powershell, action[11:])
            await _send_ack(result.get("ok", False), result.get("detail", ""))
            return

        # Яндекс Музыка + SMTC
        _music_action = None
        if action.startswith("music_"):
            _music_action = action
        elif action in ("music:next", "music:prev", "music:play_pause"):
            _music_action = action.replace("music:", "music_")
        elif action in ("music:like", "music:dislike"):
            _music_action = action.replace("music:", "music_")
        if _music_action:
            try:
                from core.music import music_command
                result = await music_command(_music_action)
                result["action"] = _music_action
                await self._ws.send(json.dumps({
                    "type": "command_result", "id": cmd_id,
                    "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                    "ok": True, "detail": result.get("result", ""),
                    "music": result,
                }))
            except Exception as e:
                log.error(f"music error: {e}")
                await _send_ack(False, f"music error: {e}")
            return

        # Команды через расширение браузера
        if action.startswith("ext:"):
            try:
                import sys as _s
                _ext = _s.modules.get('core.extension_server')
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
                _ext = __import__('sys').modules.get('core.extension_server')
                if _ext and _ext.is_connected():
                    result = await _ext.send_command(action)
                    log.info(f"[yt] {action} via extension → {result}")
                else:
                    from core.browser import youtube_player_cmd
                    result = youtube_player_cmd(action)
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
                from core.kettle import kettle_command
                result = await kettle_command(kettle_action)
                await self._ws.send(json.dumps({
                    "type": "command_result", "id": cmd_id,
                    "device_id": config.DEVICE_ID, "token": config.WS_TOKEN,
                    "ok": result.get("ok", False), "detail": result.get("result", ""),
                    "kettle": result,
                }))
                if result.get("ok") and kettle_action in ("boil", "boil_heat") or kettle_action.startswith("boil"):
                    asyncio.create_task(self._kettle_watch())
            except Exception as e:
                log.error(f"kettle error: {e}")
                await _send_ack(False, f"kettle error: {e}")
            return

        # ── Фолбэк: execute_command (hands.py) ──────────────────────
        try:
            out = await asyncio.to_thread(execute_command, action)
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
        from core.kettle import kettle_command

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
        self._loop = asyncio.get_running_loop()
        # Запускаем локальный WS сервер для расширения браузера
        try:
            import importlib.util as _ilu, os as _o, threading as _th
            _srv = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), 'extension_server.py')
            _spec = _ilu.spec_from_file_location('extension_server', _srv)
            _mod  = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            import sys as _s; _s.modules['core.extension_server'] = _mod
            _mod.set_agent_loop(asyncio.get_event_loop())

            def _run_ext_server():
                import asyncio as _aio, time as _ti
                while True:
                    try:
                        _loop = _aio.new_event_loop()
                        _aio.set_event_loop(_loop)
                        _loop.run_until_complete(_mod.start())
                    except Exception as _e:
                        log.warning(f"[extension] Сервер упал: {_e}, перезапуск через 5с")
                        _ti.sleep(5)
                    finally:
                        try:
                            _loop.close()
                        except Exception:
                            pass

            _ext_thread = _th.Thread(target=_run_ext_server, daemon=True, name="extension-server")
            _ext_thread.start()
        except Exception as _ext_e:
            log.warning(f"[extension] Не удалось запустить сервер: {_ext_e}")

        asyncio.create_task(self._heartbeat())
        asyncio.create_task(self._screen_analysis_loop())
        self.hearing.start()

        # Фоновый индекс — не блокируем event loop
        import threading as _th2
        _th2.Thread(target=init_index, daemon=True).start()

        # ── Основной цикл: подключение к VPS ──────────────────────────
        import sys as _sys
        print(f"[agent] Запускаю подключение к VPS: {config.VPS_WS_URL}", flush=True)
        _sys.stdout.flush()
        while True:
            try:
                print(f"[agent] Подключаюсь к {config.VPS_WS_URL}...", flush=True)
                _sys.stdout.flush()
                async with websockets.connect(
                    config.VPS_WS_URL,
                    ping_interval=20,
                    proxy=None,
                    max_size=None,
                ) as ws:
                    self._ws = ws
                    await ws.send(json.dumps(self._payload("register")))
                    apps = scan_apps()
                    if apps:
                        await ws.send(json.dumps({
                            "type":      "apps_list",
                            "device_id": config.DEVICE_ID,
                            "token":     config.WS_TOKEN,
                            "apps":      apps,
                        }))
                    self.bus.emit("connection", online=True)
                    print(f"[agent] Подключено к VPS! Приложений: {len(apps)}", flush=True)
                    _sys.stdout.flush()
                    await self._recv_loop()
            except Exception as e:
                print(f"[agent] WS ошибка: {e}", flush=True)
                _sys.stdout.flush()
            self._ws = None
            self.bus.emit("connection", online=False)
            await asyncio.sleep(config.RECONNECT_SEC)

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
                from core.hands import execute_command
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
        while True:
            try:
                async with websockets.connect(
                    config.VPS_WS_URL,
                    ping_interval=20,
                    proxy=None,
                    max_size=None,
                ) as ws:
                    self._ws = ws
                    await ws.send(json.dumps(self._payload("register")))
                    apps = scan_apps()
                    if apps:
                        await ws.send(json.dumps({
                            "type":      "apps_list",
                            "device_id": config.DEVICE_ID,
                            "token":     config.WS_TOKEN,
                            "apps":      apps,
                        }))
                    self.bus.emit("connection", online=True)
                    log.info(f"Подключено. Приложений: {len(apps)}")
                    await self._recv_loop()
            except Exception as e:
                log.warning(f"WS обрыв: {e} — реконнект через {config.RECONNECT_SEC}с")
            self._ws = None
            self.bus.emit("connection", online=False)
            await asyncio.sleep(config.RECONNECT_SEC)