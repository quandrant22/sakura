"""
web_search.py — Умный веб-поиск для Сакуры.
Оптимизирован: последовательный fetch вместо параллельного,
gc.collect() после работы с BeautifulSoup.
"""

import asyncio
import gc
import logging
import os
import re
import time
import httpx
from bs4 import BeautifulSoup
from config import MAIN_MODEL, SEARCH_MODEL, get_active_key, mark_key_used

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
]


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


def needs_search(text: str) -> bool:
    """Решает, идёт ли запрос в поиск (grounding → Tavily fallback).

    Правила:
      * Приветы / команды / творческие просьбы — НЕ в поиск (по границам слов);
      * Жёсткие и мягкие триггеры — ДА (по границам слов);
      * Убрано ограничение len < 15: короткие вопросы типа
        «кто президент Франции» пошли в поиск;
      * Вопросительное слово + имя собственное — ДА
        («кто президент Франции»);
      * Маркер времени (сейчас/сегодня/последний/текущий/…) + существенное
        слово — ДА («кто сейчас президент Франции», «сколько сейчас стоит биткоин»).
    """
    if not text:
        return False
    tl = text.lower().strip()
    if not tl:
        return False
    words = tl.split()
    orig_words = text.split()

    # Приветы / команды / творческое — не ищем (по границам слов)
    if _word_in(tl, SEARCH_STOP):
        return False
    # Жёсткие триггеры — ищем
    if _word_in(tl, SEARCH_TRIGGERS_HARD):
        return True
    # Мягкие триггеры — ищем
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


async def search_and_fetch(query: str, max_chars: int = 3000) -> str:
    """Поиск: Tavily (быстро, ~200мс) → Brave Search → Gemini fallback."""
    # 1. Tavily — быстрый AI-поиск
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tavily_key:
        try:
            from tavily import AsyncTavilyClient
            tavily = AsyncTavilyClient(api_key=tavily_key)
            response = await tavily.search(query=query, max_results=3, search_depth="basic")
            results = response.get("results", [])
            if results:
                parts = [r.get("content", "") for r in results[:3] if r.get("content")]
                text = "\n\n".join(parts)
                urls = [r.get("url", "") for r in results[:3] if r.get("url")]
                if urls:
                    text += "\n\nИсточники:\n" + "\n".join(f"• {u}" for u in urls)
                if len(text) > 50:
                    log.info(f"[search] Tavily: {len(results)} результатов")
                    return text[:max_chars]
        except Exception as e:
            log.warning(f"[search] Tavily error: {e}")

    # 2. Brave Search — HTTP API (бесплатно 2000/мес)
    brave_key = os.getenv("BRAVE_API_KEY", "").strip()
    if brave_key:
        try:
            async with httpx.AsyncClient(timeout=5, headers=HEADERS) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": 3},
                    headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                )
                if r.status_code == 200:
                    data = r.json()
                    results = data.get("web", {}).get("results", [])
                    parts = []
                    urls = []
                    for res in results[:3]:
                        desc = res.get("description", "")
                        url = res.get("url", "")
                        title = res.get("title", "")
                        if desc:
                            parts.append(f"**{title}**\n{desc}")
                        if url:
                            urls.append(url)
                    text = "\n\n".join(parts)
                    if urls:
                        text += "\n\nИсточники:\n" + "\n".join(f"• {u}" for u in urls)
                    if len(text) > 50:
                        log.info(f"[search] Brave: {len(results)} результатов")
                        return text[:max_chars]
        except Exception as e:
            log.warning(f"[search] Brave error: {e}")

    # 3. Fallback — Gemini без поиска (из памяти)
    try:
        from config import get_active_key, mark_key_used
        from google import genai
        from google.genai import types

        key = get_active_key()
        if not key:
            return ""
        client = genai.Client(api_key=key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MAIN_MODEL,
            contents=[types.Content(
                role="user",
                parts=[types.Part(text=query)]
            )],
            config=types.GenerateContentConfig(
                max_output_tokens=1000,
                temperature=0.3,
            ),
        )
        mark_key_used(key)
        text = (response.text or "").strip()
        if text:
            log.info(f"[search] Gemini fallback: {len(text)} символов")
            return text[:max_chars]
    except Exception as e:
        log.warning(f"[search] Gemini fallback error: {e}")

    return ""


async def smart_search(query: str) -> str:
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


