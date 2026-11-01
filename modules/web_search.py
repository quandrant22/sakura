"""
web_search.py — Умный веб-поиск для Сакуры.
Оптимизирован: последовательный fetch вместо параллельного,
gc.collect() после работы с BeautifulSoup.
"""

import gc
import logging
import re
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

SEARCH_TRIGGERS_HARD = [
    "найди в интернете", "найди информацию", "поищи в интернете",
    "загугли", "найди в гугле", "найди в яндексе",
    "что говорил", "что написано", "что сказал",
    "цитата", "цитату", "точная фраза",
    "последние новости", "свежие новости", "актуально",
    "курс", "погода сейчас", "сейчас стоит",
]

SEARCH_TRIGGERS_SOFT = [
    "что такое", "кто такой", "кто такая",
    "расскажи про", "расскажи о",
    "как работает", "как устроен",
    "где находится", "когда произошло",
    "сколько стоит", "где купить",
    "как называется", "что значит",
    "в каком году", "кто написал", "кто снял",
    "какой рейтинг", "какие отзывы",
    "wiki", "wikipedia",
]

SEARCH_STOP = [
    "как дела", "как ты", "что делаешь", "как настроение",
    "привет", "пока", "спасибо", "окей", "ладно",
    "помоги мне написать", "напиши код", "переведи",
    "объясни мне", "расскажи историю",
    # Бытовые реплики/эмоции — не поиск (даже внутри с существительными)
    "я устал", "я устала", "устал", "устала", "хочу спать",
    "еду домой", "дорога домой", "доехал",
    "сегодня был", "сегодня была", "сегодня было",
    "вчера был", "вчера была",
]

# Глаголы поиска, с которых начинается ПРЯМАЯ просьба («найди Х», «поищи Х»,
# «загугли Х» / «погугли Х» + любое продолжение). Проверяются только в начале
# фразы и по границам слов: «перенайди мне песню» и «найдись» не срабатывают.
# «поиши» — частый вариант распознавания Vosk от «поищи».
_SEARCH_LEAD_VERBS = (
    "найдите", "найди",
    "поищите", "поищи", "поиши",
    "загуглите", "загугли",
    "погуглите", "погугли",
)
_SEARCH_LEAD_RE = re.compile(
    r"^(?:" + "|".join(re.escape(v) + r"\b" for v in _SEARCH_LEAD_VERBS) + r")"
)


# Вопросы о СВОЁМ состоянии (притяжательное «у меня/мой/…») —
# НИКОГДА не поиск. Ответы берутся из состояния системы
# (music:now_playing, tasks, наигранные часы), а в интернете их нет:
# поиск по «что у меня играет» возвращал выдумку
# («Nickelback» вместо реального трека).
# Работает и при искажениях STT («Какое трек у меня сейчас играет»).
# Вопросительность фразы НЕ требуется: «сколько я наиграл в X»
# поиск не запускает в любом случае.
_SELF_STATE_RE = re.compile(
    r"(?<!\w)(?:"
    r"у\s+меня|мой|моя|мо[её]|мои|моих|моим|мне|мной"  # притяжательные
    r"|я\s+сейчас|что\s+я\s+сейчас|сколько\s+я\s+наиграл"  # «я сейчас…»
    r"|что\s+(?:я\s+|мы\s+)?слушал\w*|что\s+играло|что\s+был\w*\s+в\s+плейлист"
    r"|последни\w+\s+трек\w*|каки\w+\s+трек\w*|истори\w+\s+музык\w*"  # муз. статистика
    r")"
)

# ── Вспомогательные константы для needs_search ────────────────────────
_QUESTION_WORDS = (
    "кто", "какой", "какая", "какие", "что", "где", "когда",
    "как", "почему", "зачем", "сколько",
)
# Маркеры актуальности — «сейчас / сегодня / последний / текущий / …»
_TIME_MARKERS = (
    "сейчас", "сегодня", "вчера", "недавно", "недавней",
    "последний", "последняя", "последние",
    "крайний", "крайняя", "крайние",
    "текущий", "текущая", "текущие",
    "актуальн", "свеж", "свежие", "новости", "курс",
)
_TIME_MARKER_SET = set(_TIME_MARKERS)
_QUESTION_WORD_SET = set(_QUESTION_WORDS)


def _word_in(text: str, phrases: list[str]) -> bool:
    """True, если фраза встречается в *text* целиком — по границам слов.

    Решает класс бага подстрочного матча («гром» ловил «громче», «свет» — «рассвет»).
    """
    for phrase in phrases:
        pat = r"(?<![\w])" + re.escape(phrase) + r"(?![\w])"
        if re.search(pat, text):
            return True
    return False


