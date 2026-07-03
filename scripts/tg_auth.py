"""Авторизация Telethon с SMS. Запускать из терминала."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "sakura_tg")

async def main():
    from telethon import TelegramClient
    print(f"API_ID: {API_ID}")
    print(f"Сессия: {SESSION}")
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start(force_sms=True)
    me = await client.get_me()
    print(f"\nАвторизован: {me.first_name} {me.last_name or ''} (ID: {me.id})")
    print(f"Username: @{me.username or 'нет'}")
    await client.disconnect()

asyncio.run(main())
