"""context — о чём речь: игра или программа, которая сейчас перед Мастером.

Порядок (надёжное → догадка):
  1. игра, запущенная в Steam;
  2. заголовок активного окна, если это игра (по списку игр или потому, что это
     окно Сакура уже видела на экране) — заголовок пишет сама программа, он
     точнее, чем то, что модель «узнала» на кадре (01.11: Scrap Mechanic на
     экране, модель назвала Craftopia);
  3. тема последнего взгляда на экран (vision/seen), если свежая.
Браузер, редактор, мессенджер — не тема.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("sakura.search")

_NOT_SUBJECT = re.compile(
    r"(chrome|firefox|edge|opera|yandex|яндекс|браузер|safari|brave|vivaldi|"
    r"visual studio|vs ?code|pycharm|intellij|notepad|блокнот|word|excel|powerpoint|"
    r"telegram|discord|whatsapp|explorer|проводник|obs|sakura|сакура|диспетчер задач|"
    r"task manager|параметры|settings|^steam$)",
    re.IGNORECASE)
_VERSION = re.compile(r"\s*(?:v?\d+(?:\.\d+){1,3}[a-z]?|\(dx\d+\)|\(64-bit\)|\(x64\)|build\s*\d+)\s*", re.IGNORECASE)


def clean_title(window: str | None) -> str:
    """«Minecraft 1.21.4 - Singleplayer» → «Minecraft». Не тема — пусто."""
    title = " ".join((window or "").split())
    if not title or _NOT_SUBJECT.search(title):
        return ""
    title = re.split(r"\s+[-—|:]\s+", title)[0]
    title = _VERSION.sub(" ", title)
    title = " ".join(title.split()).strip(" -—|:")
    return title if 2 <= len(title) <= 60 and re.search(r"[A-Za-zА-Яа-яЁё]", title) else ""


def _active_window() -> str:
    try:
        from modules.window_watcher import _load
        return _load().get("current_window") or ""
    except Exception as e:
        log.debug(f"[search] окно: {type(e).__name__}")
        return ""


def _steam_game() -> str:
    try:
        from modules import steam_integration
        game = steam_integration._current_game
        if isinstance(game, dict) and game.get("name"):
            return str(game["name"])
    except Exception as e:
        log.debug(f"[search] steam: {type(e).__name__}")
    return ""


def _window_is_game(window: str) -> bool:
    try:
        from personality import is_game_active
        if is_game_active(window):
            return True
    except Exception as e:
        log.debug(f"[search] игра по окну: {type(e).__name__}")
    from sakura_core.vision import seen
    last = seen.last_any()
    if not last or not window:
        return False
    w = window.lower()
    names = [n.lower() for n in (last.title, last.subject) if n and len(n) >= 3]
    return any(n in w or w in n for n in names)


def resolve_subject(active_window: str | None = None) -> str:
    """Игра/программа, о которой, скорее всего, речь, или пусто."""
    game = _steam_game()
    if game:
        return game
    window = active_window if active_window is not None else _active_window()
    if window and _window_is_game(window):
        title = clean_title(window)
        if title:
            return title
    from sakura_core.vision import seen
    s = seen.latest()
    return s.subject if s and s.subject else ""
