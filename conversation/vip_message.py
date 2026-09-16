"""Написать VIP-контакту (этап 5, 3/3). Поиск контакта — локальный fuzzy
по memory/users.json (перенесён из main.py:_find_vip_by_name). В Telegram
текст сообщения Сакура сочиняет через LLM (промпт в Reply), голосом —
передаётся как есть."""

from __future__ import annotations

import difflib
import json
import re

from . import Reply

_VERBS = ("напиши", "напишите", "передай", "сообщи", "скажи")


def _find_vip(text: str):
    """Ищет VIP по имени (fuzzy). Возвращает (chat_id, name) или None."""
    try:
        with open("memory/users.json", encoding="utf-8") as fh:
            vips = json.load(fh).get("vip", {})
    except Exception:
        return None
    names = {info.get("name", "").lower(): cid
             for cid, info in vips.items() if info.get("name")}
    if not names:
        return None
    for w in text.lower().replace(",", " ").split():
        if len(w) < 3:
            continue
        m = difflib.get_close_matches(w, list(names.keys()), n=1, cutoff=0.62)
        if m:
            return names[m[0]], m[0]
    return None


def try_handle(text: str, ctx: dict) -> "Reply | None":
    words = text.lower().replace(",", " ").split()
    if not words or words[0] not in _VERBS:
        return None
    vip = _find_vip(" ".join(words[:3]))  # имя должно идти сразу после глагола
    if not vip:
        return None
    vip_id, vip_name = vip

    tl = text.lower()
    i, mlen = tl.find("чтобы"), 5
    if i == -1:
        i, mlen = tl.find("что"), 3
    if i != -1:
        msg = text[i + mlen:]
    else:
        msg = text
        for w in (*_VERBS, "сакура", vip_name):
            msg = re.sub(re.escape(w), " ", msg, flags=re.I)
    msg = " ".join(msg.split()).strip(" ,.")
    if not msg:
        return Reply(text=f"Что передать {vip_name.capitalize()}?")

    if ctx.get("surface") == "tg":
        prompt = (
            f"Напиши сообщение для {vip_name} от своего лица "
            f"(ты — Сакура, ассистент Мастера). "
            f"Мастер просит передать ему: {msg}\n"
            f"Пиши в своей манере, обращайся к нему напрямую. "
            f"Верни только текст сообщения, без пояснений."
        )
        return Reply(prompt=prompt, send_tg=(vip_id, None, vip_name))
    return Reply(text=f"Передала {vip_name.capitalize()}.",
                 send_tg=(vip_id, msg, vip_name))