"""feat/search-core: единый конвейер поиска (sakura_core/search).

Сценарий 01.11: «где найти хлопок» в Scrap Mechanic — поисковик вернул гайд по
Scrap Mechanic, гайд по V Rising и статью про ткани; модель зрения назвала игру
Craftopia. Ожидаемо: тема — по окну, запросы по-русски и по-английски, судья
оставляет только Scrap Mechanic, лучшая страница дочитана.

Run: python -m pytest tests/test_search.py -q
"""
import asyncio

import pytest

from sakura_core.search import context, pages, pipeline, plan, rank
from sakura_core.vision import seen

SCRAP = {"url": "https://vgtimes.ru/guides/66679-scrap-mechanic-gde-nayti-hlopok.html",
         "title": "Гайд по ресурсам в Scrap Mechanic", "text": "Хлопок растёт возле деревьев в осеннем биоме."}
V_RISING = {"url": "https://www.playground.ru/v_rising/guide/kak_dobyt_hlopok_v_v_rising-1771611",
            "title": "Как добыть хлопок в V Rising", "text": "Хлопок в V Rising растёт в Dunley Farmlands."}
TKANI = {"url": "https://tkani.land/blog/vse-pro-tkani/hlopok", "title": "Хлопок: что это такое",
         "text": "Хлопок — натуральное волокно."}
FANDOM = {"url": "https://scrapmechanic.fandom.com/wiki/Cotton", "title": "Cotton | Scrap Mechanic Wiki",
          "text": "Cotton is harvested from Cotton Plants."}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    seen.reset()
    pipeline.reset_cache()
    from modules import steam_integration
    monkeypatch.setattr(steam_integration, "_current_game", None, raising=False)
    yield
    seen.reset()
    pipeline.reset_cache()


def run(coro):
    return asyncio.run(coro)


# ── тема ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("window, want", [
    ("Scrap Mechanic", "Scrap Mechanic"),
    ("Minecraft 1.21.4 - Singleplayer", "Minecraft"),
    ("Elden Ring (DX12)", "Elden Ring"),
    ("YouTube — Google Chrome", ""),
    ("main.py — Visual Studio Code", ""),
    ("Telegram", ""),
    ("", ""),
])
def test_clean_title(window, want):
    assert context.clean_title(window) == want


def test_subject_window_beats_model_guess():
    """Модель назвала Craftopia, окно — Scrap Mechanic, которое Сакура уже видела."""
    seen.record("pc", "Scrap Mechanic", "лес", "ask", subject="Craftopia")
    assert context.resolve_subject("Scrap Mechanic") == "Scrap Mechanic"


def test_subject_steam_first(monkeypatch):
    from modules import steam_integration
    monkeypatch.setattr(steam_integration, "_current_game", {"name": "Valheim"}, raising=False)
    assert context.resolve_subject("Terraria") == "Valheim"


def test_subject_unknown_window_not_taken():
    assert context.resolve_subject("Калькулятор") == ""          # не игра и не видела
    assert context.resolve_subject("Terraria") == "Terraria"     # игра по списку


def test_subject_falls_back_to_recent_seen():
    seen.record("pc", "YouTube — Google Chrome", "видео", "ask", subject="Scrap Mechanic")
    assert context.resolve_subject("YouTube — Google Chrome") == "Scrap Mechanic"


# ── план ───────────────────────────────────────────────────────────

def test_plan_parse():
    p = plan.parse('```json\n{"entity": "Scrap Mechanic", "queries": ["Scrap Mechanic где найти «хлопок»", '
                   '"Scrap Mechanic cotton location", "Scrap Mechanic cotton location", '
                   '"Scrap Mechanic wiki cotton", "лишний"]}\n```')
    assert p.entity == "Scrap Mechanic" and p.source == "model"
    assert p.queries == ['Scrap Mechanic где найти "хлопок"', "Scrap Mechanic cotton location",
                         "Scrap Mechanic wiki cotton"]
    assert plan.parse("не json") is None
    assert plan.parse('{"entity": "x", "queries": []}') is None


def fake_generate(monkeypatch, *answers):
    calls = []
    from sakura_core import llm

    async def gen(prompt, **kw):
        calls.append((prompt, kw))
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(llm, "generate", gen)
    return calls


def test_plan_make_fast_and_keeps_hint(monkeypatch):
    calls = fake_generate(monkeypatch, '{"entity": "Scrap Mechanic", "queries": ["a b c", "x y z"]}')
    p = run(plan.make("где найти хлопок", subject="Scrap Mechanic", hint="Scrap Mechanic хлопок", timeout=3))
    assert p.queries[0] == "Scrap Mechanic хлопок" and len(p.queries) <= 3
    assert calls[0][1]["thinking"] is False and calls[0][1]["timeout"] == 3


def test_plan_fallback_on_failure(monkeypatch):
    fake_generate(monkeypatch, TimeoutError())
    p = run(plan.make("где найти хлопок?", subject="Scrap Mechanic"))
    assert p.source == "fallback" and p.entity == "Scrap Mechanic"
    assert p.queries == ["Scrap Mechanic где найти хлопок"]


