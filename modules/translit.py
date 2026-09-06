"""
modules/translit.py — ЕДИНАЯ нормализация названий: транслитерация
(кириллица → латиница) + фонетическая нормализация.

Нужна в двух рантаймах:
  - сервер (VPS): modules/steam_integration.search_game() — резолв игр
    по разговорным названиям («ремнант», «палворлд», «фоллаут шелтер»);
  - агент (laptop): agent/core/hands.py — резолв приложений для запуска.

Одна реализация на обоих: агент импортирует отсюда (корень репо в sys.path).
Если modules/ недоступен (автономная PyInstaller-сборка агента) — hands.py
держит помеченную копию; паритет проверяет tests/test_translit.py
(золотой корпус + идентичность функций при живом импорте).
"""

import re

# ── Транслитерация (кириллица → латиница, включая частые сочетания) ──
_TRANSLITERATION_MAP = {
    # Сочетания (проверяются ДО одиночных букв)
    'дж': 'j', 'дз': 'dz', 'кс': 'x',
    # Гласные
    'а': 'a', 'е': 'e', 'ё': 'yo', 'и': 'i', 'о': 'o', 'у': 'u',
    'ы': 'y', 'э': 'e', 'я': 'ya', 'ю': 'yu',
    # Согласные
    'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'ж': 'zh', 'з': 'z',
    'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'п': 'p',
    'р': 'r', 'с': 's', 'т': 't', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ь': '',
}


def transliterate(text: str) -> str:
    """Кириллица → латиница, включая частые сочетания (дж/кс/...)."""
    text = (text or "").lower()
    result = []
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in _TRANSLITERATION_MAP:
            result.append(_TRANSLITERATION_MAP[pair])
            i += 2
            continue
        result.append(_TRANSLITERATION_MAP.get(text[i], text[i]))
        i += 1
    return "".join(result)


def phonetic_normalize(text: str) -> str:
    """Фонетическая нормализация латинских строк: ph→f, ck→k, oo→u, ee→i,
    w↔v, o↔a, схлопывание удвоенных согласных."""
    text = (text or "").lower()
    text = re.sub(r'ph', 'f', text)
    text = re.sub(r'ck', 'k', text)
    text = re.sub(r'oo', 'u', text)
    text = re.sub(r'ee', 'i', text)
    text = text.replace('w', 'v')
    text = re.sub(r'(.)\1+', r'\1', text)
    text = re.sub(r'[oa]', 'a', text)
    return text


# Разделители, вырезаемые при нормализации имён
_SEP_RE = r'[\s\-_:;,.()\[\]\'"!+&/]'


def normalize_name(name: str) -> str:
    """Транслит + фонетика + удаление спецсимволов → одна строка
    («Remnant: From the Ashes» и «ремнант фром зе эйс» сравнимы целиком)."""
    name = transliterate(name)
    name = phonetic_normalize(name)
    name = re.sub(_SEP_RE, '', name)
    return name.strip()


def normalize_tokens(name: str) -> list:
    """Токены после транслита/фонетики (для поиска по словам)."""
    name = transliterate(name)
    name = phonetic_normalize(name)
    name = re.sub(_SEP_RE, ' ', name)
    return [t for t in name.split() if t]


# ── Стоп-токены: артикли/предлоги/союзы ──────────────────────────────
# При матче по словам игнорируются: «ремнант фром зе эйс» =
# «Remnant: From the Ashes». Хранятся в УЖЕ нормализованном виде
# (транслит + фонетика): the→the, зе→ze; of→af, оф→af; фром→fram, ...
_STOP_WORDS = (
    "the", "a", "an", "of", "from", "to", "in", "on", "for", "and", "&",
    # частые русские прочтения тех же слов
    "зе", "зи", "оф", "ов", "фром", "ин", "он", "ту", "фор", "энд",
)
_STOP_TOKENS = frozenset(
    phonetic_normalize(transliterate(w)) for w in _STOP_WORDS if w)


def content_tokens(name: str) -> list:
    """Значимые токены: нормализация + выбрасывание артиклей/предлогов
    и однобуквенных осколков («s» из «Man's», «V» и т.п. — при матче
    они дают ложные вхождения)."""
    return [t for t in normalize_tokens(name)
            if len(t) >= 2 and t not in _STOP_TOKENS]
