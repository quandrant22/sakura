"""Режим компаньона в игре: включается только явной командой (не фразой «я играю»)."""
import pytest

from sakura_core.registry import build_index, load


@pytest.fixture(scope="module")
def index():
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    return build_index(load())


@pytest.mark.parametrize("phrase, want", [
    ("режим компаньона", "game_mode.on"),
    ("сакура, включи режим компаньона", "game_mode.on"),
    ("войди в режим компаньона", "game_mode.on"),
    ("включи компаньона", "game_mode.on"),
    ("включи игровой режим", "game_mode.on"),
    ("выключи режим компаньона", "game_mode.off"),
    ("выйди из режима компаньона", "game_mode.off"),
    ("выключи компаньона", "game_mode.off"),
    ("выключи игровой режим", "game_mode.off"),
    ("я играю", None),
    ("я играю в доту", None),
])
def test_companion_phrases(index, phrase, want):
    m = index.match(phrase, None)
    assert (m[1].id if m else None) == want
