"""Домен «управление компьютером» (feat/pc-control): окна, питание,
процессы, буфер обмена, экран, микрофон, сеть, клавиши, файлы, UI
Automation — все executor=agent.

Источник правды — настольный клиент (ветка feat/desktop-rewrite):
desktop/docs/CONTROL.md, «Справочник новых действий», и
desktop/core/control/registry.py (ACTIONS). На провод уходит канонический
id и arg в формате клиента:
  {"type": "command", "action": "<id>", "arg": "<строка>", "id", "confirmed"}
Ответ клиента — {ok, status: done|noop|failed|unsupported, detail}.

Опасные (confirm в реестре): power.sleep, process.kill, net.wifi,
files.move, files.delete — сервер сначала спрашивает, после «да» шлёт
команду с "confirmed": true (sakura_core/executor.py). Без него клиент
отвечает «нужно подтверждение».

audio.output не объявлен: клиент его не реализует (DECISIONS №42).
"""

from __future__ import annotations

import re

from sakura_core.executor import AgentCommand, ExecutionContext, register_table

PC_ACTIONS = (
    "window.minimize", "window.maximize", "window.restore", "window.snap",
    "window.move_monitor", "window.focus", "window.list",
    "power.lock", "power.display_off", "power.sleep",
    "process.list", "process.kill",
    "clipboard.read", "clipboard.write", "clipboard.clear",
    "display.brightness", "display.night_light",
    "audio.mic_mute",
    "net.wifi", "net.bluetooth",
    "keys.type", "keys.hotkey", "keys.media",
    "files.reveal", "files.recent", "files.copy", "files.move", "files.delete",
    "ui.click", "ui.type", "ui.scroll", "ui.read",
)
# «да» на вопрос подтверждения исполняется через Executor (команда собрана
# в момент вопроса, уходит с "confirmed": true): эти действия и computer.do.
EXECUTOR_CONFIRMED = frozenset(PC_ACTIONS) | {"computer.do"}

# Действия-списки и чтения: результат (detail) пересказывается голосом.
READ_ACTIONS = frozenset({
    "window.list", "process.list", "clipboard.read", "files.recent", "ui.read",
})


def _text(ctx: ExecutionContext) -> str:
    return str((ctx.extra or {}).get("text") or "").strip()


def _param(ctx: ExecutionContext) -> str:
    return (ctx.param or "").strip()


# ── нормализация аргументов ────────────────────────────────────────

_OFF = re.compile(r"\b(выключи|отключи|выруби|off)\b", re.I)
_ON = re.compile(r"\b(включи|вруби|on)\b", re.I)


def on_off(text: str) -> str:
    """«выключи вайфай» → off, «включи» → on, иначе пусто."""
    if _OFF.search(text):
        return "off"
    if _ON.search(text):
        return "on"
    return ""


def mic_arg(text: str) -> str:
    """audio.mic_mute: on — заглушить, off — включить, пусто — переключить."""
    if re.search(r"\b(выключи|отключи|заглуши|выруби)\b", text, re.I):
        return "on"
    if re.search(r"\b(включи|верни)\b", text, re.I):
        return "off"
    return ""


_SIDES = {"влево": "left", "налево": "left", "слева": "left", "left": "left",
          "вправо": "right", "направо": "right", "справа": "right", "right": "right",
          "вверх": "top", "наверх": "top", "сверху": "top", "top": "top"}


def snap_arg(text: str) -> str:
    for word, side in _SIDES.items():
        if re.search(rf"\b{word}\b", text, re.I):
            return side
    return ""


_MONITORS = {"следующий": "next", "другой": "next", "предыдущий": "prev",
             "первый": "1", "второй": "2", "третий": "3"}


def monitor_arg(text: str) -> str:
    m = re.search(r"(\d)\s*(?:-?й\s*)?монитор", text)
    if m:
        return m.group(1)
    for word, arg in _MONITORS.items():
        if re.search(rf"\b{word}\b", text, re.I):
            return arg
    return "next"


_KEYS = {"контрол": "ctrl", "контрл": "ctrl", "ctrl": "ctrl", "шифт": "shift",
         "shift": "shift", "альт": "alt", "alt": "alt", "вин": "win", "win": "win",
         "таб": "tab", "энтер": "enter", "ввод": "enter", "эскейп": "esc",
         "эскейв": "esc", "пробел": "space", "делит": "delete",
         "це": "c", "си": "c", "ве": "v", "вэ": "v", "икс": "x", "зет": "z",
         "зэт": "z", "а": "a", "эй": "a", "эс": "s", "ти": "t", "дабл ю": "w"}


def hotkey_arg(spoken: str) -> str:
    """«контрол шифт эс» → ctrl+shift+s; f-клавиши и латиница — как есть."""
    spoken = spoken.lower().replace("+", " ").replace(" плюс ", " ")
    out = []
    for w in spoken.split():
        w = w.strip(",.")
        if not w:
            continue
        if re.fullmatch(r"f\d{1,2}|ф\d{1,2}", w):
            out.append("f" + w[1:])
        else:
            out.append(_KEYS.get(w, w))
    return "+".join(out)


