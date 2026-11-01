"""tg_share — «скинь в телегу …»: подробный ответ с картинками и ссылками.

Голос отвечает сразу («Отправляю в Телеграм»), а сбор идёт фоном:
  1. тема: сама фраза или — для «скинь это» / «где найти» — последний вопрос;
  2. поиск — единый конвейер (sakura_core/search, канал tg): тема по окну игры,
     запросы по-русски и по-английски, судья отсеивает чужие игры, лучшая
     страница дочитывается;
  3. текст — ask_gemini с фактами, оформленный для Telegram;
  4. картинки — главная картинка дочитанной страницы и других отобранных
     источников (og:image); логотипы, иконки и мелочь отсеиваются;
  5. скриншот экрана — только если Мастер попросил («и скрин»);
  6. в Telegram: текст + источники, затем альбом картинок.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from sakura_core.search.pages import (  # noqa: F401  (старые имена)
    page_image_url,
    prepare_image,
)

log = logging.getLogger("sakura.tg_share")

MAX_IMAGES = 3

_NO_IMAGES = re.compile(r"(?<!\w)без\s+(?:картин\w*|фото\w*|изображени\w*)", re.IGNORECASE)
_WANT_SCREEN = re.compile(r"(?<!\w)(скрин\w*|скриншот\w*|снимок\s+экрана|с\s+экрана|что\s+на\s+экране)(?!\w)",
                          re.IGNORECASE)
_PICS = r"(?:картин\w*|фото\w*|фотк\w*|изображени\w*|скрин\w*|скриншот\w*)"
_DECOR = re.compile(rf"\b(?:и|плюс)\s+скрин\w*\s+тоже\b|\b(?:с|и|плюс|без)\s+{_PICS}\b", re.IGNORECASE)
_THIS = re.compile(r"^(?:это|этот|эту|то|то\s+что\s+ты\s+сказала|ответ|об\s+этом|про\s+это|всё\s+это|все\s+это)$",
                   re.IGNORECASE)

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


# ── картинки со страниц-источников ─────────────────────────────────

async def images(image_urls: list[str], pages_urls: list[str], limit: int = MAX_IMAGES) -> list[bytes]:
    """До limit картинок: сначала уже известные (дочитанная страница), затем
    главные картинки других отобранных страниц. Без повторов."""
    from sakura_core.search import pages
    out: list[bytes] = []
    seen: set[str] = set()
    async with pages.client() as c:
        async def from_url(url: str) -> bytes | None:
            return pages.prepare_image(await pages.get(c, url, pages.IMAGE_MAX_BYTES) or b"")

        async def from_page(page: str) -> bytes | None:
            html = await pages.get(c, page, pages.PAGE_MAX_BYTES)
            url = pages.page_image_url(html.decode("utf-8", "ignore") if html else "", page)
            return await from_url(url) if url else None

        jobs = [from_url(u) for u in image_urls] + [from_page(p) for p in pages_urls]
        for img in await asyncio.gather(*jobs[:limit + 3]):
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
    from modules.web_search import facts_prompt
    from sakura_core.search import run
    topic = resolve_topic(topic_of(request))
    if not topic:
        await send_safe_fn(master_id, "Что прислать, Мастер?")
        return False
    topic = topic_of(topic)
    ev = await run(topic, channel="tg")
    extra = (facts_prompt(ev.facts) if ev.ok else
             "\n\nПоиск ничего подходящего не дал: если ответ нужен из интернета — честно скажи, "
             "что не нашла точной информации, и не выдумывай.")
    import config
    text = await ask_gemini_fn(topic, save_history=False, chain=config.MODEL_CHAIN,
                               extra_system=extra + TG_FORMAT, search=False)
    from sakura_core.llm import _strip_tone
    text = _strip_tone(text or "").strip() or "Не получилось собрать ответ, Мастер."
    await send_safe_fn(master_id, text + format_sources(ev.sources if ev.ok else []))

    photos: list[bytes] = []
    if wants_images(request) and ev.ok:
        known = ev.image_urls
        rest = [it["url"] for it in ev.items if it.get("url") and not it.get("image")]
        try:
            photos = await images(known, rest)
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
             f"источников {len(ev.sources) if ev.ok else 0}")
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
