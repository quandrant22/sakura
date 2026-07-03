"""
modules/tg_monitor.py — Мониторинг Telegram через Telethon (User API).

Читает входящие сообщения из личного Telegram и определяет важные.
Управление whitelist через Telegram-бота: "мониторь <ID>", "убери монитор <ID>".
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

from telethon import events

log = logging.getLogger("sakura.tg_monitor")

TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "memory/sakura_tg.session")

WHITELIST_FILE = "memory/tg_whitelist.json"

_env_wl = [x.strip() for x in os.getenv("TG_MONITOR_WHITELIST", "").split(",") if x.strip()]


def _load_whitelist() -> dict:
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"whitelist": _env_wl, "blacklist": []}


def _save_whitelist(data: dict):
    os.makedirs(os.path.dirname(WHITELIST_FILE), exist_ok=True)
    with open(WHITELIST_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _check_chat(chat_id: str) -> bool:
    data = _load_whitelist()
    wl = set(data.get("whitelist", []))
    bl = set(data.get("blacklist", []))
    if bl and chat_id in bl:
        return False
    if wl and chat_id not in wl:
        return False
    return True


def add_to_whitelist(chat_id: str) -> bool:
    data = _load_whitelist()
    wl = data.get("whitelist", [])
    if chat_id not in wl:
        wl.append(chat_id)
        data["whitelist"] = wl
        _save_whitelist(data)
        log.info(f"[tg_monitor] Whitelist +{chat_id}")
        return True
    return False


def remove_from_whitelist(chat_id: str) -> bool:
    data = _load_whitelist()
    wl = data.get("whitelist", [])
    if chat_id in wl:
        wl.remove(chat_id)
        data["whitelist"] = wl
        _save_whitelist(data)
        log.info(f"[tg_monitor] Whitelist -{chat_id}")
        return True
    return False


def get_whitelist() -> list[str]:
    return _load_whitelist().get("whitelist", [])


def is_whitelist_command(text: str) -> bool:
    """Проверяет, является ли текст командой управления whitelist."""
    tl = text.lower().strip()
    return bool(re.match(r"^(монитор|мониторь|добавь монитор|убери монитор|список монитора)", tl))


def handle_whitelist_command(text: str) -> str | None:
    """
    Обрабатывает команду управления whitelist.
    Возвращает ответ пользователю или None.
    """
    tl = text.lower().strip()
    me_id = "773405879"  # ID Мастера

    # "список монитора" — показать текущий whitelist
    if re.match(r"список монитора", tl):
        wl = get_whitelist()
        if not wl:
            return "Белый список пуст. Добавь чат: «мониторь <ID>»"
        lines = [f"• {cid}" for cid in wl]
        return f"Белый список ({len(wl)} чатов):\n" + "\n".join(lines)

    # "мониторь <ID>" — добавить чат
    m = re.match(r"(?:монитор|мониторь|добавь монитор)\s+(\d+)", tl)
    if m:
        cid = m.group(1)
        if add_to_whitelist(cid):
            return f"Чат {cid} добавлен в белый список."
        return f"Чат {cid} уже в белом списке."

    # "убери монитор <ID>" — удалить чат
    m = re.match(r"убери монитор\s+(\d+)", tl)
    if m:
        cid = m.group(1)
        if remove_from_whitelist(cid):
            return f"Чат {cid} удалён из белого списка."
        return f"Чата {cid} нет в белом списке."

    return None


# ── Мониторинг ─────────────────────────────────────────────────

class TGMonitor:
    def __init__(self):
        self._client = None
        self._running = False
        self._callback = None

    def set_callback(self, cb):
        self._callback = cb

    async def start(self):
        if not TG_API_ID or not TG_API_HASH:
            log.warning("[tg_monitor] TG_API_ID/TG_API_HASH не заданы — мониторинг отключён")
            return

        try:
            from telethon import TelegramClient

            self._client = TelegramClient(
                TG_SESSION, TG_API_ID, TG_API_HASH,
                system_version="Sakura Bot v1.0",
            )

            await self._client.start()

            if not await self._client.is_user_authorized():
                log.info("[tg_monitor] Требуется авторизация")
                return

            me = await self._client.get_me()
            log.info(f"[tg_monitor] Авторизован как: {me.first_name} (ID: {me.id})")

            self._running = True
            self._client.add_event_handler(self._on_message, events.NewMessage)
            log.info(f"[tg_monitor] Мониторинг запущен. Whitelist: {get_whitelist()}")
            await self._client.run_until_disconnected()

        except Exception as e:
            log.error(f"[tg_monitor] Ошибка запуска: {e}")

    async def stop(self):
        self._running = False
        if self._client:
            await self._client.disconnect()

    async def _on_message(self, event):
        if not self._running or not self._callback:
            return

        try:
            if not hasattr(event, 'message') or not event.message:
                return
            msg = event.message
            if isinstance(msg, str):
                return
            if not hasattr(msg, 'text') or not msg.text:
                return

            text = msg.text or ""
            if not text:
                return

            # Команды управления whitelist — обрабатываем
            if is_whitelist_command(text):
                reply = handle_whitelist_command(text)
                if reply:
                    await event.reply(reply)
                return

            # Пропускаем свои сообщения
            me = await self._client.get_me()
            if event.sender_id == me.id:
                return

            # Инфо о чате
            chat = await event.get_chat()
            chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", None) or "Unknown"
            chat_id = str(getattr(chat, "id", ""))

            # Фильтрация
            if not _check_chat(chat_id):
                return

            sender = await event.get_sender()
            sender_name = getattr(sender, "first_name", None) or "Unknown"

            self._last_check = time.time()
            await self._callback(chat_name, sender_name, text[:200], False)

        except Exception as e:
            log.error(f"[tg_monitor] Ошибка обработки: {e}")

    async def get_chats(self) -> list[dict]:
        if not self._client or not self._running:
            return []
        try:
            dialogs = []
            async for dialog in self._client.iter_dialogs(limit=30):
                chat = dialog.entity
                name = getattr(chat, "title", None) or getattr(chat, "first_name", "")
                chat_id = str(getattr(chat, "id", ""))
                username = getattr(chat, "username", "")
                dialogs.append({
                    "id": chat_id, "name": name, "username": username,
                    "last_message": dialog.message.text[:50] if dialog.message else "",
                })
            return dialogs
        except Exception as e:
            log.error(f"[tg_monitor] get_chats error: {e}")
            return []


_monitor: Optional[TGMonitor] = None

def get_monitor() -> TGMonitor:
    global _monitor
    if _monitor is None:
        _monitor = TGMonitor()
    return _monitor


async def _authorize():
    if not TG_API_ID or not TG_API_HASH:
        print("Задай TG_API_ID и TG_API_HASH в .env")
        return
    from telethon import TelegramClient
    client = TelegramClient(TG_SESSION, TG_API_ID, TG_API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"Авторизован: {me.first_name} (ID: {me.id})")
    await client.disconnect()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        asyncio.run(_authorize())
    else:
        print("Авторизация: python modules/tg_monitor.py auth")