_MEDIA = (("следующ", "next"), ("предыдущ", "prev"), ("пауз", "play_pause"),
          ("продолж", "play_pause"), ("без звука", "mute"), ("заглуш", "mute"),
          ("тише", "volume_down"), ("громче", "volume_up"))


def media_arg(text: str) -> str:
    t = text.lower()
    for stem, arg in _MEDIA:
        if stem in t:
            return arg
    return "play_pause"


_DIRS = {"вниз": "down", "вверх": "up", "наверх": "up", "влево": "left", "вправо": "right"}
_PAGES = {"одну": 1, "один": 1, "две": 2, "два": 2, "три": 3, "четыре": 4, "пять": 5,
          "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10}


def scroll_arg(text: str) -> str:
    t = text.lower()
    direction = next((v for k, v in _DIRS.items() if re.search(rf"\b{k}\b", t)), "down")
    m = re.search(r"на\s+(\d+|[а-я]+)\s+(?:страниц|экран)", t)
    pages = 0
    if m:
        v = m.group(1)
        pages = int(v) if v.isdigit() else _PAGES.get(v, 0)
    return f"{direction}:{min(pages, 10)}" if pages else direction


# Два файла: «X в/на Y» → «X|Y».
_SRC_DST = re.compile(r"(?:файл|документ|копию файла)\s+(.+?)\s+(?:в|на|во)\s+(.+)$", re.I)


def src_dst(text: str) -> str:
    m = _SRC_DST.search(text)
    if not m:
        return ""
    return f"{m.group(1).strip()}|{m.group(2).strip()}"


_FIELD_TEXT = re.compile(r"(?:впиши|введи)\s+в\s+(?:поле\s+)?(\S+)\s+(.+)$", re.I)


def field_text(text: str, param: str) -> str:
    """ui.type: «впиши в поиск котики» → «поиск|котики»; иначе текст в фокус."""
    m = _FIELD_TEXT.search(text)
    if m:
        return f"{m.group(1)}|{m.group(2).strip()}"
    return param


# ── хендлеры ───────────────────────────────────────────────────────

def _cmd(action: str, arg_fn=None):
    def handler(ctx: ExecutionContext) -> AgentCommand:
        arg = arg_fn(ctx) if arg_fn else _param(ctx)
        return AgentCommand(action, arg=arg or "")
    return handler


def _required(action: str, what: str, arg_fn=None):
    """Действие без значения бессмысленно — ошибка, а не голая команда
    (как files.open: в реестре required: ask, сюда пусто доезжает только с LLM)."""
    def handler(ctx: ExecutionContext) -> AgentCommand:
        arg = arg_fn(ctx) if arg_fn else _param(ctx)
        if not arg:
            raise ValueError(f"{action}: не извлечён параметр ({what})")
        return AgentCommand(action, arg=arg)
    return handler


PC_COMMANDS = {aid: _cmd(aid) for aid in PC_ACTIONS}
PC_COMMANDS.update({
    "window.snap": _required("window.snap", "сторона",
                             lambda c: snap_arg(_text(c)) or snap_arg(_param(c))),
    "window.move_monitor": _cmd("window.move_monitor", lambda c: monitor_arg(_text(c))),
    "window.focus": _required("window.focus", "окно"),
    "process.kill": _required("process.kill", "процесс"),
    "clipboard.write": _required("clipboard.write", "текст"),
    "display.brightness": _required("display.brightness", "уровень 0–100"),
    "display.night_light": _cmd("display.night_light", lambda c: on_off(_text(c))),
    "audio.mic_mute": _cmd("audio.mic_mute", lambda c: mic_arg(_text(c))),
    "net.wifi": _required("net.wifi", "on/off", lambda c: on_off(_text(c))),
    "net.bluetooth": _required("net.bluetooth", "on/off", lambda c: on_off(_text(c))),
    "keys.type": _required("keys.type", "текст"),
    "keys.hotkey": _required("keys.hotkey", "сочетание", lambda c: hotkey_arg(_param(c))),
    "keys.media": _cmd("keys.media", lambda c: media_arg(_text(c))),
    "files.reveal": _required("files.reveal", "файл"),
    "files.copy": _required("files.copy", "откуда|куда", lambda c: src_dst(_text(c))),
    "files.move": _required("files.move", "откуда|куда", lambda c: src_dst(_text(c))),
    "files.delete": _required("files.delete", "файл"),
    "ui.click": _required("ui.click", "элемент"),
    "ui.type": _required("ui.type", "текст", lambda c: field_text(_text(c), _param(c))),
    "ui.scroll": _cmd("ui.scroll", lambda c: scroll_arg(_text(c))),
})

register_table(PC_COMMANDS)
