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
Висящий вопрос про ПК сбрасывается по bye и при уходе ПК офлайн, а также
(«Хорошо, не выключаю») любым ходом Мастера, кроме да/нет, и любым другим
вопросом Сакуры: «да» засчитывается только на последний заданный вопрос.
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
DROPPED = "Хорошо, не выключаю"
# Клиентам proto 1 (старый agent/) — прежние имена; proto 2 — канонические.
LEGACY_WIRE = {"system.shutdown": "system:shutdown", "system.restart": "system:restart",
               "power.sleep": "system:sleep", "system.sleep": "system:sleep"}
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
    """→ (цели, «все», готовый ответ без вопроса или None).
    Нет названия, нет активного ПК и онлайн больше одного → цели пусты,
    ответ — «Какой компьютер?» (see request)."""
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
            named = active if active in online else (online[0] if len(online) == 1 else None)
    if named is None:
        if not online:
            return [], False, "Все компьютеры уже выключены."
        return [], False, None
    if named not in online:
        return [], False, f"{dm.device_name(named)} уже выключен."
    return [named], False, None


def other_dialogs_pending() -> bool:
    """Есть ли другой незакрытый вопрос Сакуры (план, уточнение, подтверждение)."""
    try:
        from sakura_core.bridge import get_router
        if get_router().session.pending is not None:
            return True
    except Exception:
        pass
    if st._pending_plan or st._pending_clarify or st._pending_system:
        return True
    try:
        from modules.voice_info import pending_forget_active
        return bool(pending_forget_active())
    except Exception:
        return False


def _clear_other_dialogs() -> None:
    """Наш вопрос — последний: прежние ожидания снимаются."""
    try:
        from sakura_core.bridge import get_router
        get_router().session.cancel()
    except Exception:
        pass
    st._pending_plan.clear()
    st._pending_clarify.clear()
    st._pending_system.clear()


async def _ask(action_id: str, targets: list[str], everyone: bool, source: str | None) -> None:
    verb = ACTIONS[action_id][0]
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


async def request(action_id: str, ctx, param=None):
    """Executor: вместо исполнения — вопрос. → DELIVERED или (текст, ok)."""
    extra = ctx.extra or {}
    text = str(extra.get("text") or "")
    source = extra.get("source") or ctx.device_id
    targets, everyone, answer = choose_targets(action_id, text, ctx.device_id, source)
    if answer:
        return (answer, True)
    _clear_other_dialogs()
    if not targets:
        # какой именно? — следующая реплика с названием ПК выбирает машину
        online = online_pcs()
        pid = f"{int(time.time() * 1000) % 10**9:x}"
        st._pending_power = {"id": pid, "action": action_id, "targets": [], "stage": "which",
                             "options": online, "ts": time.monotonic(), "ttl": TTL_S,
                             "source": source}
        names = ", ".join(_dm().device_short(d) for d in online)
        await say(f"Какой компьютер: {names}?", source, "confirm")
        from sakura_core.tasks import spawn
        spawn(_expire(pid), name="power-confirm-ttl")
        return DELIVERED
    await _ask(action_id, targets, everyone, source)
    return DELIVERED


async def _expire(pid: str) -> None:
    await asyncio.sleep(TTL_S)
    p = st._pending_power
    if p and p["id"] == pid:
        st._pending_power = {}
        log.info("[power] срок вышел — отмена")
        await say(CANCELLED + ".", p["source"], "ack")


def supersede(reason: str = "другой вопрос") -> None:
    """Сакура задала другой вопрос: наш снимается («Хорошо, не выключаю»)."""
    p = st._pending_power
    if not p:
        return
    st._pending_power = {}
    log.info(f"[power] вопрос снят: {reason}")
    try:
        asyncio.get_running_loop().create_task(say(DROPPED + ".", p["source"], "ack"))
    except RuntimeError:
        pass


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
        if st.device_proto.get(dev) == 2:
            msg = {"type": "command", "action": wire, "id": cmd_id, "confirmed": True}
        else:       # proto 1 (старый agent/): прежние имена system:*
            msg = {"type": "command", "action": LEGACY_WIRE[p["action"]]}
        await ws.send(json.dumps(msg))
        done.append(dev)
        st._last_command_ts = time.monotonic()
        log.info(f"[power] → {dev}: {wire} confirmed")
    parts = []
    if done:
        parts.append(f"{doing} {', '.join(dm.device_acc(d) for d in done)}.")
    parts += [f"{dm.device_name(d)} уже выключен." for d in gone]
    return " ".join(parts)


async def handle_answer(text: str, source: str | None) -> bool:
    """Ход Мастера при висящем вопросе. True — это был ответ на вопрос.

    «да»/«нет» → ответ; на «Какой компьютер?» — название ПК → следующий вопрос;
    любой другой ход (голос, окно, Telegram) снимает вопрос («Хорошо, не
    выключаю») и обрабатывается как обычно (возвращаем False).
    Если после нашего вопроса был задан другой — «да» ему, наш снят."""
    p = pending()
    if p is None:
        return False
    if other_dialogs_pending():
        supersede("задан другой вопрос")
        return False
    if p.get("stage") == "which":
        name = mentioned(text)
        online = online_pcs()
        if name == "all" and online:
            st._pending_power = {}
            await _ask(p["action"], online, True, p["source"])
            return True
        if name in online:
            st._pending_power = {}
            await _ask(p["action"], [name], False, p["source"])
            return True
        if name is not None:
            st._pending_power = {}
            await say(f"{_dm().device_name(name)} уже выключен.", source, "ack")
            return True
    else:
        from sakura_core.session import check_confirmation
        verdict = check_confirmation(text)
        if verdict is not None:
            reply = await resolve(verdict)
            if reply:
                await say(reply, source, "ack")
            return True
    # любой другой ход
    st._pending_power = {}
    log.info(f"[power] вопрос снят: другой ход {text[:30]!r}")
    await say(DROPPED + ".", source, "ack")
    return False
