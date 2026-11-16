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
# Правятся прямо в Telegram:
#   /база, /фигура            — карточка с кнопками параметров
#   нажать параметр           — следующим сообщением прислать значение
#   /фигура рост 172          — быстрая правка параметра
#   /фигура + Тату: сакура    — свой параметр;  /фигура - Тату — убрать
#   /база заметка <текст>     — заметка; кнопка «Заметки» — список/удаление
#   … сброс | откат | файл    — как у /образ (файл .md — целиком)
#
# Документ — строки «— Параметр: значение» под заголовками разделов
# (строки ЗАГЛАВНЫМИ). Раздел ЗАМЕТКИ — свободные строки «— дата: текст».
# Читаются только образом intimate (personality._intimate_docs) и лежат
# в memory/persona/, не в основной памяти.

import re as _re
import time as _time

_DOC_TITLES = {"intimate_kb": "база режима 18+", "intimate_figure": "фигура"}
_DOC_CMD = {"intimate_kb": "/база", "intimate_figure": "/фигура"}
_DOC_KEY = {"intimate_kb": "k", "intimate_figure": "f"}
_KEY_DOC = {v: k for k, v in _DOC_KEY.items()}
NOTES_HEADER = "ЗАМЕТКИ"
EMPTY = "—"
MAX_VALUE = 600
PENDING_TTL = 600

_FIELD_RX = _re.compile(r"^—\s*([^:\n]{1,60}?)\s*:\s*(.*)$")
_HEADER_RX = _re.compile(r"^[А-ЯЁA-Z0-9 «»\"—\-+/,.()]{3,}$")

# Внешность — только взрослая: явные признаки несовершеннолетия не принимаем.
_MINOR_RX = _re.compile(
    r"(?<!\w)(?:школьниц|школьник|ребён|ребен|девочк|малолет|несовершеннолет|"
    r"подрост|лоли|младшеклас|(?:[1-9]|1[0-7])\s*(?:лет|год))",
    _re.IGNORECASE)


def _check_figure(text: str) -> str | None:
    if _MINOR_RX.search(text or ""):
        return "только взрослая внешность — без детских черт и возраста младше 18"
    for line in (text or "").splitlines():
        m = _FIELD_RX.match(line.strip())
        if m and m.group(1).strip().lower() == "возраст":
            num = _re.search(r"\d+", m.group(2))
            if num and int(num.group()) < 18:
                return "возраст — от 18"
    return None


