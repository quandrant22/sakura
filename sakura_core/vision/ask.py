"""ask — разовый вопрос по экрану («глянь на экран», «что у меня тут»).

Реестр: vision.ask (legacy: screenshot.describe). Хендлер возвращает
(текст, ok) — мост озвучит/отправит его как ответ на ход.

Клиент без vision.capture (старый agent/): команда screenshot.describe
с отметкой st._pending_describe — кадр придёт command_result, ответ
даст describe_legacy() тем же промптом и той же моделью.
"""

from __future__ import annotations

import asyncio
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


DIALOGUE_TURNS = 6
DIALOGUE_CHARS = 240
SEARCH_TIMEOUT_S = 12.0


def recent_dialogue() -> str:
    """Последние реплики разговора для модели зрения: она должна понять
    задачу Мастера («найди, где предмет по квесту»), а не только фразу
    «глянь на экран»."""
    try:
        from memory.memory import get_history
        history = get_history()[-DIALOGUE_TURNS:]
    except Exception as e:
        log.debug(f"[vision] история: {type(e).__name__}")
        return "— (пусто)"
    lines = []
    for m in history:
        who = "Мастер" if m.get("role") == "user" else "Сакура"
        text = " ".join(str((m.get("parts") or [""])[0]).split())[:DIALOGUE_CHARS]
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines) or "— (пусто)"


async def _search(query: str) -> tuple[str, bool]:
    from modules.web_search import search_grounded
    try:
        facts, _sources, ok = await asyncio.wait_for(search_grounded(query), SEARCH_TIMEOUT_S)
    except Exception as e:
        log.info(f"[vision] поиск не удался: {type(e).__name__}")
        return "", False
    return (facts or "").strip(), bool(ok and facts)


async def answer(device_id: str, question: str) -> tuple[str, bool]:
    """Кадр → факты с экрана (модель зрения) → поиск при необходимости →
    ответ обычной Сакуры с историей и характером (ask_gemini)."""
    import config
    from sakura_core.vision import capture, model, parse, prompts, seen
    try:
        result = await capture.request(device_id, "ask")
    except capture.CaptureError as e:
        return ERROR_TEXT.get(e.code, "Не получилось посмотреть на экран."), False
    if isinstance(result, capture.Skipped):
        return SKIP_TEXT.get(result.reason, "Не получилось снять экран."), result.reason == "private_window"
    try:
        reply = await model.see(result.image, result.mime,
                                prompts.EXTRACT.format(dialogue=recent_dialogue(), question=question),
                                max_tokens=400)
    except Exception as e:
        log.error(f"[vision] ask {device_id}: модель: {type(e).__name__}")
        return "Не получилось рассмотреть экран.", False
    saw, facts, query = parse.parse_extract(reply)
    if not saw and not facts:
        return "Не получилось рассмотреть экран.", False
    seen.record(device_id, result.title, saw or facts, "ask")

    context = prompts.ANSWER_CONTEXT.format(saw=saw or "—", facts=facts or "—")
    if query:
        found, ok = await _search(query)
        log.info(f"[vision] поиск по экрану: {'есть факты' if ok else 'пусто'} ({len(query)} симв запроса)")
        if ok:
            from modules.web_search import facts_prompt
            context += facts_prompt(found)
        else:
            context += prompts.NO_SEARCH_RESULT.format(query=query)

    from sakura_core.llm import ask_gemini
    text = await ask_gemini(question, history_limit=config.VOICE_HISTORY_LIMIT,
                            chain=config.VOICE_MODEL_CHAIN, extra_system=context, search=False)
    text = parse.clean_answer(text or "")
    return (text, True) if text else ("Не получилось ответить по экрану.", False)


async def describe_legacy(device_id: str, image: bytes, mime: str, question: str) -> str:
    """Старый клиент прислал кадр command_result по screenshot.describe."""
    from sakura_core.vision import model, parse, prompts, seen
    reply = await model.see(image, mime, prompts.ASK.format(question=question))
    text, saw = parse.split_ask(reply)
    if saw:
        seen.record(device_id, "", saw, "ask")
    return text