def _starts_with_search_verb(text_lower: str) -> bool:
    """Глагол поиска в НАЧАЛЕ фразы → прямая просьба найти в интернете.

    «найди рецепт борща», «поищи погоду», «загугли что такое MCP» → True,
    продолжение роли не играет. Границы слов сохранены:
    «перенайди мне песню», «найдись» → False.
    """
    return bool(_SEARCH_LEAD_RE.match(text_lower))


def _has_question_word(words: list[str]) -> bool:
    for w in words:
        w = w.strip("«»\"',.?!-…")
        if w and w.lower() in _QUESTION_WORD_SET:
            return True
    return False


def _has_proper_noun(orig_words: list[str]) -> bool:
    """Имя собственное — слово с заглавной буквы НЕ на первом месте."""
    for i, w in enumerate(orig_words):
        w = w.strip("«»\"',.?!-…")
        if i > 0 and len(w) > 1 and w[0].isalpha() and w[0].isupper():
            return True
    return False


def _has_time_marker(text_lower: str) -> bool:
    return _word_in(text_lower, list(_TIME_MARKERS))


def _is_question(words: list[str]) -> bool:
    """Фраза является вопросом: '?' в конце ИЛИ вопросительное слово в начале.

    Повествовательные бытовые реплики («сегодня был в парке»,
    «еду домой») НЕ считаются вопросами, даже если в середине есть
    маркер времени или существительное.
    """
    if not words:
        return False
    first = words[0].strip("«»\"',.?!-…").lower()
    if first in _QUESTION_WORD_SET:
        return True
    # вопросительный знак — грамматический маркер вопроса без слова
    return any(w.endswith("?") for w in words)


def needs_search(text: str) -> bool:
    """Решает, идёт ли запрос в поиск (Parallel Search MCP).

    Поиск — ТОЛЬКО по прямому запросу Мастера:
      * а) явный глагол поиска в начале («найди», «поищи», «загугли»,
        «погугли») + любое продолжение;
      * б) вопрос о фактах, которых модель знать не может (цены, курсы,
        «кто сейчас», «когда выйдет», игровые/технические детали) — И при
        этом фраза ЯВЛЯЕТСЯ вопросом: вопросительное слово в начале или
        «?» в конце.
    Никогда НЕ ищутся: утверждения, рассказы о себе, бытовые реплики,
    эмоции — даже если содержат существительные. Приветы/команды — мимо.
    """
    if not text:
        return False
    tl = text.lower().strip()
    if not tl:
        return False
    words = tl.split()
    orig_words = text.split()

    # Приветы / команды / бытовое — не ищем (по границам слов)
    if _word_in(tl, SEARCH_STOP):
        return False
    # а) прямая просьба: глагол поиска в начале фразы + любое продолжение
    if _starts_with_search_verb(tl):
        return True
    # Вопросы о СВОЁМ состоянии — НИКОГДА не поиск (до гейта
    # вопросительности: «сколько я наиграл в X» не ищет в любом виде).
    # Ответ берётся из состояния системы, в интернете его нет.
    if _SELF_STATE_RE.search(tl):
        return False
    # б) дальше — ТОЛЬКО вопросы: без вопросительной структуры поиска нет
    if not _is_question(words):
        return False
    # Жёсткие/мягкие триггеры — ищем (фраза-вопрос)
    if _word_in(tl, SEARCH_TRIGGERS_HARD):
        return True
    if _word_in(tl, SEARCH_TRIGGERS_SOFT):
        return True

    has_q = _has_question_word(words)
    has_proper = _has_proper_noun(orig_words)
    has_time = _has_time_marker(tl)

    # Вопросительное слово + имя собственное
    if has_q and has_proper:
        return True
    # Маркер времени + существительное (хотя бы одно «весомое» слово)
    if has_time:
        rest = [w for w in words if w not in _TIME_MARKER_SET and not _has_question_word([w])]
        if rest:
            return True
    return False


async def fetch_page(url: str, max_chars: int = 3000) -> str:
    """Загружает страницу. Уменьшен max_chars для экономии RAM."""
    try:
        async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return ""

            soup = BeautifulSoup(r.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer",
                              "header", "aside", "form", "iframe"]):
                tag.decompose()

            main = (
                soup.find("article") or
                soup.find("main") or
                soup.find(id=re.compile(r"content|article|main", re.I)) or
                soup.find(class_=re.compile(r"content|article|post|entry", re.I)) or
                soup.body
            )

            if not main:
                return ""

            text  = main.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 40]
            result = "\n".join(lines)[:max_chars]

            # Явно освобождаем soup
            soup.decompose()
            del soup, main
            gc.collect()

            return result

    except Exception as e:
        log.debug(f"fetch_page error ({url}): {e}")
        return ""


