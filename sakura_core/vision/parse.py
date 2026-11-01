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
        return _clean_answer(reply), ""
    answer = (reply or "")[:m.start()]
    saw = _clean((reply or "")[m.end():])[:SAW_MAX]
    return _clean_answer(answer), saw


def _clean_answer(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines()).strip()


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
        return "", "" if is_skip(say) else say
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
    return saw[:SAW_MAX], say
