"""repeat_guard — не повторять недавние реплики по сути.

Механика по мотивам capri-desktop (Glances.Repeats/Keys), код свой.
Ключи реплики — то, о чём она: имена и названия (слово с заглавной не в
начале предложения, латиница — названия игр и программ), числа от двух
цифр. Реплика — повтор, если делит с недавней хотя бы один ключ или
похожа на неё по значимым словам (modules.proactive.is_semantically_similar).

Общий для взгляда (sakura_core/vision/glance.py) и других проактивных
реплик.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9'’\-]*|[.!?…]")
_LATIN = re.compile(r"^[A-Za-z][A-Za-z0-9'’\-]{2,}$")


def keys(line: str) -> set[str]:
    """Имена/названия и числа реплики, в нижнем регистре."""
    out: set[str] = set()
    text = re.sub(r"\[[^\]]*\]", ".", line or "")
    text = re.sub(r"(?<=\d)[\s ,](?=\d{3}(?!\d))", "", text)     # 1 000 → 1000
    letters = [c for c in text if c.isalpha()]
    shouting = letters and sum(c.isupper() for c in letters) * 2 > len(letters)
    start = True
    for tok in _TOKEN.findall(text):
        if tok in ".!?…":
            start = True
            continue
        low = tok.lower().replace("’", "'")
        if tok.isdigit():
            if len(tok) >= 2:
                out.add(low)
        else:
            latin_name = bool(_LATIN.match(tok)) and low not in _LATIN_PLAIN
            name = (not shouting and not start and tok[0].isupper() and len(tok) >= 3
                    and not low.startswith(_OWN))
            if latin_name or name:
                out.add(low)
        start = False
    return out


_LATIN_PLAIN = frozenset({"the", "and", "you", "ok", "okay", "lol", "wow", "omg", "gg", "yes", "nice"})
# Слова, которые Сакура пишет с заглавной в любой реплике, — не тема.
_OWN = ("мастер", "сакур")


def repeats(line: str, recent: list[str]) -> bool:
    if not line or not recent:
        return False
    mine = keys(line)
    norm = " ".join(line.lower().split())
    from modules.proactive import is_semantically_similar
    for old in recent:
        if not old:
            continue
        if " ".join(old.lower().split()) == norm:
            return True
        if mine & keys(old):
            return True
        if is_semantically_similar(line, old):
            return True
    return False
