"""Разбор ответов модели зрения.

Разовый вопрос: ответ Мастеру + последняя строка «ВИДЕЛА: …» (для памяти).
Взгляд: «ВИДЕЛА: … СКАЖУ: …»; «ПРОПУСК» — молчать. Неуверенность в
ВИДЕЛА («кажется», «не видно») — тоже молчать: маленькие модели угадывают
игру по размытой картинке.
"""

from __future__ import annotations

import re

_SAW = r"(?:ВИДЕЛА|SAW)"
_SAY = r"(?:СКАЖУ|SAY)"
_LABEL = re.compile(rf"(?<![\w])(?P<label>{_SAW}|{_SAY})[*_]*\s*[:—-][*_]*", re.IGNORECASE)
_SKIP = re.compile(r"^[\[(«\"]?\s*(ПРОПУСК|SKIP|НИЧЕГО|NONE)\s*[\])»\"]?[.!?…]*$", re.IGNORECASE)
_UNSURE = re.compile(
    r"(?<!\w)(кажется|наверное|вероятно|возможно|похоже|видимо|не\s+уверен\w*|"
    r"не\s+видно|не\s+разобрать|не\s+могу\s+(?:разглядеть|понять|прочитать)|"
    r"неясно|непонятно|размыт\w*|maybe|probably|unclear|not\s+sure)(?!\w)",
    re.IGNORECASE)
SAW_MAX = 200

# Отчёт модели о правилах вместо ответа: «имён на экране нет», «больше
# ничего не заметила», «пароли не пересказываю». Такие предложения вырезаются.
_META = re.compile(
    r"(?<!\w)("
    r"(?:им[её]н\w*|имени|подпис\w*)[^.!?…]*\b(?:нет|не\s+вижу|не\s+видно|не\s+написан\w*|не\s+указан\w*)|"
    r"(?:нет|не\s+вижу|не\s+видно)[^.!?…]*\b(?:им[её]н\w*|имени)|"
    r"больше\s+ничего[^.!?…]*\b(?:не\s+(?:заметил\w*|вижу|видно|могу)|нет)|"
    r"ничего\s+(?:особенного|примечательного)[^.!?…]*\b(?:не\s+(?:заметил\w*|вижу|видно)|нет)|"
    r"по\s+лицу|не\s+(?:буду\s+)?(?:угадывать|гадать)|"
    r"(?:пароли|личн\w+\s+переписк\w*)[^.!?…]*\bне\s+(?:пересказываю|называю|читаю)"
    r")(?!\w)",
    re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def drop_meta(text: str) -> str:
    """Убрать из ответа предложения-отчёты о правилах (см. _META)."""
    kept = [s.strip() for s in _SENTENCE_END.split(text or "") if s.strip() and not _META.search(s)]
    return " ".join(kept).strip()


def _clean(text: str) -> str:
    text = re.sub(r"[*_`#]+", "", text or "")
    return " ".join(text.split()).strip(" -—:")


def is_skip(text: str) -> bool:
    return bool(_SKIP.match(_clean(text))) or not re.search(r"\w", text or "")


def split_ask(reply: str) -> tuple[str, str]:
    """(ответ Мастеру, что видела). Без метки — весь текст ответ, saw пуст."""
    m = None
    for m in re.finditer(rf"(?im)^\s*{_SAW}[*_]*\s*[:—-]", reply or ""):
        pass
    if m is None:
        return clean_answer(reply), ""
    answer = (reply or "")[:m.start()]
    saw = _clean((reply or "")[m.end():])[:SAW_MAX]
    return clean_answer(answer), saw


def clean_answer(text: str) -> str:
    lines = (drop_meta(line) for line in (text or "").strip().splitlines())
    return "\n".join(line for line in lines if line).strip()


def parse_glance(reply: str) -> tuple[str, str]:
    """(что видела, что сказать). Пустая реплика — молчать.

    ПРОПУСК целиком — ("", ""). Неуверенность в ВИДЕЛА — saw и реплика
    отбрасываются. Без меток весь ответ — реплика."""
    text = reply or ""
    if is_skip(text):
        return "", ""
    labels = list(_LABEL.finditer(text))
    if not labels:
        say = _clean(text)
        return "", "" if is_skip(say) else drop_meta(say)
    saw = say = ""
    for i, m in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        part = _clean(text[m.end():end])
        if re.fullmatch(_SAW, m.group("label"), re.IGNORECASE):
            saw = saw or part
        else:
            say = say or part
    if is_skip(saw):
        saw = ""
    if is_skip(say):
        say = ""
    if saw and _UNSURE.search(saw):
        return "", ""
    return saw[:SAW_MAX], drop_meta(say)


_EXTRACT_LABEL = re.compile(r"(?im)^\s*[*_]*(?P<label>ВИДЕЛА|ФАКТЫ|ПОИСК)[*_]*\s*[:—-][*_]*")
QUERY_MAX = 120
FACTS_MAX = 600


def _none(text: str) -> bool:
    return not text or bool(re.fullmatch(r"[\[(«\"]?\s*(НЕТ|NONE|-|—)\s*[\])»\"]?[.!]*", text, re.IGNORECASE))


def parse_extract(reply: str) -> tuple[str, str, str]:
    """Ответ модели зрения на разовый вопрос → (видела, факты, запрос поиска).

    «НЕТ» → пусто. Запрос — одна строка до QUERY_MAX, без кавычек."""
    text = reply or ""
    found = {"ВИДЕЛА": "", "ФАКТЫ": "", "ПОИСК": ""}
    labels = list(_EXTRACT_LABEL.finditer(text))
    for i, m in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        key = m.group("label").upper()
        if not found[key]:
            found[key] = _clean(text[m.end():end])
    if not labels:
        found["ВИДЕЛА"] = _clean(text)
    saw, facts, query = (found[k] for k in ("ВИДЕЛА", "ФАКТЫ", "ПОИСК"))
    saw = "" if _none(saw) else saw[:SAW_MAX]
    facts = "" if _none(facts) else facts[:FACTS_MAX]
    query = "" if _none(query) else query.strip("«»\"' ")[:QUERY_MAX]
    return saw, facts, query
