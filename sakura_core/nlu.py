"""Локальный разбор фразы для роутера: без сети и без LLM.

Здесь только работа с текстом:
  split_units      — фраза → части по союзам («и», «а потом», «затем», «,»);
  UnitGuard        — является ли часть фразы явной командой для данного
                     триггера (а не рассказом, жалобой или чужим глаголом);
  find_delay       — отложенное время («через час», «в 23:00»);
  implied_context  — контекст, который создаёт предыдущий шаг плана.

Решения (что исполнять) принимает sakura_core/router.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from sakura_core.registry import Declaration

# ── контракт LLM-разбора ────────────────────────────────────────────────


class LlmUnavailable(RuntimeError):
    """LLM-разбор не состоялся: сеть, таймаут, ключи, пустой ответ.

    Это не вердикт «разговор»: роутер обязан попробовать локальный разбор."""


@dataclass(frozen=True)
class IntentParse:
    """Результат структурированного разбора намерений.

    actions — действия по порядку: ((id, параметр | None), …); пусто — команд нет.
    chat    — во фразе есть разговорная часть, на которую нужно ответить.
    """

    actions: tuple[tuple[str, Optional[str]], ...] = ()
    chat: bool = False


# ── разбиение на части ──────────────────────────────────────────────────

# Порядок важен: длинные связки раньше коротких.
_SPLIT_RE = re.compile(
    r"\s*(?:"
    r"[,;]\s*(?:а\s+|и\s+)?(?:(?:потом|затем|после\s+этого|ещё|еще|также)\s+)?"
    r"|\s+(?:а\s+)?(?:потом|затем|после\s+этого)\s+"
    r"|\s+и\s+(?:(?:потом|затем|ещё|еще|также)\s+)?"
    r"|\s+плюс\s+"
    r"|\s+а\s+также\s+"
    r")\s*",
    re.IGNORECASE,
)
MAX_UNITS = 4


def split_units(text: str) -> list[tuple[str, str]]:
    """Фраза → [(часть, связка_перед_ней)]. Связка первой части — пустая.

    Одна часть — фразу делить не на что. Больше MAX_UNITS частей —
    это перечисление или рассказ, а не план: возвращается целая фраза.
    """
    s = (text or "").strip()
    if not s:
        return []
    units: list[tuple[str, str]] = []
    pos, sep = 0, ""
    for m in _SPLIT_RE.finditer(s):
        if m.start() == 0 or m.end() >= len(s):
            continue
        part = s[pos:m.start()].strip(" ,.;!?")
        if part:
            units.append((part, sep))
        sep = m.group(0)
        pos = m.end()
    tail = s[pos:].strip(" ,.;!?")
    if tail:
        units.append((tail, sep))
    if len(units) <= 1 or len(units) > MAX_UNITS:
        return [(s, "")]
    # «следующий трек, пожалуйста», «ну и погода» — часть из одних служебных
    # слов самостоятельной частью не является: фраза остаётся целой.
    if any(all(w in FILLERS for w in words(part)) for part, _ in units):
        return [(s, "")]
    return units


# ── допустимые слова вокруг триггера ────────────────────────────────────

# Вежливые обороты убираются целиком до проверки слов: в них есть «не»,
# которое вне оборота означает отрицание команды.
_POLITE_RE = re.compile(
    r"(?<!\w)(?:"
    r"если\s+(?:тебе\s+|вам\s+)?(?:не\s+)?(?:сложно|трудно|затруднит|можно)"
    r"|будь(?:те)?\s+(?:так\s+)?(?:добр[аы]?|любезн[аы]?|друг(?:ом)?|лапочкой)"
    r"|не\s+мог(?:ла)?\s+бы\s+(?:ты\s+)?"
    r"|(?:ты\s+)?не\s+могла\s+бы"
    r"|мог(?:ла)?\s+бы\s+(?:ты\s+)?"
    r"|можешь\s+(?:ли\s+)?(?:ты\s+)?"
    r"|я\s+(?:бы\s+)?(?:хочу|хотел|хотела)(?:\s+бы)?"
    r"|мне\s+(?:бы\s+)?(?:нужно|надо|хочется)"
    r")(?!\w)",
    re.IGNORECASE,
)

FILLERS = frozenset("""
пожалуйста плиз пж сакура слушай ну а и да давай давай-ка ка мне нам сейчас
быстренько быстро немного немножко чуть чуть-чуть чуточку ещё еще там тут это
эту этот кстати так вот теперь тогда уже снова опять на в во до к по для с
мою мой моё свою весь всю всё все же ж ли бы ты прошу будь-добра срочно просто
какая какой какие какое каков сколько есть у меня мои моя за как что где
""".split())

# Глаголы-носители: сами действия не называют («сделай потише»).
CARRIERS = frozenset("""
сделай сделайте поставь включи запусти давай покажи скажи расскажи дай
можешь можно хочу надо нужно
""".split())

SLOT_WORDS = frozenset("""
сегодня завтра послезавтра сейчас процент процента процентов градус градуса
градусов минут минуты минуту секунд секунды час часа часов раз раза
""".split())

# Слова, после которых триггер — уже не просьба (отрицание, чужая речь, прошлое).
NEGATIONS = frozenset({"не", "нельзя", "никогда", "ни"})
NARRATIVE = frozenset("""
вчера позавчера когда-то раньше сказал сказала сказали говорил говорила
попросил попросила написал написала помнишь думал думала хотел хотела был
была были было
""".split())

# Слоты домена после триггера: «погода завтра в Питере» — город и «будет»
# относятся к запросу, посторонним текстом не считаются.
_DOMAIN_SLOTS = {
    "weather": re.compile(
        r"(?<!\w)(?:(?:в|во)\s+[a-zа-яё\-]+|будет|ожидается|обещают|ждать)(?!\w)",
        re.IGNORECASE),
}

# Окончания повелительного наклонения: «скинь», «отправь», «перешли», «покажите».
_IMPERATIVE_RE = re.compile(r"(?:[ьй]|[^аеёиоуыэюя]и|ите|йте|ьте)$")

_WORD_RE = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9\-]*", re.IGNORECASE)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _stem(word: str) -> str:
    """Грубая основа: без окончания, чтобы «музыку» узнала «музыка»."""
    return word[:4] if len(word) >= 5 else word


def strip_polite(text: str) -> str:
    return _POLITE_RE.sub(" ", text or "")


class UnitGuard:
    """Проверка «часть фразы — явная команда» для сработавшего триггера.

    Словарь домена строится из самого реестра: слова триггеров и описаний
    всех действий с тем же префиксом id («music.» — музыку, трек, песню…).
    Ручной список на каждое действие не нужен.
    """

    def __init__(self, declarations: Iterable[Declaration],
                 free_tail: Iterable[str] = ()):
        self._vocab: dict[str, set[str]] = {}
        self._free_tail = set(free_tail)
        for d in declarations:
            vocab = self._vocab.setdefault(self.domain(d.id), set())
            for chunk in (*d.triggers, d.desc):
                for w in words(chunk):
                    if len(w) >= 3:
                        vocab.add(_stem(w))
            if d.param is not None:
                self._free_tail.add(d.id)

    @staticmethod
    def domain(action_id: str) -> str:
        return (action_id or "").partition(".")[0]

    def takes_free_tail(self, action_id: str) -> bool:
        """После триггера идёт свободный текст (название, задача, запрос)."""
        return action_id in self._free_tail

    def _allowed(self, word: str, domain: str) -> bool:
        if word in FILLERS or word in CARRIERS or word in SLOT_WORDS:
            return True
        if word.isdigit() or re.fullmatch(r"\d+[%°]?", word):
            return True
        return _stem(word) in self._vocab.get(domain, ())

    def _span(self, text: str, trigger: str,
              decl: Optional[Declaration] = None) -> Optional[tuple[str, str]]:
        """Текст до и после команды. Командой считается триггер вместе с
        совпадением шаблона параметра: в «разверни хром на весь экран»
        слово «хром» — аргумент, а не посторонний текст."""
        m = re.search(rf"(?<!\w){re.escape(trigger)}(?!\w)", text, re.IGNORECASE)
        if not m:
            return None
        start, end = m.start(), m.end()
        if decl is not None and decl.param is not None:
            pm = re.search(decl.param.pattern, text, re.IGNORECASE)
            if pm:
                start, end = min(start, pm.start()), max(end, pm.end())
        after = text[end:]
        slots = _DOMAIN_SLOTS.get(self.domain(decl.id)) if decl is not None else None
        if slots is not None:
            after = slots.sub(" ", after)
        return text[:start], after

    def is_command(self, text: str, trigger: str, decl: Declaration) -> bool:
        """Строгая проверка быстрого пути (без LLM).

        До триггера — только обращения, вежливые слова, глаголы-носители
        и слова домена (или одно «я»/«мы»: «я выполнил задачу 5»).
        После триггера:
          • действие со свободным хвостом — что угодно (это его аргумент);
          • триггер из нескольких слов — что угодно (сам триггер уже
            однозначен: «какая погода завтра в Питере»);
          • триггер из одного слова («дальше», «погода», «стоп») — только
            допустимые слова: иначе это слово внутри чужой фразы.
        """
        span = self._span(strip_polite(text), trigger, decl)
        if span is None:
            # Триггер попал внутрь вежливого оборота — проверяем исходный текст.
            span = self._span(text, trigger, decl)
            if span is None:
                return False
        before, after = span
        domain = self.domain(decl.id)
        prefix = words(before)
        if any(w in NEGATIONS or w in NARRATIVE for w in prefix):
            return False
        single = " " not in trigger.strip()
        if single and prefix[:2] == ["ну", "и"]:
            return False        # «ну и погода» — восклицание, не просьба
        if prefix not in (["я"], ["мы"]) and not all(self._allowed(w, domain) for w in prefix):
            return False
        if not single or self.takes_free_tail(decl.id):
            return True
        return all(self._allowed(w, domain) for w in words(after))

    def is_plausible(self, text: str, trigger: str, decl: Declaration) -> bool:
        """Мягкая проверка — запасной путь, когда LLM недоступен.

        Лучше исполнить вероятную команду, чем молча принять её за болтовню:
        для триггера из нескольких слов запрещены только отрицание и пересказ
        перед ним. Однословный триггер («погода», «дальше») и здесь проверяется
        строго: без модели отличить его от слова в рассказе нечем.
        """
        if " " not in trigger.strip() and not self.takes_free_tail(decl.id):
            return self.is_command(text, trigger, decl)
        span = self._span(strip_polite(text), trigger, decl) or self._span(text, trigger, decl)
        if span is None:
            return False
        before, after = span
        prefix = words(before)
        if any(w in NEGATIONS or w in NARRATIVE for w in prefix):
            return False
        if len(prefix) > 4:
            return False
        # Чужой глагол в повелительном наклонении перед триггером («скинь
        # следующий трек другу») — просьба о другом, не эта команда.
        domain = self.domain(decl.id)
        return not any(len(w) >= 4 and _IMPERATIVE_RE.search(w)
                       and not self._allowed(w, domain) for w in prefix)


# ── отложенное время ────────────────────────────────────────────────────

_DELAY_RE = re.compile(
    r"(?<!\w)(?:"
    r"через\s+(?:\d+\s*)?(?:пол\s*часа|полчаса|час(?:а|ов)?|минут[уы]?|мин|секунд[уы]?|"
    r"пару\s+\w+|несколько\s+\w+|[а-яё]+\s+(?:час(?:а|ов)?|минут[уы]?))"
    r"|в\s+\d{1,2}(?:[:.]\d{2})"
    r"|в\s+\d{1,2}\s+(?:час(?:а|ов)?|утра|вечера|ночи|дня)"
    r"|(?:после|до)\s+\d{1,2}(?:[:.]\d{2})?"
    r"|в\s+(?:полночь|полдень)"
    r"|(?:ближе\s+к\s+)?(?:вечером|утром|ночью|попозже|позже|потом)"
    r"|когда\s+\w+"
    r")(?!\w)",
    re.IGNORECASE,
)


def find_delay(text: str) -> Optional[str]:
    """«через час», «в 23:00», «вечером» → найденный оборот, иначе None."""
    m = _DELAY_RE.search(text or "")
    return m.group(0).strip() if m else None


# ── контекст следующего шага ────────────────────────────────────────────

_IMPLIED = {"music": "playing:music", "youtube": "window:youtube",
            "browser": "window:browser"}


def implied_context(action_id: str, param: Optional[str] = None) -> Optional[str]:
    """Что станет верным после шага: «включи музыку» → играет музыка,
    поэтому следующее «сделай погромче» относится к ней."""
    domain = UnitGuard.domain(action_id)
    if domain == "open":
        p = (param or "").lower()
        return "playing:music" if not p or "музык" in p else None
    return _IMPLIED.get(domain)
