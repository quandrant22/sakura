"""pages — дочитать страницу-источник: основной текст и главная картинка.

Выдержки поисковика — пара фраз. С лучшей отобранной страницы (обычно вики)
берётся основной текст (у MediaWiki/Fandom — блок статьи, без меню) и главная
картинка (og:image — у вики это изображение предмета).
"""

from __future__ import annotations

import io
import logging
import re
from urllib.parse import urljoin, urlparse

log = logging.getLogger("sakura.search")

PAGE_MAX_BYTES = 1_500_000
IMAGE_MAX_BYTES = 8_000_000
IMAGE_MIN_SIDE = 200
IMAGE_MAX_ASPECT = 3.0
IMAGE_OUT_SIDE = 1600
FETCH_TIMEOUT_S = 8.0
TEXT_MAX = 3000

_BAD_IMAGE_URL = re.compile(r"(logo|favicon|sprite|icon|avatar|placeholder|blank|default|banner-ad|\.svg|\.ico)",
                            re.IGNORECASE)
_META_IMAGE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*[\"'](?:og:image(?::url)?|twitter:image(?::src)?)[\"'][^>]*>",
    re.IGNORECASE)
_CONTENT = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_MAIN_SELECTORS = (".mw-parser-output", "article", "main", "#content", ".post-content", ".entry-content")


def page_image_url(html: str, page_url: str) -> str | None:
    """Главная картинка страницы (og:image / twitter:image), если не логотип."""
    for tag in _META_IMAGE.findall(html or ""):
        m = _CONTENT.search(tag)
        if not m:
            continue
        url = urljoin(page_url, m.group(1).strip().replace("&amp;", "&"))
        if urlparse(url).scheme in ("http", "https") and not _BAD_IMAGE_URL.search(url):
            return url
    return None


def page_text(html: str, limit: int = TEXT_MAX) -> str:
    """Основной текст статьи без меню, скриптов и подвалов."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"]):
        tag.decompose()
    root = None
    for sel in _MAIN_SELECTORS:
        root = soup.select_one(sel)
        if root is not None:
            break
    text = (root or soup.body or soup).get_text(" ", strip=True)
    return " ".join(text.split())[:limit]


def prepare_image(data: bytes) -> bytes | None:
    """Проверить и пережать в JPEG: не мелочь, не полоска, не гигант."""
    if not data or len(data) > IMAGE_MAX_BYTES:
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    w, h = img.size
    if min(w, h) < IMAGE_MIN_SIDE or max(w, h) / max(1, min(w, h)) > IMAGE_MAX_ASPECT:
        return None
    img = img.convert("RGB")
    if max(w, h) > IMAGE_OUT_SIDE:
        scale = IMAGE_OUT_SIDE / max(w, h)
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


async def get(client, url: str, limit: int) -> bytes | None:
    """GET с потолком размера; любой сбой — None."""
    try:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                return None
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    return None
            return bytes(buf)
    except Exception as e:
        log.debug(f"[search] {urlparse(url).netloc}: {type(e).__name__}")
        return None


def client():
    import httpx

    from modules.web_search import HEADERS
    return httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, headers=HEADERS, follow_redirects=True)


async def read(url: str) -> tuple[str, str | None]:
    """(основной текст, адрес главной картинки) страницы."""
    async with client() as c:
        html = await get(c, url, PAGE_MAX_BYTES)
    if not html:
        return "", None
    decoded = html.decode("utf-8", "ignore")
    return page_text(decoded), page_image_url(decoded, url)
