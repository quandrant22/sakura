"""feat/tg-share: «скинь в телегу …» — ответ с поиском, картинками и ссылками.

Run: python -m pytest tests/test_tg_share.py -q
"""
import asyncio
import io

import pytest
from PIL import Image

from sakura_core import tg_share


def jpeg(w, h, color=(120, 80, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


# ── разбор просьбы ─────────────────────────────────────────────────

@pytest.mark.parametrize("payload, topic", [
    ("где взять хлопок в scrap mechanic с картинками", "где взять хлопок в scrap mechanic"),
    ("как построить бота-мастера и скрин тоже", "как построить бота-мастера"),
    ("рецепт верстака без картинок", "рецепт верстака"),
])
def test_topic_of(payload, topic):
    assert tg_share.topic_of(payload) == topic


def test_flags():
    assert tg_share.wants_images("где взять хлопок")                  # по умолчанию — да
    assert not tg_share.wants_images("где взять хлопок без картинок")
    assert tg_share.wants_screen("и скрин тоже")
    assert tg_share.wants_screen("что на экране")
    assert not tg_share.wants_screen("где взять хлопок")


def test_resolve_this_uses_last_question(monkeypatch):
    import memory.memory as mem
    monkeypatch.setattr(mem, "get_history", lambda: [
        {"role": "user", "parts": ["где взять хлопок в Scrap Mechanic?"]},
        {"role": "model", "parts": ["На фермах в ящиках."]},
        {"role": "user", "parts": ["скинь это в телегу"]},
    ])
    assert tg_share.resolve_topic("это") == "где взять хлопок в Scrap Mechanic?"
    assert tg_share.resolve_topic("рецепт верстака") == "рецепт верстака"


# ── картинки ───────────────────────────────────────────────────────

@pytest.mark.parametrize("html, want", [
    ('<meta property="og:image" content="https://wiki.example/images/Cotton.png">',
     "https://wiki.example/images/Cotton.png"),
    ("<meta content='/img/cotton.jpg' property='og:image'>", "https://wiki.example/img/cotton.jpg"),
    ('<meta name="twitter:image" content="https://cdn.example/a.webp?x=1&amp;y=2">',
     "https://cdn.example/a.webp?x=1&y=2"),
    ('<meta property="og:image" content="https://wiki.example/site-logo.png">', None),
    ('<meta property="og:image" content="https://wiki.example/x.svg">', None),
    ("<html>нет картинки</html>", None),
])
def test_page_image_url(html, want):
    assert tg_share.page_image_url(html, "https://wiki.example/wiki/Cotton") == want


def test_prepare_image_filters_and_resizes():
    assert tg_share.prepare_image(jpeg(100, 100)) is None                 # мелочь
    assert tg_share.prepare_image(jpeg(1200, 200)) is None                # полоска-баннер
    assert tg_share.prepare_image(b"not an image") is None
    out = tg_share.prepare_image(jpeg(3200, 1800))
    from sakura_core.search import pages
    assert max(Image.open(io.BytesIO(out)).size) == pages.IMAGE_OUT_SIDE


# ── сбор и отправка ────────────────────────────────────────────────

class Bot:
    def __init__(self):
        self.albums, self.photos = [], []

    async def send_media_group(self, chat_id, media):
        self.albums.append(media)

    async def send_photo(self, chat_id, photo, caption=None):
        self.photos.append(photo)


COTTON = [{"url": "https://wiki.example/Cotton", "title": "Cotton", "text": "Хлопок растёт на фермах.",
           "image": "https://wiki.example/cotton.png"},
          {"url": "https://guide.example/sm", "title": "Гайд", "text": "Ещё про хлопок."}]


def run_share(monkeypatch, request, *, items=COTTON, images=(b"a", b"b"), shot=None, device="pc"):
    import sakura_core.search as search
    from sakura_core.search.pipeline import Evidence, build_facts
    sent, asked, searched, fetched = [], [], [], []

    async def fake_run(question, **kw):
        searched.append((question, kw.get("channel")))
        return Evidence(ok=bool(items), entity="Scrap Mechanic", items=list(items),
                        facts=build_facts(list(items), 5000))

    async def ask(topic, **kw):
        asked.append((topic, kw))
        return "[ТОН: весело] Хлопок собирают на фермах."

    async def send(chat, text):
        sent.append(text)

    async def imgs(known, pages_urls, limit=3):
        fetched.append((list(known), list(pages_urls)))
        return list(images)

    async def screenshot(dev):
        return shot

    async def album(bot, chat, photos, caption=""):
        bot.albums.append(list(photos))
        bot.captions.append(caption)
    monkeypatch.setattr(search, "run", fake_run)
    monkeypatch.setattr(tg_share, "images", imgs)
    monkeypatch.setattr(tg_share, "_screenshot", screenshot)
    monkeypatch.setattr(tg_share, "_send_album", album)
    bot = Bot()
    bot.captions = []
    asyncio.run(tg_share.share(request, bot=bot, master_id=1, device_id=device,
                               ask_gemini_fn=ask, send_safe_fn=send))
    bot.fetched = fetched
    return sent, asked, searched, bot


def test_share_text_sources_and_images(monkeypatch):
    sent, asked, searched, bot = run_share(monkeypatch, "где взять хлопок в scrap mechanic с картинками")
    assert searched == [("где взять хлопок в scrap mechanic", "tg")]
    assert sent[0].startswith("Хлопок собирают на фермах.")             # без тега [ТОН]
    assert "Источники:" in sent[0] and "https://wiki.example/Cotton" in sent[0]
    _topic, kw = asked[0]
    assert kw["search"] is False and "Хлопок растёт на фермах." in kw["extra_system"]
    assert "Телеграма" in kw["extra_system"]
    # картинка дочитанной страницы — первой, остальные страницы — потом
    assert bot.fetched == [(["https://wiki.example/cotton.png"], ["https://guide.example/sm"])]
    assert bot.albums == [[b"a", b"b"]] and bot.captions == ["Где взять хлопок в scrap mechanic"]


def test_share_without_images_and_with_screenshot(monkeypatch):
    _, _, _, bot = run_share(monkeypatch, "рецепт верстака без картинок и скрин тоже", shot=b"SHOT")
    assert bot.albums == [[b"SHOT"]] and bot.fetched == []


def test_share_search_failed_is_honest(monkeypatch):
    sent, asked, _, bot = run_share(monkeypatch, "где взять хлопок", items=[])
    assert "не нашла" in asked[0][1]["extra_system"]
    assert "Источники" not in sent[0] and bot.albums == []


@pytest.mark.parametrize("payload, topic", [
    ("Глянь на экран и скажи, где найти хлопок", "где найти хлопок"),
    ("посмотри на экран и подскажи как построить бота", "как построить бота"),
    ("где найти хлопок", "где найти хлопок"),
])
def test_topic_lead_stripped(payload, topic):
    assert tg_share.topic_of(payload) == topic


def test_parallel_items_parsed():
    from modules.parallel_search import _parse_items
    res = {"structuredContent": {"results": [
        {"url": "https://a", "title": "A", "excerpts": ["x", " y "]}, {"url": "https://b", "excerpts": []}]}}
    assert _parse_items(res) == [{"url": "https://a", "title": "A", "text": "x y"},
                                 {"url": "https://b", "title": "", "text": ""}]


# ── маршрут voice_to_tg ────────────────────────────────────────────

def test_voice_to_tg_question_with_pictures_goes_to_share(monkeypatch):
    from sakura_core import send
    shared, stock = [], []

    async def fake_share(request, **kw):
        shared.append((request, kw.get("device_id")))
        return True

    async def search_image(q, count=1):
        stock.append(q)
        return []
    monkeypatch.setattr(tg_share, "share", fake_share)

    async def none(*a, **k):
        return ""
    text = "скинь в телегу где взять хлопок в scrap mechanic с картинками"
    payload = send.strip_payload_words(text)
    asyncio.run(send.voice_to_tg(text, text, payload, "", none, none, search_image, none,
                                 none, lambda t: False, none, None, 1, device_id="pc"))
    assert shared == [("где взять хлопок в scrap mechanic с картинками", "pc")] and stock == []


def test_voice_to_tg_plain_picture_request_stays_stock(monkeypatch):
    from sakura_core import send
    shared, stock = [], []

    async def fake_share(request, **kw):
        shared.append(request)

    async def search_image(q, count=1):
        stock.append(q)
        return []

    async def translate(q):
        return q

    async def none(*a, **k):
        return ""
    monkeypatch.setattr(tg_share, "share", fake_share)
    text = "скинь в телегу картинку котика"
    asyncio.run(send.voice_to_tg(text, text, send.strip_payload_words(text), "", none, none, search_image,
                                 none, none, lambda t: False, translate, None, 1))
    assert stock and shared == []


# ── просьба «в телегу» с ошибками распознавания ────────────────────

@pytest.mark.parametrize("text", [
    "скинь в ттелегу, где найти?", "скинь в телегу где найти хлопок", "отправь в телеграмм рецепт",
    "пришли на телегу это", "кинь в тг ссылку", "скинь мне в личку", "перешли в телеграм",
])
def test_tg_trigger_variants(text):
    from sakura_core.send import has_tg_trigger
    assert has_tg_trigger(text.lower())


@pytest.mark.parametrize("text", [
    "где найти хлопок", "телега сломалась", "скинь громкость", "открой телеграм",
])
def test_not_tg_requests(text):
    from sakura_core.send import has_tg_trigger
    assert not has_tg_trigger(text.lower())


def test_payload_strips_garbled_target():
    from sakura_core.send import strip_payload_words
    assert strip_payload_words("скинь в ттелегу, где найти хлопок") == "где найти хлопок"


def test_tg_request_not_taken_by_game_intent():
    from sakura_core.vision import intent, seen
    seen.reset()
    seen.record("pc", "Scrap Mechanic", "лес", "ask", now=1000.0, subject="Scrap Mechanic")
    try:
        assert intent.wants_screen("где найти хлопок", None, now=1010.0)
        assert not intent.wants_screen("Скинь в Ттелегу, где найти?", None, now=1010.0)
    finally:
        seen.reset()


def test_short_topic_takes_last_question(monkeypatch):
    import memory.memory as mem
    monkeypatch.setattr(mem, "get_history", lambda: [
        {"role": "user", "parts": ["Глянь на экран и скажи, где найти хлопок."]},
        {"role": "model", "parts": ["Хлопок растёт на хлопковых цветах."]},
    ])
    assert tg_share.resolve_topic("где найти") == "Глянь на экран и скажи, где найти хлопок."
    assert tg_share.resolve_topic("где найти хлопок в scrap mechanic") == "где найти хлопок в scrap mechanic"


def test_short_topic_without_history_kept(monkeypatch):
    import memory.memory as mem
    monkeypatch.setattr(mem, "get_history", lambda: [])
    assert tg_share.resolve_topic("рецепт верстака") == "рецепт верстака"





# ── просьба в Telegram — мимо разговорного слоя ────────────────────

def test_share_request_vs_vip_message():
    from sakura_core.send import is_share_request
    assert is_share_request("Скинь в телегу, где найти хлопок.")
    assert is_share_request("пришли в ттелегу рецепт")
    assert not is_share_request("напиши Пете в телеграм что я опоздаю")
    assert not is_share_request("где найти хлопок")


def test_fear_does_not_take_tg_request():
    from conversation import fears
    assert fears.try_handle("Скинь в телегу, где найти хлопок.", {}) is None
    assert fears.try_handle("кинь хлопок в тг", {}) is None


def test_bridge_skips_router_for_share_request(monkeypatch):
    import sakura_core.bridge as bridge
    routed = []

    class Router:
        class session:
            pending = None

        async def route(self, text, context, **kw):
            routed.append(text)
    monkeypatch.setattr(bridge, "get_router", lambda: Router())
    ok = asyncio.run(bridge.v3_fast_path("Скинь в телегу, где найти хлопок.", data={}, device_ws=None,
                                         device_id="pc", register_command=None))
    assert ok is False and routed == []
