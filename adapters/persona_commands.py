"""adapters/persona_commands.py — /образ: просмотр и перезапись образа Сакуры.

Только Мастер (регистрируется через _master_only). Логика отделена от
aiogram: run() принимает аргументы команды и текст присланного файла и
возвращает ответ — так её проверяют тесты без Telegram.

    /образ                         — какие образы действуют
    /образ <режим>                 — прислать текущий образ файлом .md
    /образ <режим>  + файл .md     — перезаписать образ содержимым файла
    /образ <режим> сброс           — вернуть заводской образ
    /образ <режим> откат           — вернуть предыдущую версию

Режимы: обычный (master), гость (guest), интим (intimate).
"""

from __future__ import annotations

from dataclasses import dataclass

from sakura_core import persona

_ALIASES = {
    "master": "master", "мастер": "master", "обычный": "master", "основной": "master",
    "guest": "guest", "гость": "guest", "гостевой": "guest", "гости": "guest",
    "intimate": "intimate", "интим": "intimate", "интимный": "intimate",
    "18": "intimate", "18+": "intimate", "приват": "intimate",
}
_TITLES = {"master": "обычный", "guest": "гость", "intimate": "интим"}
MAX_FILE_BYTES = 64 * 1024


@dataclass
class Reply:
    text: str
    file_name: str | None = None
    file_bytes: bytes | None = None


def _usage() -> str:
    return ("Образ: /образ [обычный|гость|интим] [сброс|откат].\n"
            "Чтобы перезаписать — пришлите .md файлом с подписью «/образ <режим>».")


def _overview() -> str:
    lines = ["Образы:"]
    for mode in persona.MODES:
        text = persona.get(mode)
        origin = "свой" if persona.origin(mode) == "custom" else "заводской"
        hist = len(persona.history(mode))
        lines.append(f"— {_TITLES[mode]}: {origin}, {len(text)} симв., версий в истории: {hist}")
    return "\n".join(lines) + "\n\n" + _usage()


def run(args: str, document_text: str | None = None) -> Reply:
    parts = (args or "").split()
    if not parts:
        return Reply(_overview())
    mode = _ALIASES.get(parts[0].lower())
    if not mode:
        return Reply(f"Такого образа нет: {parts[0]}.\n" + _usage())
    action = parts[1].lower() if len(parts) > 1 else ""
    title = _TITLES[mode]

    if document_text is not None:
        try:
            persona.set(mode, document_text, source="telegram")
        except persona.PersonaError as e:
            return Reply(f"Не приняла образ «{title}»: {e}.")
        return Reply(f"Образ «{title}» перезаписан: {len(persona.get(mode))} симв. "
                     f"Действует со следующей реплики. Вернуть прежний — «/образ {title} откат».")

    if action in ("сброс", "reset"):
        persona.reset(mode, source="telegram")
        return Reply(f"Образ «{title}» сброшен к заводскому.")
    if action in ("откат", "undo", "rollback"):
        if persona.rollback(mode, source="telegram"):
            return Reply(f"Образ «{title}» возвращён к предыдущей версии.")
        return Reply(f"Предыдущих версий образа «{title}» нет.")
    if action:
        return Reply(f"Не знаю действия «{action}».\n" + _usage())

    text = persona.get(mode)
    origin = "свой" if persona.origin(mode) == "custom" else "заводской"
    return Reply(f"Образ «{title}» ({origin}, {len(text)} симв.). Исправьте и пришлите обратно "
                 f"файлом с подписью «/образ {title}».",
                 file_name=f"sakura_{mode}.md", file_bytes=(text + "\n").encode("utf-8"))


async def cmd_persona_impl(message, bot=None):
    """aiogram-обёртка: читает аргументы из текста или подписи, файл — если приложен."""
    import asyncio

    raw = message.text or message.caption or ""
    args = raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1)) > 1 else ""

    doc_text = None
    doc = getattr(message, "document", None)
    if doc is not None:
        if (doc.file_size or 0) > MAX_FILE_BYTES:
            await message.answer(f"Файл больше {MAX_FILE_BYTES // 1024} КиБ — это не похоже на образ.")
            return
        try:
            buf = await (bot or message.bot).download(doc)
            doc_text = buf.read().decode("utf-8")
        except UnicodeDecodeError:
            await message.answer("Файл не в UTF-8. Сохраните образ как текст UTF-8.")
            return
        except Exception as e:  # noqa: BLE001 — сбой сети/Telegram: сообщаем Мастеру
            await message.answer(f"Не получилось скачать файл: {type(e).__name__}.")
            return

    reply = await asyncio.to_thread(run, args, doc_text)
    if reply.file_bytes is not None:
        from aiogram.types import BufferedInputFile
        await message.answer_document(
            BufferedInputFile(reply.file_bytes, filename=reply.file_name), caption=reply.text)
    else:
        await message.answer(reply.text)
