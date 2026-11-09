"""desktop.core.discord_rpc — Прямая интеграция с Discord через локальный IPC/RPC.

Архитектура:
1. Подключается к Discord через локальный Named Pipe (\\\\.\\pipe\\discord-ipc-0).
2. Авторизуется через локальный OAuth2 (scopes: rpc, rpc.voice.read).
3. Получает список участников текущего звонка (серверного или личного в ЛС).
4. Отслеживает в реальном времени события SPEAKING (кто сейчас говорит).
5. Предоставляет CallModeManager точное имя говорящего собеседника вместо «Друг».
"""

from __future__ import annotations

import glob
import json
import logging
import os
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests

from desktop.core import config

log = logging.getLogger("sakura.discord_rpc")


@dataclass
class DiscordUser:
    id: str
    username: str
    display_name: str
    avatar: str = ""
    is_self: bool = False


class DiscordRpcManager:
    """Управление локальным подключением к Discord через IPC pipe."""

    OP_HANDSHAKE = 0
    OP_FRAME = 1
    OP_CLOSE = 2
    OP_PING = 3
    OP_PONG = 4

    def __init__(self):
        self.client_id: str = getattr(config, "DISCORD_CLIENT_ID", "1517097834057306163")
        self.client_secret: str = getattr(config, "DISCORD_CLIENT_SECRET", "jHAazXp6QYbfHKxz23BP-VvrllJ01k1a")
        self.token_file: str = os.path.join(config.DATA_DIR, "discord_token.json")
        self._pipe = None
        self._pipe_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

        self.connected: bool = False
        self.authenticated: bool = False
        self.self_user: Optional[DiscordUser] = None
        self.current_channel_id: Optional[str] = None
        self.current_channel_name: str = ""
        self.participants: Dict[str, DiscordUser] = {}
        self.speaker_timestamps: Dict[str, float] = {}  # user_id -> monotonic ts

    def start(self):
        """Запуск фонового потока подключения к Discord."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="discord-rpc", daemon=True)
        self._thread.start()
        log.info("[discord_rpc] Фоновый клиент запущен")

    def stop(self):
        self._running = False
        self._close_pipe()

    def get_active_speaker(self, max_age_sec: float = 2.5) -> tuple[Optional[str], Optional[str], bool]:
        """Возвращает (имя_говорящего, user_id, is_master).

        Если кто-то говорил в течение последних max_age_sec секунд — возвращает его имя.
        Иначе возвращает (None, None, False).
        """
        now = time.monotonic()
        recent = [
            (uid, ts)
            for uid, ts in self.speaker_timestamps.items()
            if (now - ts) <= max_age_sec
        ]
        if not recent:
            return None, None, False

        # Самый свежий голос
        recent.sort(key=lambda x: x[1], reverse=True)
        active_id = recent[0][0]
        user = self.participants.get(active_id)
        if user:
            return user.display_name, user.id, user.is_self

        return "Собеседник", active_id, False

    def _close_pipe(self):
        with self._pipe_lock:
            if self._pipe:
                try:
                    self._pipe.close()
                except Exception:
                    pass
                self._pipe = None
        self.connected = False
        self.authenticated = False

    def _find_pipe_path(self) -> Optional[str]:
        pipes = glob.glob(r"\\.\pipe\discord-ipc-*")
        if pipes:
            # Сортируем: discord-ipc-0 в первую очередь
            pipes.sort()
            return pipes[0]
        return None

    def _send_ipc(self, opcode: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        header = struct.pack("<II", opcode, len(payload))
        with self._pipe_lock:
            if self._pipe:
                self._pipe.write(header + payload)

    def _read_ipc(self) -> tuple[int, dict]:
        with self._pipe_lock:
            if not self._pipe:
                raise ConnectionError("Pipe closed")
            header = self._pipe.read(8)
            if not header or len(header) < 8:
                raise ConnectionError("Short header read")
            opcode, length = struct.unpack("<II", header)
            payload = self._pipe.read(length)
            if len(payload) < length:
                raise ConnectionError("Short payload read")
            return opcode, json.loads(payload.decode("utf-8"))

    def _load_token(self) -> Optional[str]:
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    return d.get("access_token")
        except Exception as e:
            log.debug("[discord_rpc] Ошибка чтения токена: %s", e)
        return None

    def _save_token(self, token_data: dict):
        try:
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            with open(self.token_file, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
            log.info("[discord_rpc] Токен Discord успешно сохранён в %s", self.token_file)
        except Exception as e:
            log.warning("[discord_rpc] Не удалось сохранить токен: %s", e)

    def _exchange_code_for_token(self, code: str) -> Optional[str]:
        try:
            resp = requests.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "http://127.0.0.1",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                },
                timeout=10.0,
            )
            if resp.status_code == 200:
                res_data = resp.json()
                self._save_token(res_data)
                return res_data.get("access_token")
            else:
                log.error("[discord_rpc] Ошибка ответа OAuth-сервера Discord: HTTP %s: %s", resp.status_code, resp.text)
                return None
        except Exception as e:
            log.error("[discord_rpc] Ошибка запроса токена OAuth: %s", e)
            return None

    def _authenticate(self) -> bool:
        """Аутентификация через сохранённый access_token или запрос нового."""
        access_token = self._load_token()

        if access_token:
            # Пробуем войти по существующему токену
            auth_nonce = str(uuid.uuid4())
            self._send_ipc(self.OP_FRAME, {
                "cmd": "AUTHENTICATE",
                "args": {"access_token": access_token},
                "nonce": auth_nonce,
            })
            op, resp = self._read_ipc()
            if resp.get("evt") != "ERROR":
                log.info("[discord_rpc] Успешная аутентификация по сохранённому токену")
                self.authenticated = True
                return True
            log.info("[discord_rpc] Сохранённый токен истёк — запрашиваем новый...")

        # Запрашиваем авторизацию (Discord покажет модалку пользователю)
        auth_nonce = str(uuid.uuid4())
        self._send_ipc(self.OP_FRAME, {
            "cmd": "AUTHORIZE",
            "args": {
                "client_id": self.client_id,
                "scopes": ["rpc", "rpc.voice.read"],
            },
            "nonce": auth_nonce,
        })
        log.info("[discord_rpc] Ожидание подтверждения авторизации в окне Discord...")
        op, resp = self._read_ipc()
        if resp.get("evt") == "ERROR":
            log.warning("[discord_rpc] Авторизация отклонена пользователем: %s", resp.get("data"))
            return False

        code = resp.get("data", {}).get("code")
        if not code:
            log.warning("[discord_rpc] Нет кода авторизации в ответе: %s", resp)
            return False

        new_token = self._exchange_code_for_token(code)
        if not new_token:
            return False

        # Финальный AUTHENTICATE с новым токеном
        auth_nonce = str(uuid.uuid4())
        self._send_ipc(self.OP_FRAME, {
            "cmd": "AUTHENTICATE",
            "args": {"access_token": new_token},
            "nonce": auth_nonce,
        })
        op, resp = self._read_ipc()
        if resp.get("evt") != "ERROR":
            log.info("[discord_rpc] Аутентификация с новым токеном успешна!")
            self.authenticated = True
            return True

        return False

    def _setup_voice_subscriptions(self):
        """Подписка на события звонков и получение текущего канала."""
        # 1. Подписка на смену голосового канала
        sub_nonce = str(uuid.uuid4())
        self._send_ipc(self.OP_FRAME, {
            "cmd": "SUBSCRIBE",
            "evt": "VOICE_CHANNEL_SELECT",
            "nonce": sub_nonce,
        })

        # 2. Запрос текущего голосового канала
        chan_nonce = str(uuid.uuid4())
        self._send_ipc(self.OP_FRAME, {
            "cmd": "GET_SELECTED_VOICE_CHANNEL",
            "args": {},
            "nonce": chan_nonce,
        })

    def _update_channel_data(self, channel_data: Optional[dict]):
        if not channel_data or not channel_data.get("id"):
            self.current_channel_id = None
            self.current_channel_name = ""
            self.participants.clear()
            log.info("[discord_rpc] Не в голосовом канале Discord")
            return

        chan_id = str(channel_data.get("id"))
        self.current_channel_id = chan_id
        self.current_channel_name = channel_data.get("name", "Звонок")

        # Подписываемся на индикаторы речи в этом канале
        self._send_ipc(self.OP_FRAME, {
            "cmd": "SUBSCRIBE",
            "evt": "SPEAKING",
            "args": {"channel_id": chan_id},
            "nonce": str(uuid.uuid4()),
        })

        # Обновляем участников
        new_participants = {}
        for vs in channel_data.get("voice_states", []):
            u = vs.get("user", {})
            uid = str(u.get("id", ""))
            if not uid:
                continue
            nick = vs.get("nick")
            global_name = u.get("global_name")
            username = u.get("username", "Собеседник")
            display = nick or global_name or username
            is_self = bool(self.self_user and self.self_user.id == uid)
            new_participants[uid] = DiscordUser(
                id=uid,
                username=username,
                display_name=display,
                avatar=u.get("avatar", ""),
                is_self=is_self,
            )

        self.participants = new_participants
        names = [f"{p.display_name} ({p.username})" for p in self.participants.values()]
        log.info(
            "[discord_rpc] Канал '%s' (%s участников): %s",
            self.current_channel_name, len(self.participants), ", ".join(names)
        )

    def _handle_event(self, resp: dict):
        evt = resp.get("evt")
        data = resp.get("data") or {}

        if evt == "VOICE_CHANNEL_SELECT":
            chan_id = data.get("channel_id")
            if chan_id:
                chan_nonce = str(uuid.uuid4())
                self._send_ipc(self.OP_FRAME, {
                    "cmd": "GET_SELECTED_VOICE_CHANNEL",
                    "args": {},
                    "nonce": chan_nonce,
                })
            else:
                self._update_channel_data(None)

        elif evt == "SPEAKING":
            uid = str(data.get("user_id", ""))
            speaking = data.get("speaking", 0)
            if uid and speaking:
                self.speaker_timestamps[uid] = time.monotonic()
                user = self.participants.get(uid)
                name = user.display_name if user else uid
                log.debug("[discord_rpc] Речь в войсе: %s", name)

        elif resp.get("cmd") == "GET_SELECTED_VOICE_CHANNEL":
            self._update_channel_data(data)

    def _run_loop(self):
        """Основной рабочий цикл с автоматическим переподключением."""
        while self._running:
            pipe_path = self._find_pipe_path()
            if not pipe_path:
                time.sleep(3.0)
                continue

            try:
                log.info("[discord_rpc] Подключение к %s...", pipe_path)
                with open(pipe_path, "r+b", buffering=0) as f:
                    with self._pipe_lock:
                        self._pipe = f
                    self.connected = True

                    # 1. Рукопожатие
                    handshake_payload = {"v": 1, "client_id": self.client_id}
                    self._send_ipc(self.OP_HANDSHAKE, handshake_payload)
                    op, ready_resp = self._read_ipc()
                    if ready_resp.get("evt") != "READY":
                        log.warning("[discord_rpc] Ошибка READY: %s", ready_resp)
                        time.sleep(2.0)
                        continue

                    user_info = ready_resp.get("data", {}).get("user", {})
                    self.self_user = DiscordUser(
                        id=str(user_info.get("id", "")),
                        username=user_info.get("username", "Мастер"),
                        display_name=user_info.get("global_name") or user_info.get("username", "Мастер"),
                        avatar=user_info.get("avatar", ""),
                        is_self=True,
                    )
                    log.info("[discord_rpc] Рукопожатие успешно! Пользователь: %s", self.self_user.display_name)

                    # 2. Аутентификация
                    if not self._authenticate():
                        time.sleep(5.0)
                        continue

                    # 3. Подписки на голосовые события
                    self._setup_voice_subscriptions()

                    # 4. Чтение потока событий
                    while self._running:
                        op, msg = self._read_ipc()
                        if op == self.OP_PING:
                            self._send_ipc(self.OP_PONG, msg.get("data", {}))
                            continue
                        self._handle_event(msg)

            except Exception as e:
                log.debug("[discord_rpc] Соединение разорвано: %s", e)
            finally:
                self._close_pipe()
                time.sleep(3.0)


# Синглтон
_discord_rpc_manager: Optional[DiscordRpcManager] = None


def get_discord_rpc_manager() -> DiscordRpcManager:
    global _discord_rpc_manager
    if _discord_rpc_manager is None:
        _discord_rpc_manager = DiscordRpcManager()
    return _discord_rpc_manager
