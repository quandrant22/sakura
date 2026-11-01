"""tg_share — «скинь в телегу …»: подробный ответ с картинками и ссылками.

Голос отвечает сразу («Отправляю в Телеграм»), а сбор идёт фоном:
  1. тема: сама фраза или — для «скинь это» — последний вопрос разговора;
  2. поиск (Parallel) — с темой экрана, если Мастер недавно спрашивал про экран;
  3. текст — ask_gemini с фактами из поиска, оформленный для Telegram;
  4. картинки — главные изображения (og:image) страниц-источников: у вики игр
     это картинка предмета; логотипы, иконки и мелочь отсеиваются;
  5. скриншот экрана — только если Мастер попросил («и скрин»);
  6. в Telegram: текст + источники, затем альбом картинок.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from urllib.parse import urljoin, urlparse

log = logging.getLogger("sakura.tg_share")

MAX_IMAGES = 3
PAGE_MAX_BYTES = 1_500_000
IMAGE_MAX_BYTES = 8_000_000
IMAGE_MIN_SIDE = 200
IMAGE_MAX_ASPECT = 3.0
IMAGE_OUT_SIDE = 1600
FETCH_TIMEOUT_S = 8.0
SEARCH_TIMEOUT_S = 20.0

_NO_IMAGES = re.compile(r"(?<!\w)без\s+(?:картин\w*|фото\w*|изображени\w*)", re.IGNORECASE)
_WANT_SCREEN = re.compile(r"(?<!\w)(скрин\w*|скриншот\w*|снимок\s+экрана|с\s+экрана|что\s+на\s+экране)(?!\w)",
                          re.IGNORECASE)
_PICS = r"(?:картин\w*|фото\w*|фотк\w*|изображени\w*|скрин\w*|скриншот\w*)"
_DECOR = re.compile(rf"\b(?:и|плюс)\s+скрин\w*\s+тоже\b|\b(?:с|и|плюс|без)\s+{_PICS}\b", re.IGNORECASE)
_THIS = re.compile(r"^(?:это|этот|эту|то|то\s+что\s+ты\s+сказала|ответ|об\s+этом|про\s+это|всё\s+это|все\s+это)$",
                   re.IGNORECASE)
_BAD_IMAGE_URL = re.compile(r"(logo|favicon|sprite|icon|avatar|placeholder|blank|default|banner-ad|\.svg|\.ico)",
                            re.IGNORECASE)
_META_IMAGE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*[\"'](?:og:image(?::url)?|twitter:image(?::src)?)[\"'][^>]*>",
    re.IGNORECASE)
_CONTENT = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)

TG_FORMAT = (
    "\n\nЭто ответ для Телеграма, не для голоса: напиши подробно и по делу — "
    "5–12 предложений или нумерованный список шагов, с точными названиями предметов, "
    "мест и чисел из фактов. Без заголовков с #, без приветствия, без тегов [ТОН]. "
    "В конце ничего не перечисляй про источники — их добавят отдельно."
)


# ── запрос ─────────────────────────────────────────────────────────

_LEAD = re.compile(
    r"^(?:(?:глянь|посмотри|взгляни)(?:\s+на\s+(?:мой\s+)?экран)?\s*(?:,|и)?\s*)?"
    r"(?:(?:скажи|подскажи|расскажи|напиши|найди)\s*,?\s*)?",
    re.IGNORECASE)


def topic_of(payload: str) -> str:
    """Тема без «с картинками», «и скрин», «глянь на экран и скажи» и т.п."""
    t = _DECOR.sub(" ", payload or "")
    t = " ".join(t.split()).strip(" ,.")
    return _LEAD.sub("", t).strip(" ,.") or t


def wants_images(text: str) -> bool:
    """Картинки — по умолчанию; «без картинок» — нет."""
    return not _NO_IMAGES.search(text or "")


def wants_screen(text: str) -> bool:
    return bool(_WANT_SCREEN.search(text or ""))


# Тема без предмета: только вопросительное слово и глагол («где найти», «как сделать»).
_VAGUE = re.compile(
    r"^(?:а\s+)?(?:где|как|что|куда|откуда|зачем|чем)(?:\s+(?:его|её|ее|их|это|мне|тут|там))?"
    r"(?:\s+(?:найти|взять|достать|купить|получить|сделать|делать|скрафтить|построить|идти|открыть))?"
    r"(?:\s+(?:его|её|ее|их|это))?\s*[?!.]*$",
    re.IGNORECASE)


def resolve_topic(topic: str) -> str:
    """«скинь это» → последний вопрос Мастера из разговора (не сама просьба);
    тема без предмета («где найти», «как сделать») — тоже из последнего вопроса."""
    if topic and not _THIS.match(topic) and not _VAGUE.match(topic):
        return topic
    try:
        from memory.memory import get_history
        from sakura_core.send import has_tg_trigger
        for m in reversed(get_history()[-10:]):
            if m.get("role") != "user":
                continue
            text = " ".join(str((m.get("parts") or [""])[0]).split())
            if text and not has_tg_trigger(text.lower()):
                return text
    except Exception as e:
        log.debug(f"[tg_share] история: {type(e).__name__}")
    return topic


def subject_now() -> str:
    """Игра/программа, о которой речь: тема экрана (vision/seen) или игра Steam."""
    try:
        from sakura_core.vision import seen
        s = seen.latest()
        if s and s.subject:
            return s.subject
    except Exception as e:
        log.debug(f"[tg_share] seen: {type(e).__name__}")
    try:
        from modules import steam_integration
        game = steam_integration._current_game
        if isinstance(game, dict) and game.get("name"):
            return str(game["name"])
    except Exception as e:
        log.debug(f"[tg_share] steam: {type(e).__name__}")
    return ""


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", (text or "").lower()).split())


def relevant(items: list[dict], subject: str) -> list[dict]:
    """Страницы про эту игру/программу: все слова названия есть в адресе,
    заголовке или выдержках. Ни одной такой — оставляем как было (не знаем,
    какие лишние). Хлопок есть и в V Rising — без отсева его гайд шёл в ответ."""
    words = [w for w in _norm(subject).split() if len(w) >= 3]
    if not words:
        return items
    keep = [it for it in items
            if all(w in _norm(" ".join((it.get("url", ""), it.get("title", ""), it.get("text", ""))))
                   for w in words)]
    return keep or items


def facts_from(items: list[dict]) -> str:
    parts = [(f"{it['title']}: " if it.get("title") else "") + it.get("text", "") for it in items if it.get("text")]
    return "\n\n".join(parts).strip()[:4000]


def search_query(topic: str) -> str:
    """С темой экрана, если Мастер недавно спрашивал про экран (vision/followup)."""
    try:
        from sakura_core.vision.followup import plan
        query, _ctx = plan(topic)
        if query:
            return query
    except Exception as e:
        log.debug(f"[tg_share] followup: {type(e).__name__}")
    return topic


# ── картинки со страниц-источников ─────────────────────────────────

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


async def _get(client, url: str, limit: int) -> bytes | None:
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
        log.debug(f"[tg_share] {urlparse(url).netloc}: {type(e).__name__}")
        return None


async def source_images(sources: list[str], limit: int = MAX_IMAGES) -> list[bytes]:
    """До limit картинок с первых страниц-источников, без повторов."""
    import httpx

    from modules.web_search import HEADERS
    out: list[bytes] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, headers=HEADERS, follow_redirects=True) as client:
        async def one(page: str) -> bytes | None:
            html = await _get(client, page, PAGE_MAX_BYTES)
            url = page_image_url(html.decode("utf-8", "ignore") if html else "", page)
            return prepare_image(await _get(client, url, IMAGE_MAX_BYTES) or b"") if url else None

        for img in await asyncio.gather(*(one(p) for p in sources[:limit + 2])):
            if not img:
                continue
            digest = hashlib.sha1(img).hexdigest()
            if digest not in seen:
                seen.add(digest)
                out.append(img)
            if len(out) >= limit:
                break
    return out


# ── сбор и отправка ────────────────────────────────────────────────

def format_sources(sources: list[str], limit: int = 3) -> str:
    links = [s for s in sources if s][:limit]
    return ("\n\nИсточники:\n" + "\n".join(f"• {u}" for u in links)) if links else ""


async def share(request: str, *, bot, master_id: int, device_id: str | None = None,
                ask_gemini_fn=None, send_safe_fn=None) -> bool:
    """Собрать и отправить ответ в Telegram. True — что-то ушло."""
    from modules.parallel_search import parallel_search
    from modules.web_search import facts_prompt
    topic = resolve_topic(topic_of(request))
    if not topic:
        await send_safe_fn(master_id, "Что прислать, Мастер?")
        return False
    topic = topic_of(topic)
    query = search_query(topic)
    items: list[dict] = []
    try:
        await asyncio.wait_for(parallel_search(query, items_out=items), SEARCH_TIMEOUT_S)
    except Exception as e:
        log.info(f"[tg_share] поиск: {type(e).__name__}")
    subject = subject_now()
    picked = relevant(items, subject)
    if len(picked) < len(items):
        log.info(f"[tg_share] отсеяно страниц не про «{subject}»: {len(items) - len(picked)}")
    facts = facts_from(picked)
    sources = [it["url"] for it in picked if it.get("url")]
    ok = bool(facts)
    extra = (facts_prompt(facts) if ok and facts else
             "\n\nПоиск ничего не дал: если ответ нужен из интернета — честно скажи, что не нашла.")
    import config
    text = await ask_gemini_fn(topic, save_history=False, chain=config.MODEL_CHAIN,
                               extra_system=extra + TG_FORMAT, search=False)
    from sakura_core.llm import _strip_tone
    text = _strip_tone(text or "").strip() or "Не получилось собрать ответ, Мастер."
    await send_safe_fn(master_id, text + format_sources(list(sources or []) if ok else []))

    photos: list[bytes] = []
    if wants_images(request) and ok and sources:
        try:
            photos = await source_images(list(sources))
        except Exception as e:
            log.info(f"[tg_share] картинки: {type(e).__name__}")
    if wants_screen(request) and device_id:
        shot = await _screenshot(device_id)
        if shot:
            photos.append(shot)
    if photos:
        caption = (topic[:1].upper() + topic[1:])[:200]
        await _send_album(bot, master_id, photos, caption=caption)
    log.info(f"[tg_share] отправлено: текст {len(text)} симв, картинок {len(photos)}, "
             f"источников {len(sources or []) if ok else 0}")
    return True


async def _screenshot(device_id: str) -> bytes | None:
    """Кадр экрана с тем же фильтром приватности, что «глянь на экран»."""
    from sakura_core.vision import capture
    try:
        frame = await capture.request(device_id, "ask")
    except capture.CaptureError as e:
        log.info(f"[tg_share] скриншот: {e.code}")
        return None
    return frame.image if isinstance(frame, capture.Frame) else None


async def _send_album(bot, master_id: int, photos: list[bytes], caption: str = "") -> None:
    from aiogram.types import BufferedInputFile, InputMediaPhoto
    files = [BufferedInputFile(p, f"sakura_{i + 1}.jpg") for i, p in enumerate(photos)]
    if len(files) == 1:
        await bot.send_photo(master_id, photo=files[0], caption=caption or None)
        return
    media = [InputMediaPhoto(media=f, caption=caption if i == 0 and caption else None)
             for i, f in enumerate(files)]
    await bot.send_media_group(master_id, media=media)
