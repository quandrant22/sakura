"""Домен «телефон» (server/phone): phone.* — executor=phone.

Команда уходит не активному ПК, а устройству из config.PHONE_DEVICES
(первое онлайн и master — на Noise-соединении, ws_auth.SECURE_ONLY_MASTERS):
{"type": "command", "id", "action", "arg"}. Результат приходит обычным
command_result ({id, ok, status: done|noop|failed|unsupported, detail}) —
«Готово» говорит modules/acks по тому же правилу, что для ПК.

Телефон офлайн: ответ «Телефон не на связи» (reply kind=error), команда не
ставится в очередь. Нет обязательного аргумента (время будильника, секунды
таймера, громкость, адрес) — вопрос вместо отправки.
"""

from __future__ import annotations

import json
import logging
import re

import config
import modules.state as st
from sakura_core.executor import ExecutionContext, register_table

log = logging.getLogger("sakura.phone")

PHONE_ACTIONS = (
    "phone.find", "phone.dnd_on", "phone.dnd_off", "phone.alarm", "phone.timer",
    "phone.flashlight", "phone.volume", "phone.clipboard", "phone.open_url",
    "phone.open_app", "phone.media_play_pause", "phone.media_next",
    "phone.media_prev", "phone.notify",
)
OFFLINE = "Телефон не на связи"
# действия, которым нужен аргумент (action_run без arg → вопрос, как у голоса)
NEEDS_ARG = {
    "phone.alarm": "На какое время поставить будильник?",
    "phone.timer": "На сколько поставить таймер?",
    "phone.volume": "Какую громкость поставить на телефоне, от 0 до 100?",
    "phone.clipboard": "Что скопировать в буфер телефона?",
    "phone.open_url": "Какую ссылку открыть на телефоне?",
    "phone.open_app": "Какое приложение открыть на телефоне?",
    "phone.notify": "Какой текст отправить в уведомлении?",
}


def _text(ctx: ExecutionContext) -> str:
    return str((ctx.extra or {}).get("text") or "").strip()


def online_phone() -> str | None:
    """Первое онлайн-устройство из PHONE_DEVICES, у которого есть master-права."""
    from modules.ws_auth import is_master_device
    for dev in config.PHONE_DEVICES:
        if dev in st.connected_devices and is_master_device(dev):
            return dev
    return None


# ── разбор аргументов из фразы ──────────────────────────────────────

_UNITS = (("час", 3600), ("мин", 60), ("сек", 1))
_NUM_WORDS = {"пять": 5, "десять": 10, "пятнадцать": 15, "двадцать": 20, "тридцать": 30,
              "сорок": 40, "пятьдесят": 50, "один": 1, "одну": 1, "две": 2, "два": 2,
              "три": 3, "четыре": 4, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9}


def alarm_arg(text: str) -> str:
    """«будильник на телефоне на 7:30» / «на 7 утра» / «в 19.05» → HH:MM или ''."""
    t = text.lower()
    m = re.search(r"(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(?:\bна|\bв)\s+(\d{1,2})(?!\d)(?:\s*час\w*)?\s*(утра|дня|вечера|ночи)?", t.split("телефон", 1)[-1])
        if not m:
            return ""
        hour, minute = int(m.group(1)), 0
    part = re.search(r"\b(утра|дня|вечера|ночи)\b", t)
    if part and 1 <= hour < 12 and part.group(1) in ("дня", "вечера"):
        hour += 12
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return ""
    return f"{hour:02d}:{minute:02d}"


