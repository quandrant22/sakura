"""tests/test_intimate_docs.py — база режима 18+ и фигура: команды, промпт, изоляция."""

import pytest

import modules.intimacy_mode as im
from adapters import persona_commands as pc
from sakura_core import persona


@pytest.fixture(autouse=True)
def _pdir(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONA_DIR", str(tmp_path / "persona"))
    monkeypatch.setattr(pc, "_pending", None)
    im._reset_state()
    yield
    im._reset_state()


def test_defaults_exist():
    assert "БАЗА РЕЖИМА" in persona.get("intimate_kb")
    assert ("Возраст", "25") in pc.fields("intimate_figure")


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


def test_figure_param_quick_edit_and_rollback():
    r = pc.run_doc("intimate_figure", "рост 172 см")
    assert "«Рост»: 172 см" in r.text
    assert ("Рост", "172 см") in pc.fields("intimate_figure")
    pc.run_doc("intimate_figure", "волосы: чёрные, каре")
    assert ("Волосы", "чёрные, каре") in pc.fields("intimate_figure")
    assert "предыдущая" in pc.run_doc("intimate_figure", "откат").text
    assert ("Рост", "172 см") in pc.fields("intimate_figure")
    pc.run_doc("intimate_figure", "сброс")
    assert ("Возраст", "25") in pc.fields("intimate_figure")


def test_figure_multiword_param():
    pc.run_doc("intimate_figure", "кожа и запах смуглая, пахнет ванилью")
    assert ("Кожа и запах", "смуглая, пахнет ванилью") in pc.fields("intimate_figure")


def test_unknown_param_lists_available():
    r = pc.run_doc("intimate_figure", "крылья большие")
    assert "Не нашла параметр" in r.text and "рост" in r.text


def test_add_and_remove_custom_param():
    assert "Добавила" in pc.run_doc("intimate_figure", "+ Тату: сакура на бедре").text
    assert ("Тату", "сакура на бедре") in pc.fields("intimate_figure")
    assert "Убрала" in pc.run_doc("intimate_figure", "- Тату").text
    assert "Тату" not in dict(pc.fields("intimate_figure"))


def test_kb_custom_param_goes_before_notes():
    pc.add_field("intimate_kb", "Любимый запах", "жасмин")
    pc.add_note("тест")
    text = persona.get("intimate_kb")
    assert text.index("Любимый запах") < text.index("ЗАМЕТКИ") < text.index("тест")


@pytest.mark.parametrize("bad", ["возраст 16", "возраст: 17 лет",
                                 "детали выглядит как школьница"])
def test_figure_rejects_minor(bad):
    r = pc.run_doc("intimate_figure", bad)
    assert "Не приняла" in r.text
    assert ("Возраст", "25") in pc.fields("intimate_figure")


def test_figure_file_rejects_minor():
    r = pc.run_doc("intimate_figure", "", document_text="ВНЕШНОСТЬ\n— Возраст: 15\n— Рост: 150")
    assert "Не приняла" in r.text


def test_no_args_shows_card():
    assert pc.run_doc("intimate_figure", "") is None
    text, rows = pc.card("intimate_figure")
    assert "• Рост:" in text
    datas = [d for row in rows for _, d in row]
    assert "pdoc:f:e:0" in datas and "pdoc:f:undo" in datas
    assert all(len(d.encode()) <= 64 for d in datas)


def test_button_then_value():
    flds = pc.fields("intimate_kb")
    i = next(n for n, (lbl, _) in enumerate(flds) if lbl == "Темп")
    reply, show, doc = pc.handle_callback(f"pdoc:k:e:{i}")
    assert "«Темп» сейчас" in reply.text and pc.pending_active()
    reply, doc = pc.handle_pending_input("медленно, тягуче")
    assert reply.text == "Готово." and doc == "intimate_kb"
    assert ("Темп", "медленно, тягуче") in pc.fields("intimate_kb")
    assert not pc.pending_active()
    assert pc.handle_pending_input("обычное сообщение") is None


def test_button_cancel_and_clear():
    pc.set_field("intimate_kb", "Тон", "дерзкий")
    pc.handle_callback("pdoc:k:e:" + str([l for l, _ in pc.fields("intimate_kb")].index("Тон")))
    assert pc.handle_pending_input("отмена")[0].text == "Отменила."
    assert ("Тон", "дерзкий") in pc.fields("intimate_kb")
    pc.handle_callback("pdoc:k:e:" + str([l for l, _ in pc.fields("intimate_kb")].index("Тон")))
    pc.handle_pending_input("-")
    assert ("Тон", "—") in pc.fields("intimate_kb")


def test_add_param_via_button():
    pc.handle_callback("pdoc:f:add")
    r, _ = pc.handle_pending_input("без двоеточия")
    assert "Название: значение" in r.text and pc.pending_active()
    pc.handle_pending_input("Маникюр: нежно-розовый")
    assert ("Маникюр", "нежно-розовый") in pc.fields("intimate_figure")


def test_notes_add_list_delete():
    assert "записала" in pc.run_doc("intimate_kb", "заметка любит шёпот").text
    pc.add_note("вторая")
    assert pc.notes()[0].endswith("любит шёпот") and len(pc.notes()) == 2
    text, rows = pc.notes_card()
    assert "1." in text and any(d == "pdoc:k:nd:0" for r in rows for _, d in r)
    pc.handle_callback("pdoc:k:nd:0")
    assert len(pc.notes()) == 1 and pc.notes()[0].endswith("вторая")


def test_file_upload_and_file_button():
    r = pc.run_doc("intimate_kb", "", document_text="БАЗА РЕЖИМА — О НЁМ\n\nОБЩЕЕ\n— Темп: быстрый")
    assert "обновлена целиком" in r.text
    assert pc.fields("intimate_kb") == [("Темп", "быстрый")]
    assert pc.handle_callback("pdoc:k:file")[1] == "file"


def test_stale_button():
    reply, show, _ = pc.handle_callback("pdoc:f:e:99")
    assert "устарела" in reply.text and show == "card"


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