# ── Поиск через Gemini Search grounding (SEARCH_MODEL) ──────────────────
# Ответственный за «Сакура сама ищет в интернете». Grounding работает ТОЛЬКО
# на моделях 2.x (gemini-3.5-flash-lite НЕ поддерживает), поэтому поиск
# идёт на SEARCH_MODEL. Если grounding недоступен/упал/лимит перерасходован —
# fallback на Tavily «как сейчас». Результат кэшируется 30 мин.

_SEARCH_CACHE: dict = {}   # {нормализованный_запрос: (answer, sources, ok, ts)}
_SEARCH_CACHE_TTL = 30 * 60  # 30 минут


def _normalize_query(q: str) -> str:
    q = (q or "").lower().strip()
    q = re.sub(r"\s+", " ", q)
    return q


def _clear_search_cache() -> None:
    """Сбрасывает кэш поиска (для тестов)."""
    _SEARCH_CACHE.clear()


def _extract_sources(resp) -> list[str]:
    """Из grounding_metadata ответа Gemini забирает ссылки на источники."""
    out: list[str] = []
    try:
        cands = getattr(resp, "candidates", None) or []
        cand = cands[0] if cands else None
        if cand is None:
            return out
        gmd = getattr(cand, "grounding_metadata", None)
        chunks = (getattr(gmd, "grounding_chunks", None) or []) if gmd else []
        for ch in chunks:
            src = getattr(ch, "web", None)
            if src is None:
                src = getattr(ch, "retrieved_context", None)
            uri = getattr(src, "uri", None) if src else None
            if uri:
                out.append(uri)
    except Exception as e:
        log.debug(f"[search] source extraction error: {e}")
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


async def _grounding_query(query: str) -> tuple[str, list[str], bool]:
    """Один запрос к Gemini SEARCH_MODEL с включённым Google Search grounding."""
    try:
        key = get_active_key()
        if not key:
            return "", [], False
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        google_search_tool = types.Tool(google_search=types.GoogleSearch())
        cfg = types.GenerateContentConfig(
            tools=[google_search_tool],
            max_output_tokens=1500,
            temperature=0.3,
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            SEARCH_MODEL,
            [types.Content(role="user", parts=[types.Part(text=query)])],
            cfg,
        )
        mark_key_used(key)
        text = (response.text or "").strip()
        sources = _extract_sources(response)
        if text:
            log.info(f"[search] grounding: {len(sources)} источников")
            return text, sources, True
        return text, sources, False
    except Exception as e:
        # grounding недоступен/упал/лимит — фолбэк на Tavily
        log.warning(f"[search] grounding error: {e}")
        return "", [], False


async def _tavily_fallback(query: str) -> tuple[str, list[str], bool]:
    """Фолбэк на Tavily («как сейчас»), но с разбивкой ответ/источники."""
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not tavily_key:
        return "", [], False
    try:
        from tavily import AsyncTavilyClient
        tavily = AsyncTavilyClient(api_key=tavily_key)
        resp = await tavily.search(query=query, max_results=3, search_depth="basic")
        results = resp.get("results", [])
        parts = [r.get("content", "") for r in results[:3] if r.get("content")]
        urls = [r.get("url", "") for r in results[:3] if r.get("url")]
        text = "\n\n".join(parts)
        if text:
            log.info("[search] tavily fallback")
            return text, urls, True
    except Exception as e:
        log.warning(f"[search] tavily fallback error: {e}")
    return "", [], False


async def search_grounded(query: str) -> tuple[str, list[str], bool]:
    """Интернет-поиск Сакуры через Gemini grounding.

    Возвращает (ответ, источники, ok):
      * ответ — короткий фактический ответ (формат «По данным поиска: …»
        собирает вызывающая сторона);
      * источники — список URL (в Telegram прикрепляются, в голосе опущаются);
      * ok — True, если поиск дал результат (grounding или Tavily fallback).

    Кэш результата по нормализованному запросу, TTL 30 минут: повторный вопрос
    не тратит квоту.
    """
    norm = _normalize_query(query)
    cached = _SEARCH_CACHE.get(norm)
    if cached:
        answer, sources, ok, ts = cached
        if time.time() - ts < _SEARCH_CACHE_TTL:
            return answer, sources, ok

    answer, sources, ok = await _grounding_query(query)
    if not ok or not answer:
        answer, sources, ok = await _tavily_fallback(query)
    _SEARCH_CACHE[norm] = (answer, sources, ok, time.time())
    return answer, sources, ok