async def _get_search_links(query: str, count: int = 4) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
            if r.status_code != 200:
                return []

            soup  = BeautifulSoup(r.text, "lxml")
            links = []
            for result in soup.select(".result__url"):
                href = result.get("href") or result.get_text(strip=True)
                if href and href.startswith("http"):
                    if not any(bad in href for bad in [
                        "duckduckgo.com", "google.com", "bing.com",
                        "facebook.com", "twitter.com", "instagram.com",
                    ]):
                        links.append(href)
                if len(links) >= count:
                    break

            soup.decompose()
            del soup
            gc.collect()
            return links
    except Exception as e:
        log.error(f"DDG search error: {e}")
        return []


async def search_and_fetch(query: str, max_chars: int = 3000, max_results: int | None = None) -> str:
    """Факты из интернета текстом (+ источники) через единый конвейер поиска.

    Раньше: Brave (без ключа не работал) → «ответ Gemini из памяти» под видом
    интернета — источник выдумок. Теперь — только найденное; ничего — пусто.
    max_results оставлен ради старых вызовов (modules/autonomous.py)."""
    from sakura_core.search import run
    try:
        ev = await run(query, channel="background")
    except Exception as e:
        log.warning(f"[search] search_and_fetch: {type(e).__name__}: {e}")
        return ""
    if not ev.ok:
        return ""
    items = ev.items[:max_results] if max_results else ev.items
    from sakura_core.search.pipeline import build_facts
    text = build_facts(items, max_chars)
    urls = [it["url"] for it in items if it.get("url")][:3]
    if urls:
        text += "\n\nИсточники:\n" + "\n".join(f"• {u}" for u in urls)
    return text[:max_chars + 300]


async def smart_search(query: str) -> str:
    """Поиск, только если вопрос этого требует (needs_search)."""
    if not needs_search(query):
        return ""
    return await search_and_fetch(query)


async def search_image(query: str, count: int = 1) -> list[str]:
    """Поиск реальных фото через Unsplash API."""
    try:
        from config import UNSPLASH_KEY
        async with httpx.AsyncClient(timeout=10, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": max(1, count), "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
            )
            if r.status_code != 200:
                log.error(f"unsplash {r.status_code}: {r.text[:200]}")
                return []
            results = r.json().get("results", [])
            return [it["urls"]["regular"] for it in results[:count] if it.get("urls")]
    except Exception as e:
        log.error(f"image search error: {e}")
        return []