def _is_header(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith("—") and s == s.upper() and bool(_HEADER_RX.match(s))


def _parse(text: str):
    """[(line_no, section, label, value, is_note)] для строк «— …»."""
    out, section = [], ""
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if _is_header(s):
            section = s
            continue
        if not s.startswith("—"):
            continue
        if section == NOTES_HEADER:
            out.append((i, section, "", s.lstrip("— ").strip(), True))
            continue
        m = _FIELD_RX.match(s)
        if m:
            out.append((i, section, m.group(1).strip(), m.group(2).strip(), False))
    return out


def fields(doc: str) -> list[tuple[str, str]]:
    return [(lbl, val) for _, _, lbl, val, note in _parse(persona.get(doc)) if not note]


def notes(doc: str = "intimate_kb") -> list[str]:
    return [val for *_, val, note in _parse(persona.get(doc)) if note]


def _save(doc: str, text: str, source: str = "telegram") -> str | None:
    if doc == "intimate_figure":
        err = _check_figure(text)
        if err:
            return err
    try:
        persona.set(doc, text, source=source)
    except persona.PersonaError as e:
        return str(e)
    return None


def _find(doc: str, label: str):
    lbl = label.strip().lower().rstrip(":")
    items = [p for p in _parse(persona.get(doc)) if not p[4]]
    for p in items:
        if p[2].lower() == lbl:
            return p
    starts = [p for p in items if p[2].lower().startswith(lbl)]
    return starts[0] if len(starts) == 1 else None


def set_field(doc: str, label: str, value: str) -> str | None:
    """Меняет значение параметра. None — успех, иначе текст ошибки."""
    value = " ".join((value or "").split())
    if value in ("-", "", "—", "пусто", "очистить"):
        value = EMPTY
    if len(value) > MAX_VALUE:
        return f"слишком длинно: {len(value)} симв., предел {MAX_VALUE}"
    p = _find(doc, label)
    if not p:
        return f"нет параметра «{label}»"
    lines = persona.get(doc).splitlines()
    lines[p[0]] = f"— {p[2]}: {value}"
    return _save(doc, "\n".join(lines))


def add_field(doc: str, label: str, value: str) -> str | None:
    label, value = label.strip().rstrip(":"), " ".join((value or "").split()) or EMPTY
    if not label or len(label) > 60 or ":" in label:
        return "название параметра — до 60 символов, без двоеточия"
    if _find(doc, label) and _find(doc, label)[2].lower() == label.lower():
        return set_field(doc, label, value)
    lines = persona.get(doc).splitlines()
    new = f"— {label}: {value}"
    notes_at = next((i for i, l in enumerate(lines) if l.strip() == NOTES_HEADER), None)
    if notes_at is None:
        lines.append(new)
    else:
        j = notes_at
        while j > 0 and not lines[j - 1].strip():
            j -= 1
        lines.insert(j, new)
    return _save(doc, "\n".join(lines))


def remove_field(doc: str, label: str) -> str | None:
    p = _find(doc, label)
    if not p:
        return f"нет параметра «{label}»"
    lines = persona.get(doc).splitlines()
    del lines[p[0]]
    return _save(doc, "\n".join(lines))


def add_note(note: str, source: str = "telegram") -> str | None:
    note = " ".join((note or "").split()).rstrip(".!")
    if len(note) < 2:
        return "пустая заметка"
    text = persona.get("intimate_kb").rstrip()
    if not any(l.strip() == NOTES_HEADER for l in text.splitlines()):
        text += f"\n\n{NOTES_HEADER}"
    return _save("intimate_kb", f"{text}\n— {_time.strftime('%d.%m.%Y')}: {note}", source)


def delete_note(idx: int) -> str | None:
    items = [p for p in _parse(persona.get("intimate_kb")) if p[4]]
    if not 0 <= idx < len(items):
        return "такой заметки уже нет"
    lines = persona.get("intimate_kb").splitlines()
    del lines[items[idx][0]]
    return _save("intimate_kb", "\n".join(lines))


# ── Карточка с кнопками (без aiogram: кнопки — (текст, callback_data)) ─

def _short(v: str, n: int = 70) -> str:
    return v if len(v) <= n else v[: n - 1] + "…"


def card(doc: str) -> tuple[str, list[list[tuple[str, str]]]]:
    k = _DOC_KEY[doc]
    origin = "своя" if persona.origin(doc) == "custom" else "заводская"
    lines = [f"{_DOC_TITLES[doc].capitalize()} ({origin}). Нажми параметр, чтобы изменить.", ""]
    rows: list[list[tuple[str, str]]] = []
    section = None
    for i, (_, sec, lbl, val, note) in enumerate(
            p for p in _parse(persona.get(doc)) if not p[4]):
        if sec != section and sec and doc == "intimate_kb":
            lines.append(f"\n{sec}")
            section = sec
        lines.append(f"• {lbl}: {_short(val)}")
    flds = fields(doc)
    for i in range(0, len(flds), 2):
        rows.append([(_short(lbl, 28), f"pdoc:{k}:e:{i + j}")
                     for j, (lbl, _) in enumerate(flds[i:i + 2])])
    extra = [("➕ Параметр", f"pdoc:{k}:add")]
    if doc == "intimate_kb":
        n = len(notes())
        lines.append(f"\nЗаметок: {n}")
        extra.append((f"📝 Заметки ({n})", f"pdoc:{k}:notes"))
    rows.append(extra)
    rows.append([("📎 Файлом", f"pdoc:{k}:file"), ("↩ Откат", f"pdoc:{k}:undo"),
                 ("♻ Сброс", f"pdoc:{k}:reset")])
    return "\n".join(lines)[:3900], rows


def notes_card(doc: str = "intimate_kb") -> tuple[str, list[list[tuple[str, str]]]]:
    ns = notes()
    if not ns:
        text = "Заметок пока нет. «➕ Заметка» или фраза «запомни, что…» в режиме."
    else:
        text = "Заметки режима (нажми ✖, чтобы удалить):\n\n" + "\n".join(
            f"{i + 1}. {_short(n, 200)}" for i, n in enumerate(ns))
    rows = [[(f"✖ {i + 1}", f"pdoc:k:nd:{i}") for i in range(j, min(j + 5, len(ns)))]
            for j in range(0, min(len(ns), 40), 5)]
    rows.append([("➕ Заметка", "pdoc:k:note"), ("⬅ Назад", "pdoc:k:show")])
    return text[:3900], rows


# ── Ожидание значения после нажатия кнопки ───────────────────────────

_pending: dict | None = None   # {"doc", "op", "label", "ts"}


def pending_active() -> bool:
    return bool(_pending) and _time.monotonic() - _pending["ts"] < PENDING_TTL


def _ask(doc: str, op: str, label: str = "") -> str:
    global _pending
    _pending = {"doc": doc, "op": op, "label": label, "ts": _time.monotonic()}
    tail = "\n«-» — очистить, «отмена» — отменить."
    if op == "set":
        cur = dict(fields(doc)).get(label, EMPTY)
        return f"«{label}» сейчас: {_short(cur, 300)}\nНапиши новое значение.{tail}"
    if op == "add":
        return "Напиши новый параметр в виде «Название: значение»." + tail
    return "Напиши заметку." + tail


def handle_pending_input(text: str):
    """Значение для параметра, ожидаемого после кнопки. None — ничего не ждали."""
    global _pending
    if not pending_active():
        _pending = None
        return None
    p, _pending = _pending, None
    t = (text or "").strip()
    if t.lower() in ("отмена", "/отмена", "cancel", "/cancel"):
        return Reply("Отменила."), p["doc"]
    if p["op"] == "set":
        err = set_field(p["doc"], p["label"], t)
    elif p["op"] == "add":
        if ":" not in t:
            _pending = p | {"ts": _time.monotonic()}
            return Reply("Нужно «Название: значение». Ещё раз или «отмена»."), None
        lbl, val = t.split(":", 1)
        err = add_field(p["doc"], lbl, val)
    else:
        err = add_note(t)
    if err:
        return Reply(f"Не приняла: {err}."), p["doc"]
    return Reply("Готово."), p["doc"]


def handle_callback(data: str):
    """Нажатие кнопки → (Reply | None, что показать: 'card' | 'notes' | 'file' | None, doc)."""
    try:
        _, k, op, *rest = data.split(":")
        doc = _KEY_DOC[k]
    except (ValueError, KeyError):
        return None, None, None
    if op == "show":
        return None, "card", doc
    if op == "e":
        flds = fields(doc)
        i = int(rest[0]) if rest and rest[0].isdigit() else -1
        if not 0 <= i < len(flds):
            return Reply("Карточка устарела — открой заново."), "card", doc
        return Reply(_ask(doc, "set", flds[i][0])), None, doc
    if op == "add":
        return Reply(_ask(doc, "add")), None, doc
    if op == "note":
        return Reply(_ask(doc, "note")), None, doc
    if op == "notes":
        return None, "notes", doc
    if op == "nd":
        err = delete_note(int(rest[0])) if rest and rest[0].isdigit() else "нет номера"
        return (Reply(f"Не вышло: {err}.") if err else None), "notes", doc
    if op == "file":
        return None, "file", doc
    if op == "undo":
        ok = persona.rollback(doc, source="telegram")
        return Reply("Вернула предыдущую версию." if ok else "Предыдущих версий нет."), "card", doc
    if op == "reset":
        persona.reset(doc, source="telegram")
        return Reply("Сбросила к заводской."), "card", doc
    return None, None, None


# ── Текстовая команда ────────────────────────────────────────────────

def _file_reply(doc: str) -> Reply:
    text = persona.get(doc)
    return Reply(f"{_DOC_TITLES[doc].capitalize()} файлом. Исправь и пришли обратно "
                 f"с подписью «{_DOC_CMD[doc]}».",
                 file_name=f"sakura_{doc}.md", file_bytes=(text + "\n").encode("utf-8"))


def run_doc(doc: str, args: str, document_text: str | None = None) -> Reply | None:
    """Текстовая форма команды. None — показать карточку."""
    title, cmd = _DOC_TITLES[doc], _DOC_CMD[doc]
    if document_text is not None:
        err = _save(doc, document_text)
        return Reply(f"Не приняла: {err}." if err else
                     f"Готово: {title} обновлена целиком. Вернуть прежнюю — «{cmd} откат».")
    a = " ".join((args or "").split())
    low = a.lower()
    if not a:
        return None
    if low in ("сброс", "reset"):
        persona.reset(doc, source="telegram")
        return Reply(f"{title.capitalize()} — снова заводская.")
    if low in ("откат", "undo", "rollback"):
        ok = persona.rollback(doc, source="telegram")
        return Reply(f"{title.capitalize()} — предыдущая версия." if ok else "Предыдущих версий нет.")
    if low in ("файл", "file"):
        return _file_reply(doc)
    if doc == "intimate_kb" and low.split()[0] in ("заметка", "note"):
        err = add_note(a.split(maxsplit=1)[1] if " " in a else "")
        return Reply(f"Не приняла: {err}." if err else "Заметку записала.")
    if a.startswith("+"):
        body = a[1:].strip()
        if ":" not in body:
            return Reply(f"Свой параметр: «{cmd} + Название: значение».")
        lbl, val = body.split(":", 1)
        err = add_field(doc, lbl, val)
        return Reply(f"Не приняла: {err}." if err else f"Добавила «{lbl.strip()}».")
    if a.startswith("-") and len(a) > 1:
        err = remove_field(doc, a[1:])
        return Reply(f"Не вышло: {err}." if err else f"Убрала «{a[1:].strip()}».")
    # «параметр: значение» или «параметр значение» (самое длинное совпадение)
    if ":" in a:
        lbl, val = a.split(":", 1)
        p = _find(doc, lbl)
    else:
        words, p, val = a.split(), None, ""
        for n in range(len(words) - 1, 0, -1):
            p = _find(doc, " ".join(words[:n]))
            if p:
                val = " ".join(words[n:])
                break
    if not p:
        names = ", ".join(lbl.lower() for lbl, _ in fields(doc))
        return Reply(f"Не нашла параметр. Есть: {names}.\n"
                     f"Пример: «{cmd} {fields(doc)[0][0].lower() if fields(doc) else 'параметр'} …», "
                     f"свой — «{cmd} + Название: значение».")
    err = set_field(doc, p[2], val)
    return Reply(f"Не приняла: {err}." if err else f"«{p[2]}»: {_short(' '.join(val.split()), 200)}")


# «запомни…» внутри режима — в заметки базы режима, а не в основную память.
_REMEMBER_RX = _re.compile(
    r"(?:^|[,.!?]\s*|сакура,?\s+)запомни(?:\s+это)?(?:,?\s*что)?[:,]?\s+(?P<note>[^=\n]{3,300})$",
    _re.IGNORECASE)


def remember_note(text: str) -> bool:
    m = _REMEMBER_RX.search((text or "").strip())
    if not m:
        return False
    return add_note(m.group("note"), source="intimate-remember") is None


# ── aiogram ──────────────────────────────────────────────────────────

def _kb(rows):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


async def send_card(target, doc: str, *, edit: bool = False, which: str = "card"):
    import asyncio
    text, rows = await asyncio.to_thread(notes_card) if which == "notes" else await asyncio.to_thread(card, doc)
    if edit:
        try:
            await target.edit_text(text, reply_markup=_kb(rows))
            return
        except Exception:  # noqa: BLE001 — «не изменилось»/старое сообщение → новое
            pass
    await target.answer(text, reply_markup=_kb(rows))


async def _send_file(message, doc: str):
    from aiogram.types import BufferedInputFile
    r = _file_reply(doc)
    await message.answer_document(
        BufferedInputFile(r.file_bytes, filename=r.file_name), caption=r.text)


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
    if reply is None:
        await send_card(message, doc)
    elif reply.file_bytes is not None:
        await _send_file(message, doc)
    else:
        await message.answer(reply.text)
        if not reply.text.startswith(("Не ", "Свой")):
            await send_card(message, doc)


async def cmd_intimate_kb_impl(message, bot=None):
    await _doc_cmd_impl("intimate_kb", message, bot)


async def cmd_figure_impl(message, bot=None):
    await _doc_cmd_impl("intimate_figure", message, bot)


async def callback_impl(callback):
    import asyncio
    reply, show, doc = await asyncio.to_thread(handle_callback, callback.data or "")
    try:
        await callback.answer()
    except Exception:  # noqa: BLE001
        pass
    msg = callback.message
    if reply:
        await msg.answer(reply.text)
    if show == "file":
        await _send_file(msg, doc)
    elif show in ("card", "notes"):
        await send_card(msg, doc, edit=not reply, which=show)


async def pending_input_impl(message) -> bool:
    """Из обработчика сообщений Мастера: True — сообщение съедено редактором."""
    import asyncio
    if not pending_active():
        return False
    res = await asyncio.to_thread(handle_pending_input, message.text or "")
    if res is None:
        return False
    reply, doc = res
    await message.answer(reply.text)
    if doc:
        await send_card(message, doc)
    return True
