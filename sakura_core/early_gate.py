"""Ранний шлюз голоса (perf/voice-2, п.c).

Фраза — вопрос (знак «?» или вопросительное слово) и в ней нет командных
глаголов реестра → шлюз VoiceGate открывается сразу: звук ответа не ждёт
вердикта LLM-классификатора, классификатор идёт параллельно. Вердикт
«команда» всё равно отменяет поток (до первого звука — если успел).

Сюда доходят только фразы, не совпавшие с реестром точно (шаг LLM
роутера), — «что играет» и прочие триггеры исполняются раньше.

Командные глаголы берутся из триггеров реестра (первое слово в
повелительном наклонении, инфинитивы): новые действия реестра
пополняют список сами.
"""

from __future__ import annotations

import functools
import re

import yaml

QUESTION_WORDS = frozenset({
    "что", "чего", "чем", "чём", "как", "какой", "какая", "какое", "какие",
    "каким", "какую", "каков", "почему", "зачем", "отчего", "когда", "где",
    "куда", "откуда", "кто", "кого", "кому", "кем", "чей", "чья", "чьё",
    "сколько", "ли", "разве", "неужели", "правда",
})
# Первые слова триггеров, похожие на повелительное наклонение, но не глаголы.
_NOT_VERBS = frozenset({"чай", "мини", "мои", "ачивки", "какой", "игровой"})
_IMPERATIVE = re.compile(r"(?:и|й|ь|йте|ите|ьте)$")
_ADJ_OR_NOUN = re.compile(r"(?:ий|ый|ость|ось|арь|ний|ень)$")
_INFINITIVE = re.compile(r"(?:ть|ться)$")
_WORD = re.compile(r"[а-яё]+")


def _is_verb(word: str, first: bool) -> bool:
    if word in _NOT_VERBS or word in QUESTION_WORDS or len(word) < 3:
        return False
    if _ADJ_OR_NOUN.search(word):
        return False
    if word.endswith("ой") and not word.endswith("рой"):
        return False            # прилагательные: «игровой»; глаголы: «открой»
    if _INFINITIVE.search(word):
        return True
    return first and bool(_IMPERATIVE.search(word))


@functools.lru_cache(maxsize=1)
def command_verbs() -> frozenset[str]:
    """Командные глаголы из триггеров реестра."""
    from sakura_core.registry import REGISTRY_PATH
    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or []
    verbs: set[str] = set()
    for decl in raw:
        for trigger in decl.get("triggers") or ():
            words = _WORD.findall(str(trigger).lower().replace("ё", "е"))
            for i, w in enumerate(words):
                if _is_verb(w, first=(i == 0)):
                    verbs.add(w)
    return frozenset(verbs)


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace("ё", "е"))


def is_question(text: str) -> bool:
    if "?" in (text or ""):
        return True
    return any(w in QUESTION_WORDS for w in _words(text))


_VERB_ENDING = re.compile(r"(?:ться|ть|ти|ай|ей|ой|уй|яй|и|й|ь)$")


@functools.lru_cache(maxsize=1)
def _verb_stems() -> frozenset[str]:
    """Основы командных глаголов: «открой» → «откр» ловит и «открыть»,
    «откроешь» («можешь открыть …?» — тоже просьба-команда)."""
    stems = set()
    for v in command_verbs():
        base = _VERB_ENDING.sub("", v)
        if len(base) >= 4:
            stems.add(base)
    return frozenset(stems)


def has_command_verb(text: str) -> bool:
    verbs, stems = command_verbs(), _verb_stems()
    for w in _words(text):
        if w in verbs:
            return True
        for base in stems:
            if w.startswith(base) and len(w) - len(base) <= 4:
                return True
    return False


def opens_early(text: str) -> bool:
    """Вопрос без командных глаголов реестра — шлюз открывается сразу."""
    return is_question(text) and not has_command_verb(text)
