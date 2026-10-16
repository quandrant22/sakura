"""computer_step — один шаг задачи computer.do (feat/pc-control, п.3).

Агент, получив computer.do с целью, на каждом шаге шлёт:
  {"type": "computer_step", "request_id", "goal", "history": [шаги],
   "screenshot": <JPEG base64, кадр ≤ 400 КБ>}
Сервер отвечает одним действием:
  {"type": "computer_step", "request_id",
   "action": {"type": click|type|scroll|key|done|fail,
              "target", "text", "reason"}}
Ошибка запроса — {"type": "error", "request_id", "code", "message"}.

Только master-устройства и только при COMPUTER_USE=1. Один шаг за вызов,
не больше COMPUTER_MAX_STEPS шагов на задачу (дальше — fail). Кадр
живёт только на время вызова модели: не логируется и не сохраняется; в
лог — номер шага, размер кадра и тип ответа.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re

import config

log = logging.getLogger(__name__)

ACTION_TYPES = ("click", "type", "scroll", "key", "done", "fail")
FIELD_MAX = {"target": 200, "text": 500, "reason": 200}
GOAL_MAX = 300
HISTORY_ITEM_MAX = 200

PROMPT = """Ты управляешь компьютером Мастера по одному шагу за раз. На кадре — его экран сейчас.

Цель: «{goal}»
Уже сделано (по порядку):
{history}

Выбери ОДНО следующее действие и ответь ТОЛЬКО JSON:
{{"type": "click|type|scroll|key|done|fail", "target": "...", "text": "...", "reason": "..."}}
- click: target — видимая подпись кнопки/поля/ссылки, как на экране;
- type: target — поле (или пусто — текущее), text — что ввести;
- scroll: target — down|up|left|right;
- key: text — сочетание клавиш (например ctrl+s, enter);
- done: цель достигнута; fail: цель недостижима или опасна.
Нельзя: вводить пароли и платёжные данные, подтверждать оплату, удалять
файлы, менять настройки безопасности — в таких случаях fail с причиной.
reason — по-русски, до 15 слов."""


def _fail(reason: str) -> dict:
    return {"type": "fail", "target": "", "text": "", "reason": reason}


def _history_text(history: list) -> str:
    if not history:
        return "— ничего"
    lines = []
    for i, step in enumerate(history[-config.COMPUTER_MAX_STEPS:], 1):
        if isinstance(step, dict):
            desc = " ".join(str(step.get(k) or "") for k in ("type", "target", "text", "result"))
        else:
            desc = str(step)
        lines.append(f"{i}. {desc.strip()[:HISTORY_ITEM_MAX]}")
    return "\n".join(lines)


def parse_action(raw: str) -> dict:
    """Ответ модели → действие; мусор и неизвестный тип → fail."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return _fail("модель не дала действие")
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return _fail("модель не дала действие")
    kind = str(data.get("type") or "").strip().lower()
    if kind not in ACTION_TYPES:
        return _fail(f"неизвестное действие: {kind[:20] or 'пусто'}")
    out = {"type": kind}
    for k, limit in FIELD_MAX.items():
        out[k] = str(data.get(k) or "").strip()[:limit]
    return out


async def _send(ws, obj: dict) -> None:
    try:
        await ws.send(json.dumps(obj, ensure_ascii=False))
    except Exception as e:
        log.debug(f"[computer_step] ответ не отправлен: {type(e).__name__}: {e}")


async def handle(websocket, data: dict) -> None:
    rid = data.get("request_id")
    device_id = data.get("device_id")

    async def error(code: str, message: str) -> None:
        await _send(websocket, {"type": "error", "request_id": rid,
                                "code": code, "message": message})

    async def reply(action: dict) -> None:
        await _send(websocket, {"type": "computer_step", "request_id": rid, "action": action})

    if not config.COMPUTER_USE:
        await error("unsupported", "computer_step выключен (COMPUTER_USE=0)")
        return
    from modules.ws_auth import is_master_device
    if not is_master_device(device_id):
        await error("not_master", "computer_step: только для master-устройств")
        return
    from sakura_core.proto_v2 import connection_secure
    if not connection_secure(websocket) and getattr(config, "PRIVATE_REQUIRES_SECURE", True):
        await error("secure_channel_required", "кадр экрана — только по защищённому каналу")
        return
    goal = str(data.get("goal") or "").strip()[:GOAL_MAX]
    history = data.get("history") or []
    if not goal or not isinstance(history, list):
        await error("bad_request", "нужны goal и history (список)")
        return
    step = len(history) + 1
    if step > config.COMPUTER_MAX_STEPS:
        log.info(f"[computer_step] {device_id}: шаг {step} — лимит {config.COMPUTER_MAX_STEPS}")
        await reply(_fail(f"больше {config.COMPUTER_MAX_STEPS} шагов — останавливаюсь"))
        return
    shot = data.get("screenshot")
    if not isinstance(shot, str) or not shot:
        await error("bad_request", "нет кадра")
        return
    # base64 длиннее кадра на треть: грубая отсечка до декодирования.
    if len(shot) > config.COMPUTER_MAX_SHOT_BYTES * 4 // 3 + 4:
        await error("bad_request", "кадр больше 400 КБ")
        return
    try:
        frame = base64.b64decode(shot, validate=True)
    except (binascii.Error, ValueError):
        await error("bad_request", "кадр не в base64")
        return
    shot = None
    if len(frame) > config.COMPUTER_MAX_SHOT_BYTES or frame[:3] != b"\xff\xd8\xff":
        await error("bad_request", "нужен JPEG до 400 КБ")
        return

    from google.genai import types as T
    from sakura_core.llm import generate
    try:
        raw = await generate(
            [T.Part(inline_data=T.Blob(mime_type="image/jpeg", data=frame)),
             T.Part(text=PROMPT.format(goal=goal, history=_history_text(history)))],
            chain=config.VISION_MODEL_CHAIN, max_tokens=200, temperature=0.0,
            safety=False, thinking=False, response_mime_type="application/json")
        action = parse_action(raw)
    except Exception as e:
        log.error(f"[computer_step] {device_id}: модель: {type(e).__name__}")
        action = _fail("модель недоступна")
    finally:
        frame = None            # кадр дальше не живёт
    log.info(f"[computer_step] {device_id}: шаг {step}/{config.COMPUTER_MAX_STEPS} → {action['type']}")
    await reply(action)
