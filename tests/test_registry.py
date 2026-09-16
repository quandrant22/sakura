"""Тесты реестра способностей v3 (этап 1).

Run: python -m pytest tests/test_registry.py -q

Покрывают: загрузку (67 деклараций), валидацию (негативные тесты — каждый
случай бросает RegistryError), контракт матчинга (границы слов, самый длинный
триггер, context) и каталог для LLM.
"""

import pytest

from sakura_core.registry import (
    RegistryError,
    build_index,
    build_llm_catalog,
    declaration_from_dict,
    load,
    validate,
)

BASE = {
    "id": "test.action",
    "desc": "тестовое действие",
    "executor": "vps",
    "reversible": True,
    "confirm": False,
    "triggers": ["тестовая фраза"],
}


def _decl(**over):
    raw = dict(BASE)
    raw.update(over)
    return declaration_from_dict(raw)


@pytest.fixture(scope="module")
def registry():
    return load()


@pytest.fixture(scope="module")
def index(registry):
    return build_index(registry)


# --- загрузка и валидация -------------------------------------------------


def test_load_returns_82_declarations(registry):
    assert len(registry) == 82


def test_validate_passes_on_real_registry(registry):
    validate(registry)  # не бросает


def test_duplicate_id_raises():
    with pytest.raises(RegistryError):
        validate([_decl(triggers=["фраза один"]), _decl(triggers=["фраза два"])])


def test_trigger_collision_without_context_raises():
    a = _decl(id="a.one", triggers=["общая фраза"])
    b = _decl(id="b.two", triggers=["общая фраза"])
    with pytest.raises(RegistryError):
        validate([a, b])


def test_trigger_collision_with_context_is_legal():
    a = _decl(id="a.one", triggers=["общая фраза"], context="playing:music")
    b = _decl(id="b.two", triggers=["общая фраза"], context="window:youtube")
    validate([a, b])  # не бросает: разводятся контекстом


def test_empty_triggers_raises():
    with pytest.raises(RegistryError):
        validate([_decl(triggers=[])])


def test_unknown_executor_raises():
    with pytest.raises(RegistryError):
        validate([_decl(executor="magic")])


def test_unknown_context_raises():
    with pytest.raises(RegistryError):
        validate([_decl(context="window:steam")])


# --- матчинг: границы слов, самый длинный триггер, context -----------------


def test_substring_inside_word_is_not_a_match(index):
    # 'лайк' не должен срабатывать внутри 'дизлайк'/'дизлайкни'/'мои лайки'
    assert index.match("дизлайк")[1].id == "music.dislike"  # свой триггер, не music.like
    assert index.match("дизлайкни")[1].id == "music.dislike"
    assert index.match("мои лайки")[1].id == "music.liked_tracks"  # не music.like


def test_longest_trigger_wins_dislike_vs_like(index):
    # 'нравится' ⊂ 'не нравится' ⊂ 'не нравится трек' — побеждает самый длинный
    assert index.match("не нравится трек")[1].id == "music.dislike"  # не like
    assert index.match("не нравится")[1].id == "music.dislike"
    assert index.match("нравится трек")[1].id == "music.like"


def test_longest_wins_cross_domain(index):
    # 'следующий' ⊂ 'следующий таб' — побеждает browser.tab_next, не music.next
    assert index.match("следующий таб")[1].id == "browser.tab_next"


def test_context_selects_declaration(index):
    # 'перемотай вперёд' делят music.seek_forward и youtube.forward
    assert index.match("перемотай вперёд", "playing:music")[1].id == "music.seek_forward"
    assert index.match("перемотай вперёд", "window:youtube")[1].id == "youtube.forward"
    assert index.match("перемотай вперёд") is None  # без контекста не разрешается


def test_context_free_trigger_matches_with_any_context(index):
    assert index.match("следующий трек", "playing:music")[1].id == "music.next"
    assert index.match("следующий трек", "window:youtube")[1].id == "music.next"


def test_no_match_for_unknown_phrase(index):
    assert index.match("расскажи как дела") is None


# --- каталог для LLM -------------------------------------------------------


def test_catalog_contains_all_ids(registry):
    catalog = build_llm_catalog(registry)
    for d in registry:
        assert d.id in catalog
    # каталог — строки '- id: desc'
    assert catalog.splitlines()[0].startswith("- ")
