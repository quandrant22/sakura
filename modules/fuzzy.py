"""
modules/fuzzy.py — нечёткое сопоставление команд (для STT-искажений).

Whisper иногда искажает слова: «дублируй»→«доблируй», «следующий»→«следущий».
Точное вхождение `in` такое не ловит. Эта утилита матчит слова с допуском.

ВАЖНО: применять только к НЕкритичным командам (браузер, музыка).
Для выключения/блокировки/чайника — всегда точное совпадение, чтобы
случайное созвучие не привело к нежелательному действию.

Защита от ложных срабатываний:
  - короткие слова (<5 букв) требуют более высокого порога
  - очень короткие (<4) — только точное совпадение
"""

import difflib


def _similar(a: str, b: str) -> float:
    """Похожесть двух слов 0..1 (SequenceMatcher, stdlib)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def word_matches(word: str, target: str, threshold: float = 0.8) -> bool:
    """
    Совпадает ли слово `word` с эталоном `target` с учётом опечаток.
    Короткие слова требуют точности — у них одна правка сильно меняет смысл
    («кот»/«код»), поэтому порог для них выше.
    """
    word, target = word.lower(), target.lower()
    if word == target:
        return True
    n = min(len(word), len(target))
    if n < 4:
        return False                      # слишком коротко для fuzzy
    if n < 5:
        threshold = max(threshold, 0.88)  # короткие — строже
    return _similar(word, target) >= threshold


def phrase_has(text: str, target: str, threshold: float = 0.8) -> bool:
    """
    Есть ли в фразе слово, похожее на `target`.
    Для многословных target («новая вкладка») проверяем что все слова
    target нашли похожую пару в тексте.
    """
    words = text.lower().split()
    t_parts = target.lower().split()
    if len(t_parts) == 1:
        return any(word_matches(w, target, threshold) for w in words)
    # многословный эталон — каждое слово должно найтись
    return all(
        any(word_matches(w, tp, threshold) for w in words)
        for tp in t_parts
    )


def phrase_has_any(text: str, targets, threshold: float = 0.8) -> bool:
    """True если хоть один из эталонов нечётко присутствует в тексте."""
    return any(phrase_has(text, t, threshold) for t in targets)


def best_match(word: str, candidates, threshold: float = 0.8):
    """Возвращает ближайший кандидат к слову или None."""
    word = word.lower()
    best, best_score = None, threshold
    for c in candidates:
        s = _similar(word, c.lower())
        if s >= best_score:
            best, best_score = c, s
    return best
