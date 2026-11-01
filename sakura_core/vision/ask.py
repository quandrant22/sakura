"""ask — разовый вопрос по экрану («глянь на экран», «что у меня тут»).

Реестр: vision.ask (legacy: screenshot.describe). Хендлер возвращает
(текст, ok) — мост озвучит/отправит его как ответ на ход.

Клиент без vision.capture (старый agent/): команда screenshot.describe
с отметкой st._pending_describe — кадр придёт command_result, ответ
даст describe_legacy() тем же промптом и той же моделью.
"""

from __future__ import annotations

import logging

log = logging.getLogger("sakura.vision")

QUESTION_MAX = 300
DEFAULT_QUESTION = "Что у меня на экране?"

SKIP_TEXT = {
    "private_window": "Это окно приватное — туда не смотрю.",
    "disabled": "На компьютере мне запрещено смотреть на экран.",
    "no_display": "Экран сейчас выключен или заблокирован.",
    "capture_failed": "Не получилось снять экран.",
    "unchanged": "Не получилось снять экран.",
}
ERROR_TEXT = {
    "offline": "Компьютер сейчас не в сети.",
    "not_master": "С этого устройства на экран не смотрю.",
    "secure_channel_required": "Экран смотрю только по защищённому каналу.",
    "timeout": "Компьютер не прислал кадр.",
    "unsupported": "Клиент на компьютере не умеет показывать мне экран.",
}


def question_from(text: str) -> str:
    q = " ".join((text or "").split())[:QUESTION_MAX]
    return q or DEFAULT_QUESTION


def pick_device(source_device: str | None) -> str | None:
    """ПК, на экран которого смотреть: устройство-источник, если это
    онлайн-ПК; иначе активный ПК; иначе единственный онлайн-ПК."""
    import modules.state as st
    from modules.presence_sync import get_active_device, is_pc
    online = [d for d in list(st.connected_devices) if is_pc(d)]
    if source_device in online:
        return source_device
    active = get_active_device()
    if active in online:
        return active
    return online[0] if len(online) == 1 else None


async def answer(device_id: str, question: str) -> tuple[str, bool]:
    from sakura_core.vision import capture, model, parse, prompts, seen
    try:
        result = await capture.request(device_id, "ask")
    except capture.CaptureError as e:
        return ERROR_TEXT.get(e.code, "Не получилось посмотреть на экран."), False
    if isinstance(result, capture.Skipped):
        return SKIP_TEXT.get(result.reason, "Не получилось снять экран."), result.reason == "private_window"
    try:
        reply = await model.see(result.image, result.mime,
                                prompts.ASK.format(question=question))
    except Exception as e:
        log.error(f"[vision] ask {device_id}: модель: {type(e).__name__}")
        return "Не получилось рассмотреть экран.", False
    text, saw = parse.split_ask(reply)
    if saw:
        seen.record(device_id, result.title, saw, "ask")
    return (text, True) if text else ("Не получилось рассмотреть экран.", False)


async def describe_legacy(device_id: str, image: bytes, mime: str, question: str) -> str:
    """Старый клиент прислал кадр command_result по screenshot.describe."""
    from sakura_core.vision import model, parse, prompts, seen
    reply = await model.see(image, mime, prompts.ASK.format(question=question))
    text, saw = parse.split_ask(reply)
    if saw:
        seen.record(device_id, "", saw, "ask")
    return text
