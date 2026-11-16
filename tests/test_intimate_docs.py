"""tests/test_intimate_docs.py — база режима 18+ и фигура: команды, промпт, изоляция."""

import pytest

import modules.intimacy_mode as im
from adapters import persona_commands as pc
from sakura_core import persona


@pytest.fixture(autouse=True)
def _pdir(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONA_DIR", str(tmp_path / "persona"))
    im._reset_state()
    yield
    im._reset_state()


def test_defaults_exist():
    assert "БАЗА РЕЖИМА" in persona.get("intimate_kb")
    assert "двадцать пять" in persona.get("intimate_figure")


def test_docs_only_in_intimate_prompt():
    import personality
    intimate = personality.get_system_prompt(mode="intimate")
    master = personality.get_system_prompt(mode="master")
    guest = personality.get_system_prompt(mode="guest")
    assert "ТВОЯ ВНЕШНОСТЬ" in intimate and "БАЗА РЕЖИМА" in intimate
    # Границы — после документов: правка базы не перекрывает их.
    assert intimate.index("ГРАНИЦЫ (не меняются") > intimate.index("БАЗА РЕЖИМА")
    for p in (master, guest):
        assert "БАЗА РЕЖИМА" not in p and "ТВОЯ ВНЕШНОСТЬ" not in p


def test_figure_set_by_text_and_rollback():
    r = pc.run_doc("intimate_figure", "Высокая брюнетка с короткой стрижкой и зелёными глазами.")
    assert "обновлена" in r.text
    assert "брюнетка" in persona.get("intimate_figure")
    pc.run_doc("intimate_figure", "Миниатюрная блондинка, двадцать восемь, с каре.")
    assert "предыдущая" in pc.run_doc("intimate_figure", "откат").text
    assert "брюнетка" in persona.get("intimate_figure")
    pc.run_doc("intimate_figure", "сброс")
    assert "двадцать пять" in persona.get("intimate_figure")


@pytest.mark.parametrize("bad", ["Ей 16 лет, худенькая, рыжая и в веснушках.",
                                 "Выглядит как школьница в форме, с косичками."])
def test_figure_rejects_minor(bad):
    r = pc.run_doc("intimate_figure", bad)
    assert "Не приняла" in r.text
    assert "двадцать пять" in persona.get("intimate_figure")


def test_figure_show_sends_file():
    r = pc.run_doc("intimate_figure", "")
    assert r.file_bytes and r.file_name.endswith(".md")


def test_kb_upload_file():
    text = "БАЗА РЕЖИМА — О НЁМ\n\nЛюбит, когда ты шепчешь на ухо и не торопишься."
    r = pc.run_doc("intimate_kb", "", document_text=text)
    assert "обновлена" in r.text
    assert "шепчешь" in persona.get("intimate_kb")


def test_kb_text_arg_is_not_overwrite():
    r = pc.run_doc("intimate_kb", "что-то")
    assert "Не знаю действия" in r.text


def test_remember_note_appends_to_kb():
    assert pc.remember_note("Сакура, запомни, что я люблю, когда ты в моей рубашке")
    kb = persona.get("intimate_kb")
    assert "я люблю, когда ты в моей рубашке" in kb
    assert "ЗАМЕТКИ" in kb  # шаблон сохранён


@pytest.mark.parametrize("t", ["привет", "запомни: волна = моя волна", "ты запомнила?"])
def test_remember_note_ignores(t):
    assert not pc.remember_note(t)


def test_im_note_only_when_mode_active():
    from sakura_core import llm
    llm._im_note("tg_private", "запомни, что мне нравится медленно")
    assert "медленно" not in persona.get("intimate_kb")
    im.mark("режим 18+", "tg_private")
    llm._im_note("tg_private", "запомни, что мне нравится медленно")
    assert "медленно" in persona.get("intimate_kb")
