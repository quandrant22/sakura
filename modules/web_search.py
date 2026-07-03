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
]


def needs_search(text: str) -> bool:
    tl = text.lower().strip()
    if any(s in tl for s in SEARCH_STOP):
        return False
    if any(t in tl for t in SEARCH_TRIGGERS_HARD):
        return True
    if len(tl) < 15:
        return False
    if any(t in tl for t in SEARCH_TRIGGERS_SOFT):
        return True
    words = text.split()
    if len(words) > 3:
        capitalized = sum(1 for w in words[1:] if w and w[0].isupper())
        if capitalized >= 1 and "?" in text:
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
            model="gemini-3.1-flash-lite",
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