"""feat/vision: разбор ответов модели зрения и анти-повтор реплик.

Run: python -m pytest tests/test_vision_parse.py -q
"""

import pytest

from modules.repeat_guard import keys, repeats
from sakura_core.vision.parse import is_skip, parse_glance, split_ask

# ── взгляд: ВИДЕЛА / СКАЖУ ─────────────────────────────────────────

@pytest.mark.parametrize("reply, want", [
    ("ВИДЕЛА: Elden Ring, бой с боссом. СКАЖУ: Опять этот рыцарь? Ты справишься.",
     ("Elden Ring, бой с боссом.", "Опять этот рыцарь? Ты справишься.")),
    ("ВИДЕЛА: VS Code, файл main.py\nСКАЖУ: ПРОПУСК", ("VS Code, файл main.py", "")),
    ("**ВИДЕЛА:** таблица Excel **СКАЖУ:** Сколько можно считать?",
     ("таблица Excel", "Сколько можно считать?")),
    ("SAW: Minecraft night SAY: Creeper behind you!", ("Minecraft night", "Creeper behind you!")),
    ("ПРОПУСК", ("", "")),
    ("[пропуск].", ("", "")),
    ("", ("", "")),
    ("Красивый закат в игре!", ("", "Красивый закат в игре!")),       # без меток — реплика
    ("СКАЖУ: Ого, ты дошёл до финала!", ("", "Ого, ты дошёл до финала!")),
])
def test_parse_glance(reply, want):
    assert parse_glance(reply) == want


@pytest.mark.parametrize("saw", [
    "кажется, это Dota 2", "Наверное Minecraft", "не видно, что за игра",
    "размытая картинка, возможно браузер", "probably Fortnite",
])
def test_unsure_saw_means_silence(saw):
    assert parse_glance(f"ВИДЕЛА: {saw} СКАЖУ: Вперёд!") == ("", "")


def test_saw_is_capped():
    saw, _ = parse_glance("ВИДЕЛА: " + "слово " * 100 + "СКАЖУ: ок")
    assert len(saw) <= 200


@pytest.mark.parametrize("text, want", [
    ("ПРОПУСК", True), ("SKIP", True), ("(ничего)", True), ("...", True),
    ("пропуск — тут скучно", False), ("Классно!", False),
])
def test_is_skip(text, want):
    assert is_skip(text) is want


# ── разовый вопрос: ответ + ВИДЕЛА ─────────────────────────────────

def test_split_ask():
    answer, saw = split_ask("У тебя открыт браузер с почтой.\nВИДЕЛА: браузер, Gmail, список писем")
    assert answer == "У тебя открыт браузер с почтой."
    assert saw == "браузер, Gmail, список писем"


def test_split_ask_without_label():
    assert split_ask("Вижу рабочий стол.") == ("Вижу рабочий стол.", "")


def test_split_ask_uses_last_label():
    answer, saw = split_ask("Ты спросил, что я видела: игру.\nВИДЕЛА: игра Terraria")
    assert answer.startswith("Ты спросил") and saw == "игра Terraria"


# ── анти-повтор ────────────────────────────────────────────────────

def test_keys_names_numbers_latin():
    k = keys("Ого, у тебя уже 1 250 монет в Terraria, а Король Слизней ждёт!")
    assert {"1250", "terraria", "король", "слизней"} <= k


def test_keys_ignore_sentence_start_own_words_and_shouting():
    assert keys("Классно. Мастер, Сакура рада!") == set()
    assert keys("ВОТ ЭТО ДА ОГО") == set()
    assert "5" not in keys("Осталось 5 жизней")                # одна цифра — не ключ


def test_repeats_by_key():
    assert repeats("Снова Terraria? Сколько можно!", ["Terraria — моя любимая игра"])
    assert repeats("У тебя 1250 монет", ["Целых 1 250 монет!"])


def test_repeats_exact_and_similar():
    assert repeats("Ты опять сидишь в коде.", ["ты опять сидишь в коде."])
    assert repeats("Ты долго программируешь сегодня вечером",
                   ["Долго программируешь сегодня вечером, отдохни"])


def test_not_repeat():
    assert not repeats("Красивое небо в этой локации.", ["Terraria — моя любимая игра"])
    assert not repeats("что угодно", [])


# ── отчёты о правилах вырезаются ───────────────────────────────────

def test_ask_drops_rule_reports():
    reply = ("Вижу главный экран игры «Scrap Mechanic: Drilling Thunder». Персонажа с молотом вижу, "
             "а вот имён на экране нет. Больше ничего особенного здесь не заметила.\n"
             "ВИДЕЛА: Scrap Mechanic, главное меню")
    answer, saw = split_ask(reply)
    assert answer == "Вижу главный экран игры «Scrap Mechanic: Drilling Thunder»."
    assert saw == "Scrap Mechanic, главное меню"


@pytest.mark.parametrize("meta", [
    "Имени игрока не видно.", "Подписей с именами нет.", "Не буду гадать, кто это.",
    "Ничего примечательного больше не вижу.", "Пароли не пересказываю.",
    "Нет имён, только персонаж.",
])
def test_meta_sentences_dropped(meta):
    from sakura_core.vision.parse import drop_meta
    assert drop_meta(f"Открыт Steam. {meta}") == "Открыт Steam."


@pytest.mark.parametrize("keep", [
    "В списке друзей трое онлайн.", "Тут написано имя файла main.py.", "Нет, игра не на паузе.",
    "Ничего страшного, просто загрузка.",
])
def test_meaningful_sentences_kept(keep):
    from sakura_core.vision.parse import drop_meta
    assert drop_meta(keep) == keep


def test_glance_say_drops_meta():
    assert parse_glance("ВИДЕЛА: Terraria СКАЖУ: Красивый закат! Имён не видно.") == ("Terraria", "Красивый закат!")
    assert parse_glance("ВИДЕЛА: Terraria СКАЖУ: Имён нет.") == ("Terraria", "")


def test_prompts_do_not_bait_rule_reports():
    from sakura_core.vision import prompts
    assert "называй человека" not in prompts.RULES
    assert "Мастеру о них не говори" in prompts.RULES


# ── разовый вопрос: ВИДЕЛА / ФАКТЫ / ПОИСК ─────────────────────────

def test_parse_extract():
    from sakura_core.vision.parse import parse_extract
    assert parse_extract("ВИДЕЛА: Scrap Mechanic, лес\nФАКТЫ: задание «Найти паяльник»\n"
                         "ПОИСК: «Scrap Mechanic где найти паяльник»") == \
        ("Scrap Mechanic, лес", "задание «Найти паяльник»", "Scrap Mechanic где найти паяльник")
    assert parse_extract("**ВИДЕЛА:** рабочий стол\nФАКТЫ: НЕТ\nПОИСК: нет.") == ("рабочий стол", "", "")
    assert parse_extract("Просто текст без меток") == ("Просто текст без меток", "", "")
    assert parse_extract("") == ("", "", "")


def test_prompt_has_dialogue_and_forbids_greeting():
    from sakura_core.vision import prompts
    p = prompts.EXTRACT.format(dialogue="Мастер: найди паяльник", question="глянь")
    assert "найди паяльник" in p and "Без приветствий" in p
    assert "не здоровайся" in prompts.ANSWER_CONTEXT
