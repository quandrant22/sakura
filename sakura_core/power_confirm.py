"""Подтверждение выключения, перезагрузки и сна ПК.

Один вопрос на всё, ответ принимается откуда угодно:
  вопрос  — туда, где Мастер: голос и окно того ПК, с которого пришла команда
            (если Мастер у ПК), иначе Telegram с кнопками «Да»/«Нет»;
  ответ   — «да»/«нет» голосом или текстом с любого ПК Мастера, текстом или
            кнопкой в Telegram; срок TTL_S (60 с), потом «Отменила…»;
  выбор   — название в фразе (игровой/пк, ноут, рабочий/мостех) → этот ПК;
            «все компы» → перечень онлайн-ПК; без названия → активный ПК;
            ПК офлайн → «<ПК> уже выключен», без вопроса;
  «да»    — команда уходит на ПК с "confirmed": true (клиент исполняет сразу).
Висящий вопрос про ПК сбрасывается по bye и при уходе ПК офлайн.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import config
import modules.state as st

log = logging.getLogger("sakura.power")

TTL_S = 60.0
# id действия реестра → (глагол вопроса, команда на проводе, «выключаю…»)
ACTIONS = {
    "system.shutdown": ("Выключить", "system.shutdown", "Выключаю"),
    "system.restart":  ("Перезагрузить", "system.restart", "Перезагружаю"),
    "system.sleep":    ("Усыпить", "power.sleep", "Усыпляю"),
    "power.sleep":     ("Усыпить", "power.sleep", "Усыпляю"),
}
POWER_IDS = frozenset(ACTIONS)
CANCELLED = "Отменила, ничего не выключаю"
DELIVERED = object()        # мост: вопрос уже доставлен сам, второй раз не говорить

_ALL = re.compile(r"\bвсе\s+(?:комп\w*|пк|ноут\w*|машин\w*|устройства)")
_WORK = re.compile(r"рабоч|мостех|mostech")
_LAPTOP = re.compile(r"ноут|лаптоп")
_GAMING = re.compile(r"игров|(?<!\w)пк(?!\w)|системник|десктоп|\bpc\b")


def _dm():
    from modules import device_manager
    return device_manager


def mentioned(text: str) -> str | None:
    """Какой ПК назван в фразе: 'all' | id | None."""
    t = (text or "").lower()
    if _ALL.search(t):
        return "all"
    if _WORK.search(t):
        return _dm().WORK_DEVICE_ID()
    if _LAPTOP.search(t):
        return "laptop"
    if _GAMING.search(t):
        return "pc"
    return None


def online_pcs() -> list[str]:
    from modules.presence_sync import is_bye, is_pc
    return [d for d in st.connected_devices if is_pc(d) and not is_bye(d)]


def _is_online(device_id: str) -> bool:
    return device_id in online_pcs()


def pending() -> dict | None:
    p = st._pending_power
    if p and time.monotonic() - p["ts"] > p["ttl"]:
        st._pending_power = {}
        return None
    return p or None


def on_device_gone(device_id: str) -> None:
    """bye / ПК офлайн: убрать его из висящего вопроса; пусто — вопрос снят."""
    p = st._pending_power
    if not p or device_id not in p["targets"]:
        return
    p["targets"] = [t for t in p["targets"] if t != device_id]
    if not p["targets"]:
        st._pending_power = {}
    log.info(f"[power] {device_id} ушёл — подтверждение сброшено"
             + ("" if not p["targets"] else f", осталось {p['targets']}"))


# ── куда говорить ────────────────────────────────────────────────────

async def say(text: str, source: str | None, kind: str = "ack", *, buttons: str | None = None) -> None:
    """Сказать там, где Мастер: голос и окно ПК-источника, иначе Telegram."""
    ws = st.connected_devices.get(source) if source and source != "telegram" else None
    from modules.presence_sync import pc_voice_allowed
    if ws is not None and pc_voice_allowed():
        from modules.tts_server import stream_tts_to_device
        try:
            await stream_tts_to_device(
                text, ws, source, literal=True, reply_kind=kind,
                listen=config.CONFIRM_LISTEN_SEC if kind == "confirm" else None)
            return
        except Exception as e:
            log.debug(f"[power] голос: {type(e).__name__}: {e}")
    await _telegram(text, buttons)


async def _telegram(text: str, buttons: str | None = None) -> None:
    try:
        from adapters.telegram import bot
        markup = None
        if buttons:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Да", callback_data=f"power:yes:{buttons}"),
                InlineKeyboardButton(text="Нет", callback_data=f"power:no:{buttons}")]])
        await bot.send_message(config.MASTER_ID, text, reply_markup=markup)
    except Exception as e:
        log.warning(f"[power] Telegram: {type(e).__name__}: {e}")


# ── вопрос ───────────────────────────────────────────────────────────

def _question(verb: str, targets: list[str], everyone: bool) -> str:
    dm = _dm()
    if everyone and len(targets) > 1:
        return (f"{verb} все компьютеры ({', '.join(dm.device_short(t) for t in targets)})? "
                f"Да или нет?")
    return f"{verb} {dm.device_acc(targets[0])}? Да или нет?"


def choose_targets(action_id: str, text: str, ctx_device: str | None,
                   source: str | None) -> tuple[list[str], bool, str | None]:
    """→ (цели, «все», готовый ответ без вопроса или None)."""
    dm = _dm()
    from modules.presence_sync import get_active_device
    online = online_pcs()
    named = mentioned(text)
    everyone = named == "all"
    if everyone:
        if not online:
            return [], True, "Все компьютеры уже выключены."
        return online, True, None
    if named is None:
        # «… на рабочем ноутбуке»: мост уже подменил устройство
        if source and source != "telegram" and ctx_device and ctx_device != source:
            named = ctx_device
        else:
            active = get_active_device()
            named = active if active in online else (
                source if source in online else (online[0] if len(online) == 1 else None))
    if named is None:
        return [], False, "Все компьютеры уже выключены." if not online else \
            "Какой компьютер? Назови его: игровой, ноутбук или рабочий."
    if named not in online:
        return [], False, f"{dm.device_name(named)} уже выключен."
    return [named], False, None


async def request(action_id: str, ctx, param=None):
    """Executor: вместо исполнения — вопрос. → DELIVERED или (текст, ok)."""
    verb = ACTIONS[action_id][0]
    extra = ctx.extra or {}
    text = str(extra.get("text") or "")
    source = extra.get("source") or ctx.device_id
    targets, everyone, answer = choose_targets(action_id, text, ctx.device_id, source)
    if answer:
        return (answer, True)
    pid = f"{int(time.time() * 1000) % 10**9:x}"
    st._pending_power = {"id": pid, "action": action_id, "targets": targets,
                         "ts": time.monotonic(), "ttl": TTL_S, "source": source}
    question = _question(verb, targets, everyone)
    log.info(f"[power] вопрос: {action_id} → {targets} (источник {source})")
    from modules.presence_sync import pc_voice_allowed
    at_pc = source not in (None, "telegram") and pc_voice_allowed()
    await say(question, source, "confirm", buttons=None if at_pc else pid)
    from sakura_core.tasks import spawn
    spawn(_expire(pid), name="power-confirm-ttl")
    return DELIVERED


async def _expire(pid: str) -> None:
    await asyncio.sleep(TTL_S)
    p = st._pending_power
    if p and p["id"] == pid:
        st._pending_power = {}
        log.info("[power] срок вышел — отмена")
        await say(CANCELLED + ".", p["source"], "ack")


# ── ответ ────────────────────────────────────────────────────────────

async def resolve(verdict: str, pid: str | None = None) -> str | None:
    """«confirm»/«deny» → фраза-ответ; None — вопроса нет (или кнопка старая)."""
    p = pending()
    if not p or (pid is not None and p["id"] != pid):
        return None
    st._pending_power = {}
    if verdict != "confirm":
        return "Хорошо, не буду."
    _, wire, doing = ACTIONS[p["action"]]
    dm = _dm()
    done, gone = [], []
    for dev in p["targets"]:
        ws = st.connected_devices.get(dev)
        if ws is None or not _is_online(dev):
            gone.append(dev)
            continue
        try:
            from adapters.ws import _register_command
            cmd_id = _register_command(wire, dev)
        except Exception:
            cmd_id = None
        await ws.send(json.dumps({"type": "command", "action": wire,
                                  "id": cmd_id, "confirmed": True}))
        done.append(dev)
        st._last_command_ts = time.monotonic()
        log.info(f"[power] → {dev}: {wire} confirmed")
    parts = []
    if done:
        parts.append(f"{doing} {', '.join(dm.device_acc(d) for d in done)}.")
    parts += [f"{dm.device_name(d)} уже выключен." for d in gone]
    return " ".join(parts)


async def handle_answer(text: str, source: str | None) -> bool:
    """«да»/«нет» текстом или голосом откуда угодно. True — это был ответ."""
    if pending() is None:
        return False
    from sakura_core.session import check_confirmation
    verdict = check_confirmation(text)
    if verdict is None:
        return False
    reply = await resolve(verdict)
    if reply:
        await say(reply, source, "ack")
    return True
