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


# ── Документы режима 18+: база о Мастере и её фигура ─────────────────
#
#   /база                 — прислать базу файлом .md
#   /база + файл .md      — перезаписать базу
#   /база сброс | откат
#   /фигура               — показать, как она выглядит
#   /фигура <описание>    — заменить описание (или файлом .md)
#   /фигура сброс | откат
#
# Оба документа читаются только образом intimate (personality._intimate_docs)
# и хранятся рядом с образами в memory/persona/ — не в основной памяти.

import re as _re

_DOC_TITLES = {"intimate_kb": "база режима 18+", "intimate_figure": "фигура"}
_DOC_CMD = {"intimate_kb": "/база", "intimate_figure": "/фигура"}

# Внешность — только взрослая: явные признаки несовершеннолетия не принимаем.
_MINOR_RX = _re.compile(
    r"(?<!\w)(?:школьниц|школьник|ребён|ребен|девочк|малолет|несовершеннолет|"
    r"подрост|лоли|младшеклас|(?:[1-9]|1[0-7])\s*(?:лет|год))",
    _re.IGNORECASE)


def _check_figure(text: str) -> str | None:
    if _MINOR_RX.search(text or ""):
        return "только взрослая внешность — без детских черт и возраста младше 18"
    return None


def run_doc(doc: str, args: str, document_text: str | None = None) -> Reply:
    title, cmd = _DOC_TITLES[doc], _DOC_CMD[doc]
    action = (args or "").strip()
    low = action.lower()

    new_text = document_text
    if new_text is None and doc == "intimate_figure" and action and low not in (
            "сброс", "reset", "откат", "undo", "rollback"):
        new_text = action

    if new_text is not None:
        if doc == "intimate_figure":
            err = _check_figure(new_text)
            if err:
                return Reply(f"Не приняла: {err}.")
        try:
            persona.set(doc, new_text, source="telegram")
        except persona.PersonaError as e:
            return Reply(f"Не приняла {title}: {e}.")
        return Reply(f"Готово: {title} обновлена ({len(persona.get(doc))} симв.). "
                     f"Действует со следующей реплики в режиме. Вернуть прежнюю — «{cmd} откат».")

    if low in ("сброс", "reset"):
        persona.reset(doc, source="telegram")
        return Reply(f"{title.capitalize()} — снова заводская.")
    if low in ("откат", "undo", "rollback"):
        if persona.rollback(doc, source="telegram"):
            return Reply(f"{title.capitalize()} — возвращена предыдущая версия.")
        return Reply(f"Предыдущих версий нет ({title}).")
    if action:
        return Reply(f"Не знаю действия «{action}». {cmd} [сброс|откат], правка — файлом .md "
                     f"с подписью «{cmd}».")

    text = persona.get(doc)
    origin = "своя" if persona.origin(doc) == "custom" else "заводская"
    hint = (f"Поменять: «/фигура <новое описание>» или файлом с подписью «/фигура»."
            if doc == "intimate_figure" else
            "Исправьте и пришлите обратно файлом с подписью «/база».")
    return Reply(f"{title.capitalize()} ({origin}, {len(text)} симв.). {hint}",
                 file_name=f"sakura_{doc}.md", file_bytes=(text + "\n").encode("utf-8"))


# «запомни…» внутри режима — в базу режима, а не в основную память.
_REMEMBER_RX = _re.compile(
    r"(?:^|[,.!?]\s*|сакура,?\s+)запомни(?:\s+это)?(?:,?\s*что)?[:,]?\s+(?P<note>[^=\n]{3,300})$",
    _re.IGNORECASE)


def remember_note(text: str) -> bool:
    """Если реплика — «запомни …», дописать в ЗАМЕТКИ базы режима. True — записала."""
    m = _REMEMBER_RX.search((text or "").strip())
    if not m:
        return False
    note = m.group("note").strip().rstrip(".!")
    if not note:
        return False
    import time as _time
    kb = persona.get("intimate_kb").rstrip()
    line = f"— {_time.strftime('%d.%m.%Y')}: {note}"
    try:
        persona.set("intimate_kb", f"{kb}\n{line}", source="intimate-remember")
    except persona.PersonaError as e:
        log_ = __import__("logging").getLogger("sakura.persona")
        log_.warning("[persona] заметка режима не записана: %s", e)
        return False
    return True


async def _doc_cmd_impl(doc: str, message, bot=None):
    import asyncio

    raw = message.text or message.caption or ""
    args = raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1)) > 1 else ""
    doc_text = None
    d = getattr(message, "document", None)
    if d is not None:
        if (d.file_size or 0) > MAX_FILE_BYTES:
            await message.answer(f"Файл больше {MAX_FILE_BYTES // 1024} КиБ.")
            return
        try:
            buf = await (bot or message.bot).download(d)
            doc_text = buf.read().decode("utf-8")
        except UnicodeDecodeError:
            await message.answer("Файл не в UTF-8.")
            return
        except Exception as e:  # noqa: BLE001
            await message.answer(f"Не получилось скачать файл: {type(e).__name__}.")
            return

    reply = await asyncio.to_thread(run_doc, doc, args, doc_text)
    if reply.file_bytes is not None:
        from aiogram.types import BufferedInputFile
        caption = reply.text
        if doc == "intimate_figure":
            caption = (persona.get(doc)[:900] + "\n\n" + reply.text)
        await message.answer_document(
            BufferedInputFile(reply.file_bytes, filename=reply.file_name), caption=caption[:1024])
    else:
        await message.answer(reply.text)


async def cmd_intimate_kb_impl(message, bot=None):
    await _doc_cmd_impl("intimate_kb", message, bot)


async def cmd_figure_impl(message, bot=None):
    await _doc_cmd_impl("intimate_figure", message, bot)
