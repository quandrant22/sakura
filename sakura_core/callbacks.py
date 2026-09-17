"""Startup callbacks — extracted from main.py."""

import logging
from modules.state_arbiter import get_current_emotion

log = logging.getLogger("sakura.callbacks")


async def make_reminder_cb(_get_active_ws, stream_tts_to_device, send_to_master,
                            get_current_emotion):
    """Reminder callback factory."""
    async def _reminder_cb(msg):
        ws, dev = _get_active_ws()
        if ws:
            await stream_tts_to_device(msg, ws, dev or "laptop",
                                       literal=True, emotion=get_current_emotion())
        await send_to_master(msg)
    return _reminder_cb


async def make_tg_notif_cb(_get_active_ws, stream_tts_to_device, ask_gemini):
    """Telegram notification callback factory."""
    async def _tg_notif_cb(chat_name, sender, text, urgent):
        from modules.notification_tracker import add_notification
        add_notification("telegram", f"{sender} в {chat_name}", text)
        if urgent:
            ws, dev = _get_active_ws()
            if ws:
                prompt = (
                    f"Поступило важное сообщение в Telegram от {sender} в {chat_name}: «{text[:80]}». "
                    "Скажи Мастеру одной короткой фразой обратить внимание."
                )
                reply = await ask_gemini(prompt, save_history=False)
                if reply:
                    await stream_tts_to_device(reply, ws, dev or "laptop",
                                               literal=True, emotion=get_current_emotion())
    return _tg_notif_cb


async def make_achievement_cb(MASTER_ID, send_telegram_text, mark_sent):
    """Achievement callback factory."""
    async def _achievement_cb(game_name, ach):
        ach_name = ach.get("name") or ach.get("apiname") or "достижение"
        text = f"Выбито достижение: {ach_name} ({game_name})."
        await send_telegram_text(MASTER_ID, text)
        mark_sent(topic="achievement", text=text)
    return _achievement_cb