# ── отбор ──────────────────────────────────────────────────────────

def test_by_words_is_strict():
    assert rank.by_words([SCRAP, V_RISING, TKANI], "Scrap Mechanic") == [SCRAP]
    assert rank.by_words([V_RISING, TKANI], "Scrap Mechanic") == []          # чужое — не берём
    assert rank.by_words([V_RISING, TKANI], "") == [V_RISING, TKANI]


def test_judge_picks_and_orders(monkeypatch):
    fake_generate(monkeypatch, "[4, 1]")
    out = run(rank.judge([SCRAP, V_RISING, TKANI, FANDOM], "где найти хлопок", "Scrap Mechanic"))
    assert out == [FANDOM, SCRAP]


def test_judge_empty_means_nothing(monkeypatch):
    fake_generate(monkeypatch, "[]")
    assert run(rank.judge([V_RISING, TKANI], "где найти хлопок", "Scrap Mechanic")) == []


def test_judge_failure_falls_back_to_words(monkeypatch):
    fake_generate(monkeypatch, "не знаю")
    assert run(rank.judge([SCRAP, V_RISING], "где найти хлопок", "Scrap Mechanic")) == [SCRAP]


# ── страницы ───────────────────────────────────────────────────────

def test_page_text_prefers_article():
    html = ("<html><body><nav>Меню Вики Войти</nav><div class='mw-parser-output'><p>Cotton is harvested "
            "from Cotton Plants in the Meadows.</p><script>x()</script></div><footer>©</footer></body></html>")
    assert pages.page_text(html) == "Cotton is harvested from Cotton Plants in the Meadows."


# ── конвейер целиком ───────────────────────────────────────────────

def wire(monkeypatch, *, results, plan_answer, judge_answer, page=("Полный текст статьи про хлопок.", None)):
    from sakura_core import llm
    calls = {"queries": None, "read": []}

    async def gen(prompt, **kw):
        return plan_answer if "план веб-поиска" in prompt else judge_answer

    async def fetch(queries, objective, timeout=8.0):
        calls["queries"] = list(queries)
        return [dict(r) for r in results]

    async def read(url):
        calls["read"].append(url)
        return page
    monkeypatch.setattr(llm, "generate", gen)
    monkeypatch.setattr(pipeline, "_fetch", fetch)
    monkeypatch.setattr(pages, "read", read)
    return calls


def test_cotton_scenario_tg(monkeypatch):
    seen.record("pc", "Scrap Mechanic", "лес", "ask", subject="Craftopia")      # ошибка модели зрения
    calls = wire(monkeypatch, results=[SCRAP, V_RISING, TKANI, FANDOM],
                 plan_answer='{"entity": "Scrap Mechanic", "queries": ["Scrap Mechanic где найти хлопок", '
                             '"Scrap Mechanic cotton location", "Scrap Mechanic wiki cotton"]}',
                 judge_answer="[4, 1]", page=("Cotton grows in Meadows near trees.", "https://img/cotton.png"))
    ev = run(pipeline.run("где найти хлопок", channel="tg", active_window="Scrap Mechanic"))
    assert ev.ok and ev.entity == "Scrap Mechanic"
    assert calls["queries"][1] == "Scrap Mechanic cotton location"
    assert ev.sources == [FANDOM["url"], SCRAP["url"]]
    assert "V Rising" not in ev.facts and "волокно" not in ev.facts
    assert calls["read"] == [FANDOM["url"]] and "Cotton grows in Meadows" in ev.facts
    assert ev.image_urls == ["https://img/cotton.png"]


def test_voice_does_not_read_pages(monkeypatch):
    calls = wire(monkeypatch, results=[SCRAP], plan_answer='{"entity": "Scrap Mechanic", "queries": ["q"]}',
                 judge_answer="[1]")
    ev = run(pipeline.run("где найти хлопок", channel="voice", subject="Scrap Mechanic"))
    assert ev.ok and calls["read"] == [] and len(ev.facts) <= pipeline.BUDGETS["voice"].facts_max


def test_nothing_relevant_is_not_ok(monkeypatch):
    wire(monkeypatch, results=[V_RISING, TKANI], plan_answer='{"entity": "Scrap Mechanic", "queries": ["q"]}',
         judge_answer="[]")
    ev = run(pipeline.run("где найти хлопок", channel="tg", subject="Scrap Mechanic"))
    assert not ev.ok and ev.facts == "" and ev.sources == [] and ev.found == 2


def test_search_failure_never_raises(monkeypatch):
    from sakura_core import llm

    async def gen(prompt, **kw):
        raise RuntimeError("нет ключа")

    async def fetch(queries, objective, timeout=8.0):
        raise ConnectionError
    monkeypatch.setattr(llm, "generate", gen)
    monkeypatch.setattr(pipeline, "_fetch", fetch)
    ev = run(pipeline.run("кто сейчас президент Франции", channel="text", subject=""))
    assert not ev.ok and ev.queries                                   # запасной план всё равно был


