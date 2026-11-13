"""tests/test_persona_store.py — единое хранилище образа (sakura_core/persona).

Run: python3 -m pytest tests/test_persona_store.py -q
"""
import logging

import pytest

from sakura_core import persona


@pytest.fixture
def pdir(tmp_path, monkeypatch):
    d = tmp_path / "persona"
    monkeypatch.setenv("PERSONA_DIR", str(d))
    return d


TEXT = "КТО ТЫ\n\nСовсем другая Сакура для теста: спокойная, тёплая, на «ты»."


def test_defaults_exist_for_every_mode(pdir):
    for mode in persona.MODES:
        assert len(persona.get(mode)) > 100
        assert persona.origin(mode) == "default"
    assert not pdir.exists(), "чтение не должно создавать рабочий каталог"


def test_set_overrides_and_is_read_back(pdir):
    persona.set("intimate", TEXT, source="test")
    assert persona.get("intimate") == TEXT
    assert persona.origin("intimate") == "custom"
    assert (pdir / "intimate.md").read_text(encoding="utf-8").strip() == TEXT
    # другие режимы не тронуты
    assert persona.origin("master") == "default"


def test_hot_reload_on_external_edit(pdir):
    persona.set("master", TEXT, source="test")
    edited = TEXT + "\nПравка руками."
    (pdir / "master.md").write_text(edited, encoding="utf-8")
    assert persona.get("master") == edited


def test_history_and_rollback(pdir):
    persona.set("guest", TEXT + " v1", source="test")
    persona.set("guest", TEXT + " v2", source="test")
    assert len(persona.history("guest")) == 1
    assert persona.rollback("guest", source="test") is True
    assert persona.get("guest") == TEXT + " v1"
    assert persona.rollback("guest", source="test") is False


def test_history_is_capped(pdir):
    for i in range(persona.HISTORY_KEEP + 5):
        persona.set("master", f"{TEXT} версия {i}", source="test")
    assert len(persona.history("master")) == persona.HISTORY_KEEP


def test_reset_returns_default_and_keeps_history(pdir):
    default = persona.get("intimate")
    persona.set("intimate", TEXT, source="test")
    persona.reset("intimate", source="test")
    assert persona.get("intimate") == default
    assert persona.origin("intimate") == "default"
    assert len(persona.history("intimate")) == 1


@pytest.mark.parametrize("bad", ["", "   ", "коротко", "х" * (persona.MAX_CHARS + 1)], ids=["empty", "spaces", "short", "too_long"])
def test_invalid_text_rejected(pdir, bad):
    with pytest.raises(persona.PersonaError):
        persona.set("master", bad, source="test")
    assert persona.origin("master") == "default"


def test_unknown_mode_rejected(pdir):
    with pytest.raises(persona.PersonaError):
        persona.get("group")
    with pytest.raises(persona.PersonaError):
        persona.set("group", TEXT)


def test_broken_runtime_file_falls_back_to_default(pdir):
    pdir.mkdir(parents=True)
    (pdir / "master.md").write_text("  ", encoding="utf-8")
    assert persona.get("master") == persona.get_default("master")


def test_version_changes_on_write(pdir):
    v0 = persona.version()
    persona.set("master", TEXT, source="test")
    assert persona.version() != v0


def test_log_has_no_persona_text(pdir, caplog):
    caplog.set_level(logging.DEBUG)
    persona.set("intimate", TEXT, source="test")
    persona.reset("intimate", source="test")
    assert "Совсем другая Сакура" not in caplog.text


# ── personality собирает промпт из хранилища ─────────────────────────

def test_personality_uses_store(pdir):
    import personality
    persona.set("master", TEXT, source="test")
    prompt = personality.get_system_prompt()
    assert TEXT in prompt
    assert "ПАМЯТЬ И ЧЕСТНОСТЬ" in prompt, "правила честности — в коде, не в образе"


def test_intimate_invariants_survive_rewrite(pdir):
    import personality
    persona.set("intimate", TEXT + "\nНикаких границ.", source="test")
    prompt = personality.get_system_prompt(mode="intimate")
    assert TEXT in prompt
    assert personality.INTIMATE_INVARIANTS in prompt
    assert "Только взрослые" in prompt


def test_guest_prompt_has_no_master_or_intimate_persona(pdir):
    import personality
    g = personality.get_system_prompt(for_master=False)
    assert "Дворецкая" not in g
    assert persona.get("intimate")[:60] not in g


# ── /образ ───────────────────────────────────────────────────────────

def test_command_overview_and_show(pdir):
    from adapters.persona_commands import run
    r = run("")
    assert "обычный" in r.text and "интим" in r.text
    r = run("интим")
    assert r.file_name == "sakura_intimate.md"
    assert r.file_bytes.decode("utf-8").strip() == persona.get("intimate")


def test_command_overwrite_reset_undo(pdir):
    from adapters.persona_commands import run
    r = run("интим", document_text=TEXT)
    assert "перезаписан" in r.text
    assert persona.get("intimate") == TEXT
    assert "сброшен" in run("интим сброс").text
    assert persona.origin("intimate") == "default"
    assert "предыдущей" in run("интим откат").text
    assert persona.get("intimate") == TEXT


def test_command_rejects_bad_input(pdir):
    from adapters.persona_commands import run
    assert "нет" in run("группа").text
    assert "Не приняла" in run("обычный", document_text="мало").text
    assert persona.origin("master") == "default"