async def download_bytes(url: str) -> bytes | None:
    """Качает файл (картинку) по URL."""
    try:
        async with httpx.AsyncClient(timeout=12, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content:
                return r.content
    except Exception as e:
        log.error(f"download error: {e}")
    return None


# ── Поиск через Parallel Search MCP ─────────────────────────────────────
# Источник фактов «Сакура сама ищет в интернете» — Parallel Search MCP
# (modules/parallel_search.py): анонимно, без ключей и карты.
# Google Search grounding НЕДОСТУПЕН на аккаунте Мастера (живая проверка
# 2026-09): gemini-2.5-flash → 404 «no longer available to new users»
# (2.x выведен для новых аккаунтов), grounding на 3.x → 429 (квоты нет
# на бесплатном тире). Выдержки Parallel — сжатые под запрос, не сырые
# страницы. Результат кэшируется 30 мин.

_SEARCH_CACHE: dict = {}   # {нормализованный_запрос: (answer, sources, ok, ts)}
_SEARCH_CACHE_TTL = 30 * 60  # 30 минут


def _normalize_query(q: str) -> str:
    q = (q or "").lower().strip()
    q = re.sub(r"\s+", " ", q)
    return q


def _clear_search_cache() -> None:
    """Сбрасывает кэш поиска (для тестов)."""
    _SEARCH_CACHE.clear()


def _clip_answer(text: str, limit: int = 2000) -> str:
    """Ограничивает текст лимитом символов, обрезая по границе предложения.

    Выдержки Parallel уже сжатые, чистить их от мусора не нужно; режем
    только на всякий случай, чтобы не отправлять в промпт простыню.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_end = None
    for m in re.finditer(r"[.!?…]+[»\"')\]]*(?=\s|$)", cut):
        last_end = m.end()
    if last_end and last_end > limit // 2:
        return cut[:last_end].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;: ") + "…"


def _dedup_domains(urls: list[str], limit: int = 5) -> list[str]:
    """Уникальные URL с дедупом по домену (первый URL каждого домена).

    Максимум limit — в Telegram идёт список 2-5 ссылок, в голосе источники
    не зачитываются.
    """
    seen_domains: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if not u:
            continue
        try:
            domain = (urlparse(u).netloc or u).lower().removeprefix("www.")
        except Exception:
            domain = u
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        uniq.append(u)
        if len(uniq) >= limit:
            break
    return uniq


def format_sources(urls: list[str], limit: int = 3) -> str:
    """Список источников для Telegram: декод, укорачивание, максимум limit.

    URL декодируется (исключает %D1%80...-простыни), ссылки длиннее 80
    символов показываются как «домен…». Возвращает "" или
    "\\n\\nИсточники:\\n• url…".
    """
    lines: list[str] = []
    for u in (urls or [])[:limit]:
        if not u:
            continue
        try:
            from urllib.parse import unquote
            shown = unquote(u)
        except Exception:
            shown = u
        if len(shown) > 80:
            try:
                shown = (urlparse(shown).netloc or shown) + "…"
            except Exception:
                shown = shown[:77] + "…"
        lines.append(f"• {shown}")
    if not lines:
        return ""
    return "\n\nИсточники:\n" + "\n".join(lines)


# Правило честности поиска: пустая/нерелевантная выдача НЕ доказывает,
# что предмета вопроса не существует (кейс: Сакура заявила «такого навыка
# нет», опираясь на статьи Лайфхакера про личностный рост).
_FACTS_PROMPT_RULES = (
    "Это ЕДИНСТВЕННЫЙ источник правды для ответа Мастеру. Ответь на его "
    "вопрос, опираясь ТОЛЬКО на эти факты, своим голосом и в своём стиле. "
    "ЗАПРЕЩЕНО: менять, округлять или выдумывать числа, имена, названия и "
    "даты; добавлять факты от себя. Если данных мало — скажи об этом прямо.\n"
    "ВАЖНО: отсутствие информации в выдаче НЕ означает, что предмета вопроса "
    "не существует. Если в источниках нет ответа — скажи, что не нашла "
    "информацию, и НЕ утверждай, что спрошенного не существует. Формулировки "
    "«такого нет», «не существует», «ты перепутал» — ЗАПРЕЩЕНЫ, если они "
    "опираются только на пустую или нерелевантную выдачу."
)


def facts_prompt(facts: str) -> str:
    """Системный блок «факты из поиска» для main.py (текст и голос).

    Один источник текста — чтобы правило честности (пустая выдача ≠
    «не существует») не разъехалось между путями.
    """
    return (
        "\n\nСВЕЖИЕ ФАКТЫ ИЗ ИНТЕРНЕТА (только что проверено поиском):\n"
        f"{facts}\n"
        + _FACTS_PROMPT_RULES
    )


async def search_grounded(query: str, queries: list[str] | None = None) -> tuple[str, list[str], bool]:
    """Интернет-поиск Сакуры через Parallel Search MCP.

    Имя сохранено ради контракта с main.py (раньше был Gemini grounding).
    Возвращает (ответ, источники, ok):
      * ответ — выдержки из поиска, сжатые под запрос (сырой текст Мастеру
        не показывается: факты формулирует MAIN_MODEL голосом Сакуры);
      * источники — список URL, дедуп по домену, до 5 штук (в Telegram
        прикрепляются, в голосе опускаются);
      * ok — True, если поиск дал результат. При сбое — ("", [], False):
        Сакура честно говорит, что не смогла найти, без фолбэков и мусора.

    Кэш результата по нормализованному запросу, TTL 30 минут: повторный
    вопрос не бьёт по rate-лимитам.
    """
    norm = _normalize_query(query)
    cached = _SEARCH_CACHE.get(norm)
    if cached:
        answer, sources, ok, ts = cached
        if time.time() - ts < _SEARCH_CACHE_TTL:
            return answer, sources, ok

    from modules.parallel_search import parallel_search
    try:
        answer, sources, ok = await (parallel_search(query, queries=queries) if queries
                                     else parallel_search(query))
    except Exception as e:
        # параноидальная защита: parallel_search ловит всё сам, но если
        # что-то улетело — честный отказ вместо падения бота
        log.warning(f"[search] parallel failed: {type(e).__name__}: {e}")
        answer, sources, ok = "", [], False
    if ok and answer:
        sources = _dedup_domains(sources, limit=5)
        answer = _clip_answer(answer, limit=4000)   # бюджет промпта ~4к симв.
    _SEARCH_CACHE[norm] = (answer, sources, ok, time.time())
    return answer, sources, ok