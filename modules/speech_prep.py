"""Подготовка текста к речи — только для текста, который идёт в TTS.

Чат, история и Telegram не трогаются: функция зовётся в tts_server при
сборке реплики Live-сессии.

  числа и единицы → словами: «23°C» → «двадцать три градуса Цельсия»,
    «3 м/с», «15%», «60 км/ч», «8 ГБ», «120 мс»;
  латиница → кириллица по словарю data/pronunciation.json (редактируемый).
"""

from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

PRONUNCIATION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "data", "pronunciation.json")

_ONES_M = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_ONES_F = ["ноль", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
          "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
         "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
             "восемьсот", "девятьсот"]
_SCALES = [(("тысяча", "тысячи", "тысяч"), True),
           (("миллион", "миллиона", "миллионов"), False),
           (("миллиард", "миллиарда", "миллиардов"), False)]


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Форма слова для числа: (1 градус, 2 градуса, 5 градусов)."""
    n = abs(n)
    if n % 100 in range(11, 15):
        return forms[2]
    if n % 10 == 1:
        return forms[0]
    if n % 10 in (2, 3, 4):
        return forms[1]
    return forms[2]


def _triple(n: int, feminine: bool) -> list[str]:
    words = []
    h, rest = divmod(n, 100)
    if h:
        words.append(_HUNDREDS[h])
    if 10 <= rest < 20:
        words.append(_TEENS[rest - 10])
    else:
        t, o = divmod(rest, 10)
        if t:
            words.append(_TENS[t])
        if o:
            words.append((_ONES_F if feminine else _ONES_M)[o])
    return words


def number_words(n: int, feminine: bool = False) -> str:
    """Целое число словами (именительный падеж), до миллиардов."""
    if n == 0:
        return "ноль"
    if n < 0:
        return "минус " + number_words(-n, feminine)
    words: list[str] = []
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if not g:
            continue
        if idx == 0:
            words += _triple(g, feminine)
        else:
            forms, fem = _SCALES[idx - 1]
            if g != 1:              # «тысяча», а не «одна тысяча»
                words += _triple(g, fem)
            words.append(plural(g, forms))
    return " ".join(words)


# Единицы: шаблон → (формы, женский род числительного, хвост)
_UNITS = [
    (r"°\s*[CС]", ("градус", "градуса", "градусов"), False, " Цельсия"),
    (r"°", ("градус", "градуса", "градусов"), False, ""),
    (r"%", ("процент", "процента", "процентов"), False, ""),
    (r"км/ч", ("километр", "километра", "километров"), False, " в час"),
    (r"м/с", ("метр", "метра", "метров"), False, " в секунду"),
    (r"[ГG][БB]", ("гигабайт", "гигабайта", "гигабайт"), False, ""),
    (r"[МM][БB]", ("мегабайт", "мегабайта", "мегабайт"), False, ""),
    (r"мс", ("миллисекунда", "миллисекунды", "миллисекунд"), True, ""),
]
_NUM = r"(?<![\w.,])(-?\d+(?:[.,]\d+)?)"
_UNIT_RES = [(re.compile(_NUM + r"\s*" + pat + r"(?!\w)"), forms, fem, tail)
             for pat, forms, fem, tail in _UNITS]
_BARE_NUM = re.compile(_NUM + r"(?![\w.,]\d)")


def _decimal_words(raw: str, forms=None, fem=False, tail="") -> str:
    raw = raw.replace(",", ".")
    if "." not in raw:
        n = int(raw)
        out = number_words(n, fem)
        return f"{out} {plural(n, forms)}{tail}" if forms else out
    whole, frac = raw.split(".", 1)
    frac = frac.rstrip("0") or "0"
    w = int(whole)
    f = int(frac)
    denom = {1: ("десятая", "десятых", "десятых"), 2: ("сотая", "сотых", "сотых")}.get(
        len(frac), ("тысячная", "тысячных", "тысячных"))
    out = (f"{number_words(w, True)} {plural(w, ('целая', 'целых', 'целых'))} "
           f"{number_words(f, True)} {plural(f, denom)}")
    # С дробным числом единица — в родительном падеже единственного числа.
    return f"{out} {forms[1]}{tail}" if forms else out


_words_cache: tuple[float, list[tuple[re.Pattern, str]]] | None = None


def _dictionary() -> list[tuple[re.Pattern, str]]:
    """Словарь произношений; перечитывается при изменении файла."""
    global _words_cache
    try:
        mtime = os.path.getmtime(PRONUNCIATION_FILE)
    except OSError:
        return []
    if _words_cache and _words_cache[0] == mtime:
        return _words_cache[1]
    try:
        with open(PRONUNCIATION_FILE, encoding="utf-8") as f:
            words = json.load(f).get("words", {})
    except (OSError, ValueError) as e:
        log.warning(f"[speech_prep] словарь не прочитан: {type(e).__name__}: {e}")
        return []
    pats = [(re.compile(rf"(?<!\w){re.escape(k)}(?!\w)", re.IGNORECASE), v)
            for k, v in sorted(words.items(), key=lambda kv: -len(kv[0]))]
    _words_cache = (mtime, pats)
    return pats


def prepare(text: str) -> str:
    """Текст для озвучки: числа/единицы словами, латиница по словарю."""
    if not text:
        return text
    for rx, forms, fem, tail in _UNIT_RES:
        text = rx.sub(lambda m: _decimal_words(m.group(1), forms, fem, tail), text)
    text = _BARE_NUM.sub(lambda m: _decimal_words(m.group(1)), text)
    for rx, repl in _dictionary():
        text = rx.sub(repl, text)
    return text
