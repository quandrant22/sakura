"""tests/test_sources.py — Проверка вывода источников только по прямой просьбе Мастера."""

import time
import pytest
from modules.web_search import (
    wants_sources,
    is_pure_sources_request,
    needs_search,
    set_latest_sources,
    get_latest_sources,
    clear_latest_sources,
)
from sakura_core.vision.followup import plan
from sakura_core.vision import seen


def test_wants_sources_default_is_false():
    """Обычные вопросы и бытовые реплики НЕ должны содержать источники."""
    assert not wants_sources("Смена трека прошла удачно")
    assert not wants_sources("Играет Denzel Curry")
    assert not wants_sources("Поставь лайк.")
    assert not wants_sources("Где найти хлопок в Scrap Mechanic?")
    assert not wants_sources("Какая погода в Москве?")
    assert not wants_sources("Расскажи про процессор M4")


def test_wants_sources_non_informational_exclusions():
    """Бытовые источники (питания, горячие, тока) не считаются запросом ссылок."""
    assert not wants_sources("Как починить источник бесперебойного питания?")
    assert not wants_sources("источник питания сгорел")
    assert not wants_sources("Где на Камчатке горячие источники?")
    assert not wants_sources("термальные источники в Тюмени")
    assert not wants_sources("источник тока высокого напряжения")
    assert not wants_sources("источник радиации")


def test_wants_sources_explicit_requests():
    """Явные просьбы источников, ссылок и пруфов распознаются."""
    assert wants_sources("найди информацию про M4 со ссылками")
    assert wants_sources("найди информацию про M4 со ссылкой")
    assert wants_sources("где найти хлопок в Scrap Mechanic? с источниками")
    assert wants_sources("что такое квантовые вычисления, скинь ссылки")
    assert wants_sources("дай ссылки")
    assert wants_sources("прикрепи ссылки")
    assert wants_sources("дай источники")
    assert wants_sources("какие источники?")
    assert wants_sources("с пруфами")
    assert wants_sources("пруфлинки")
    assert wants_sources("откуда инфа?")
    assert wants_sources("откуда ты это узнала?")
    assert wants_sources("где ты это прочитала?")
    assert wants_sources("где это написано?")
    assert wants_sources("а источники?")
    assert wants_sources("ссылки")
    assert wants_sources("источники")


def test_is_pure_sources_request():
    """Уточняющие вопросы только об источниках (без новой темы)."""
    assert is_pure_sources_request("откуда инфа?")
    assert is_pure_sources_request("а источники?")
    assert is_pure_sources_request("скинь ссылки")
    assert is_pure_sources_request("дай источники")
    assert is_pure_sources_request("какие источники?")
    assert is_pure_sources_request("где ты это прочитала?")
    assert is_pure_sources_request("где это написано?")
    assert is_pure_sources_request("пруфы?")

    # Если есть тема вопроса — это НЕ чистый запрос источников
    assert not is_pure_sources_request("где найти хлопок со ссылками")
    assert not is_pure_sources_request("расскажи про M4 с источниками")
    assert not is_pure_sources_request("починить источник питания")


def test_needs_search_skips_pure_sources_request():
    """Вопросы «откуда инфа?» не должны запускать новый поиск в Google/Parallel."""
    assert not needs_search("откуда инфа?")
    assert not needs_search("а источники?")
    assert not needs_search("скинь ссылки")
    assert not needs_search("какие источники?")


def test_latest_sources_cache():
    """Кэш последних источников сохраняет и возвращает ссылки в пределах TTL."""
    clear_latest_sources()
    assert get_latest_sources() == []

    urls = ["https://wiki.example/a", "https://news.example/b"]
    set_latest_sources(urls)
    assert get_latest_sources() == urls

    clear_latest_sources()
    assert get_latest_sources() == []


def test_followup_plan_ignores_synthetic_prompts():
    """Служебные промпты (музыка, статус, команды) не ищутся как продолжение экрана."""
    seen.record("laptop", "The Crew Motorfest", "гонки", "ask", now=time.monotonic(),
                subject="The Crew Motorfest")

    q, ctx = plan("Скажи Мастеру ОБЯЗАТЕЛЬНО: 1. Сначала назови исполнителя и трек...")
    assert q is None

    q, ctx = plan("Результат: готово. Скажи коротко.")
    assert q is None

    q, ctx = plan("Мастер очистил историю диалога. Отреагируй коротко.")
    assert q is None

    q, ctx = plan("Приложение 'chrome' не найдено на laptop.")
    assert q is None

    # Настоящая реплика Мастера по игре — ищется
    q, ctx = plan("Где найти редкие детали?")
    assert q is not None and "The Crew Motorfest" in q


def test_ask_gemini_omits_sources_unless_requested(monkeypatch):
    """По умолчанию источники в ответе НЕ появляются."""
    import asyncio
    from sakura_core import llm
    from sakura_core.search.pipeline import Evidence

    clear_latest_sources()

    async def fake_build(query="", channel=None):
        return "SYSTEM"

    async def fake_run(*args, **kw):
        return Evidence(ok=True, facts="Хлопок растёт на фермах.",
                        items=[{"url": "https://wiki.example/cotton"}])

    async def fake_generate(contents, system="", **kw):
        return "Хлопок можно найти на руинах ферм."

    async def fake_none(*a, **k):
        return ""

    monkeypatch.setattr(llm, "_build_system", fake_build)
    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(llm, "maybe_read_url", fake_none)
    monkeypatch.setattr(llm, "_build_contents", lambda *a, **k: [])
    monkeypatch.setattr(llm, "_web_search", fake_run)
    monkeypatch.setattr(llm, "_vision_followup", lambda *a, **k: (None, ""))
    import modules.web_search as ws
    monkeypatch.setattr(ws, "needs_search", lambda t: True)
    import config
    monkeypatch.setattr(config, "get_active_key", lambda: "key")
    monkeypatch.setattr(config, "mark_key_used", lambda k: None)

    # 1. Запрос БЕЗ просьбы источников: ответ без ссылок
    reply = asyncio.run(llm.ask_gemini("Где найти хлопок в Scrap Mechanic?", save_history=False))
    assert "Хлопок можно найти на руинах ферм." in reply
    assert "Источники:" not in reply
    assert "https://wiki.example/cotton" not in reply

    # Проверяем, что источники запомнились в кэше
    assert get_latest_sources() == ["https://wiki.example/cotton"]

    # 2. Следующий ход: пользователь спрашивает «откуда инфа?»
    reply_sources = asyncio.run(llm.ask_gemini("откуда инфа?", save_history=False))
    assert "Источники:" in reply_sources or "Вот источники:" in reply_sources
    assert "https://wiki.example/cotton" in reply_sources

    # 3. Запрос С явной просьбой источников: источники сразу в ответе
    reply_with_sources = asyncio.run(llm.ask_gemini("Где найти хлопок? со ссылками", save_history=False))
    assert "Хлопок можно найти на руинах ферм." in reply_with_sources
    assert "Источники:" in reply_with_sources
    assert "https://wiki.example/cotton" in reply_with_sources
