"""Игра в слова (этап 5, 3/3): старт/подсказка, ответы в активной игре,
«слово дня», счёт, стоп. Логика modules/word_game не менялась."""

from __future__ import annotations

import json
import os

from modules.word_game import (
    check_answer,
    end_game,
    find_word,
    format_word_of_the_day,
    format_word_teach,
    get_random_word,
    get_score,
    is_game_active,
    is_word_game_request,
    record_score,
    start_game,
)

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    req = is_word_game_request(text)
    if req:
        if req["action"] == "start_game":
            reply = start_game() + "\n\n" + format_word_teach(get_random_word())
        else:
            reply = format_word_teach(get_random_word())
        return Reply(text=reply)

    tl = text.lower()
    if any(w in tl for w in ("слово дня", "какое слово сегодня")):
        return Reply(text=format_word_of_the_day())
    if any(w in tl for w in ("счёт слов", "сколько слов", "результат игры")):
        return Reply(text=get_score())
    if any(w in tl for w in ("хватит играть", "стоп игра",
                             "закончим игру", "выход из игры")):
        return Reply(text=end_game())

    # Игра активна — реплика Мастера считается ответом
    if is_game_active():
        session = {}
        path = "memory/word_game_session.json"
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    session = json.load(fh)
            except Exception:
                session = {}
        used = session.get("used_words", [])
        if used:
            last = find_word(used[-1])
            if last:
                correct = check_answer(text, last)
                record_score(correct)
                nxt = get_random_word()
                if correct:
                    return Reply(text=(f"Правильно! {last['jp']} — {last['ru']}. "
                                       f"{last['note']}\n\nСледующее: {nxt['jp']} "
                                       f"({nxt['romaji']}) — {nxt['ru']}"))
                return Reply(text=(f"Не совсем. Правильно: {last['jp']} — {last['ru']}. "
                                   f"{last['note']}\n\nСледующее: {nxt['jp']} "
                                   f"({nxt['romaji']}) — {nxt['ru']}"))
    return None