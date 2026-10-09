"""Действия расширения из словаря агента есть в background.js (без браузера)."""
import os
import re

from core.agent import EXT_NAMES

_EXT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extension")


def _background() -> str:
    with open(os.path.join(_EXT_DIR, "background.js"), encoding="utf-8") as f:
        return f.read()


def _handled_actions(src: str) -> set:
    return set(re.findall(r'action === "([a-z_]+)"', src))


def test_all_ext_names_handled():
    handled = _handled_actions(_background())
    missing = sorted(set(EXT_NAMES.values()) - handled)
    assert not missing, f"нет обработчика в background.js: {missing}"


def test_page_content_youtube_returns_required_keys():
    src = _background()
    start = src.index('action === "page_content_youtube"')
    block = src[start:src.index("if (action ===", start + 10)]
    for key in ("title", "channel", "description"):
        assert key in block
    assert "нет открытого видео YouTube" in block


def test_page_fill_protects_sensitive_fields():
    src = _background()
    start = src.index('action === "page_fill"')
    block = src[start:src.index("if (action ===", start + 10)]
    assert "поле защищено" in block
    assert "password" in block
