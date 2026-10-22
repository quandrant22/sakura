"""Работа без сервера: локальный разбор фраз для команд компьютера (громкость, музыка, программы, скриншот, окна).

Фразы — триггеры реестра (sakura_core/capabilities.yaml), только безопасные домены. Нечёткое совпадение
(difflib, порог FUZZY) — только для действий без confirm; разрушительные — лишь по точной фразе и всё
равно через окно «Разрешить?». Не команда — вопрос к модели: «нужна связь с сервером».
"""
import difflib
import os
import re

import yaml

FUZZY = 0.86
DOMAINS = ("system.volume", "music.", "open.app", "app.switch", "screenshot.run", "window.", "power.lock",
           "keys.media", "files.find")
# Короткие ответы-шаблоны (без модели); {detail} — итог действия.
REPLY_DONE = "Готово: {detail}. (офлайн-режим)"
REPLY_FAIL = "Не получилось: {detail}. (офлайн-режим)"
REPLY_NEED_SERVER = "Нужна связь с сервером, чтобы ответить на это. Команды компьютера работают и без неё."

_NUM = re.compile(r"\d{1,3}")
_OPEN = re.compile(r"^(?:открой|запусти|включи программу|открыть|запустить)\s+(.+)$")
_VOLUME = re.compile(r"(?:громкость|звук)\D{0,12}(\d{1,3})")


def _norm(text: str) -> str:
    """Нижний регистр, ё → е, без обращения «Сакура», без знаков, одиночные пробелы."""
    t = (text or "").lower().replace("ё", "е").strip()
    t = re.sub(r"^(?:сакура|sakura)[,!\s]+", "", t)
    return " ".join(re.sub(r"[^\w\s%+-]", " ", t).split())


def load_triggers(path: str | None = None) -> list[dict]:
    if path is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(root, "sakura_core", "capabilities.yaml")
    try:
        caps = yaml.safe_load(open(path, encoding="utf-8")) or []
    except OSError:
        return []
    out = []
    for c in caps:
        cid = c.get("id", "")
        if c.get("executor") != "agent" or not cid.startswith(DOMAINS):
            continue
        for t in c.get("triggers") or []:
            out.append({"id": cid, "phrase": _norm(t), "confirm": bool(c.get("confirm"))})
    return out


class OfflineIntents:
    def __init__(self, triggers: list[dict] | None = None):
        self.triggers = load_triggers() if triggers is None else triggers

    def match(self, text: str) -> tuple[str, str] | None:
        """(action, arg) или None — не команда компьютера."""
        t = _norm(text)
        if not t:
            return None
        m = _VOLUME.search(t)
        if m:
            return "system.volume", str(min(100, int(m.group(1))))
        m = _OPEN.match(t)
        if m and len(m.group(1)) <= 40:
            return "open.app", m.group(1).strip()
        best, score = None, 0.0
        for tr in self.triggers:
            if t == tr["phrase"]:
                return tr["id"], ""
            if tr["confirm"]:
                continue  # разрушительное — только точная фраза
            r = difflib.SequenceMatcher(None, t, tr["phrase"]).ratio()
            if r > score:
                best, score = tr, r
        if best is not None and score >= FUZZY:
            return best["id"], ""
        return None