def test_cache_by_question_and_entity(monkeypatch):
    calls = wire(monkeypatch, results=[SCRAP], plan_answer='{"entity": "Scrap Mechanic", "queries": ["q"]}',
                 judge_answer="[1]")
    run(pipeline.run("Где найти хлопок", channel="text", subject="Scrap Mechanic"))
    calls["queries"] = None
    ev = run(pipeline.run("где  найти хлопок", channel="text", subject="Scrap Mechanic"))
    assert ev.ok and calls["queries"] is None                         # второй раз — из кэша


def test_no_model_memory_fallback(monkeypatch):
    """search_and_fetch больше не подсовывает «ответ модели из памяти»."""
    import modules.web_search as ws
    wire(monkeypatch, results=[], plan_answer='{"entity": "", "queries": ["q"]}', judge_answer="[]")
    assert run(ws.search_and_fetch("новости 2026", max_results=2)) == ""


# ── поставщики: Parallel + SearXNG ─────────────────────────────────

def test_norm_url():
    from sakura_core.search.providers import norm_url
    assert norm_url("https://www.Example.com/a/?utm_source=x&id=2#top") == "example.com/a?id=2"
    assert norm_url("http://example.com/a") == norm_url("https://example.com/a/")


def test_merge_interleaves_and_dedupes():
    from sakura_core.search.providers import merge
    par = [{"url": "https://a.com/x", "title": "", "text": "длинная выдержка Parallel", "via": "parallel"},
           {"url": "https://b.com", "title": "B", "text": "b", "via": "parallel"}]
    sx = [{"url": "https://www.a.com/x/", "title": "A", "text": "коротко", "via": "searxng"},
          {"url": "https://c.com", "title": "C", "text": "c", "via": "searxng"}]
    out = merge(par, sx)
    assert [o["url"] for o in out] == ["https://a.com/x", "https://b.com", "https://c.com"]
    assert out[0]["title"] == "A" and out[0]["text"] == "длинная выдержка Parallel"
    assert out[0]["via"] == "parallel+searxng"


def test_parse_searxng():
    from sakura_core.search.providers import parse_searxng
    data = {"results": [
        {"url": "https://scrapmechanic.fandom.com/wiki/Cotton", "title": "Cotton | Wiki",
         "content": "Cotton is  harvested", "img_src": "https://img/c.png"},
        {"title": "без адреса"}, "мусор"]}
    assert parse_searxng(data) == [{"url": "https://scrapmechanic.fandom.com/wiki/Cotton", "title": "Cotton | Wiki",
                                    "text": "Cotton is harvested", "via": "searxng", "thumb": "https://img/c.png"}]
    assert parse_searxng({}) == []


def test_providers_enabled(monkeypatch):
    import config
    from sakura_core.search import providers
    monkeypatch.setattr(config, "SEARCH_PROVIDERS", "parallel,searxng", raising=False)
    monkeypatch.setattr(config, "SEARXNG_URL", "", raising=False)
    assert providers.enabled() == ["parallel"]                       # без адреса SearXNG выключен
    monkeypatch.setattr(config, "SEARXNG_URL", "http://127.0.0.1:8888", raising=False)
    assert providers.enabled() == ["parallel", "searxng"]
    monkeypatch.setattr(config, "SEARCH_PROVIDERS", "searxng", raising=False)
    assert providers.enabled() == ["searxng"]
    monkeypatch.setattr(config, "SEARCH_PROVIDERS", "что-то", raising=False)
    assert providers.enabled() == ["parallel"]


def test_fetch_all_survives_one_provider_down(monkeypatch):
    import config
    from sakura_core.search import providers
    monkeypatch.setattr(config, "SEARCH_PROVIDERS", "parallel,searxng", raising=False)
    monkeypatch.setattr(config, "SEARXNG_URL", "http://127.0.0.1:8888", raising=False)

    async def down(queries, objective, limit=8):
        raise ConnectionError("parallel лежит")

    async def sx(queries, base_url, timeout=8.0):
        return [dict(FANDOM, via="searxng")]
    monkeypatch.setattr(providers, "parallel", down)
    monkeypatch.setattr(providers, "searxng", sx)
    out = run(providers.fetch_all(["q"], "o", timeout=5))
    assert [o["url"] for o in out] == [FANDOM["url"]]


def test_searxng_queries_in_parallel_and_merged(monkeypatch):
    from sakura_core.search import providers
    asked = []

    class Resp:
        status_code = 200

        def __init__(self, q):
            self.q = q

        def json(self):
            return {"results": [{"url": f"https://site/{self.q}", "title": self.q, "content": "x"},
                                {"url": "https://site/common", "title": "общий", "content": "y"}]}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            asked.append((url, params["q"], params["format"]))
            return Resp(params["q"])
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    out = run(providers.searxng(["a", "b"], base_url="http://127.0.0.1:8888/"))
    assert asked == [("http://127.0.0.1:8888/search", "a", "json"), ("http://127.0.0.1:8888/search", "b", "json")]
    assert [o["url"] for o in out] == ["https://site/a", "https://site/b", "https://site/common"]