def timer_arg(text: str) -> str:
    """«таймер на телефоне на 5 минут» → '300'; пусто, если срок не назван."""
    t = text.lower().split("телефон", 1)[-1]
    if re.search(r"полчаса", t):
        return "1800"
    m = re.search(r"(\d+|\w+)\s*(час\w*|мин\w*|сек\w*)", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS.get(m.group(1))
        if n:
            for stem, mult in _UNITS:
                if m.group(2).startswith(stem):
                    return str(n * mult)
    m = re.search(r"на\s+(минуту|час|секунду)", t)
    if m:
        return str({"минуту": 60, "час": 3600, "секунду": 1}[m.group(1)])
    return ""


def flashlight_arg(text: str) -> str:
    return "off" if re.search(r"(выключ|выруб|погас|отключ|убери)", text.lower()) else "on"


def volume_arg(text: str) -> str:
    t = text.lower().split("телефон", 1)[-1]
    m = re.search(r"(\d{1,3})", t)
    if m and 0 <= int(m.group(1)) <= 100:
        return str(int(m.group(1)))
    if re.search(r"максим|на полную", t):
        return "100"
    if re.search(r"ноль|без звука|минимум", t):
        return "0"
    return ""


def _after(text: str, triggers: tuple[str, ...]) -> str:
    """Остаток фразы после самого длинного совпавшего триггера."""
    low = text.lower()
    for trig in sorted(triggers, key=len, reverse=True):
        i = low.find(trig)
        if i >= 0:
            return text[i + len(trig):].strip(" ,.:;—-")
    return ""


_URL = re.compile(r"(https?://\S+|(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?)", re.IGNORECASE)


def url_arg(text: str) -> str:
    m = _URL.search(text)
    if not m:
        return ""
    url = m.group(1).rstrip(".,)")
    return url if url.lower().startswith("http") else "https://" + url


_TRIGGERS: dict[str, tuple[str, ...]] = {}


def _triggers(action: str) -> tuple[str, ...]:
    if not _TRIGGERS:
        from sakura_core import registry
        _TRIGGERS.update({d.id: d.triggers for d in registry.load() if d.id in PHONE_ACTIONS})
    return _TRIGGERS.get(action, ())


def build(action: str, text: str) -> tuple[str, str]:
    """(arg, вопрос). Если вопрос не пуст — команда не отправляется."""
    triggers = _triggers(action)
    if action == "phone.alarm":
        arg = alarm_arg(text)
        return arg, "" if arg else "На какое время поставить будильник?"
    if action == "phone.timer":
        arg = timer_arg(text)
        return arg, "" if arg else "На сколько поставить таймер?"
    if action == "phone.flashlight":
        return flashlight_arg(text), ""
    if action == "phone.volume":
        arg = volume_arg(text)
        return arg, "" if arg else "Какую громкость поставить на телефоне, от 0 до 100?"
    if action == "phone.clipboard":
        arg = _after(text, triggers)
        return arg, "" if arg else "Что скопировать в буфер телефона?"
    if action == "phone.open_url":
        arg = url_arg(text)
        return arg, "" if arg else "Какую ссылку открыть на телефоне?"
    if action == "phone.open_app":
        arg = _after(text, triggers)
        return arg, "" if arg else "Какое приложение открыть на телефоне?"
    if action == "phone.notify":
        arg = _after(text, triggers)
        return arg, "" if arg else "Какой текст отправить в уведомлении?"
    return "", ""


async def _tell(ctx: ExecutionContext, text: str, kind: str):
    """Ответ там, где Мастер (голос+reply на ПК-источнике, иначе Telegram)."""
    from sakura_core import power_confirm
    source = (ctx.extra or {}).get("source") or ctx.device_id
    await power_confirm.say(text, source, kind)
    return power_confirm.DELIVERED


def _make(action: str):
    async def run(ctx: ExecutionContext):
        dev = online_phone()
        if dev is None:
            log.info(f"[phone] {action}: телефон не на связи")
            return await _tell(ctx, OFFLINE, "error")
        explicit = (ctx.extra or {}).get("arg")
        if explicit is not None:           # action_run: аргумент уже готов
            arg, ask = explicit.strip(), ""
            if action in NEEDS_ARG and not arg:
                ask = NEEDS_ARG[action]
        else:
            arg, ask = build(action, _text(ctx))
        if ask:
            return await _tell(ctx, ask, "ack")
        ws = st.connected_devices[dev]
        cmd_id = ctx.register_command(action, dev) if ctx.register_command else None
        await ws.send(json.dumps({"type": "command", "id": cmd_id, "action": action, "arg": arg}))
        st._last_command_ts = __import__("time").monotonic()
        log.info(f"[phone] → {dev}: {action}")
        return cmd_id
    return run


register_table({aid: _make(aid) for aid in PHONE_ACTIONS})
