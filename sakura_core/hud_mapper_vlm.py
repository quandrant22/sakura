"""sakura_core.hud_mapper_vlm — Серверный VLM-маппинг интерфейса (Gemini 3.5 Flash-Lite) и чтение кропов (3.1 Flash-Lite)."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time

import config
from google.genai import types as T
from sakura_core.llm import generate

log = logging.getLogger("sakura.hud_mapper_vlm")

HUD_MAP_PROMPT = """You are an expert game HUD analyzer. Identify key HUD/UI elements for the game '{game_name}' ({genre}).
Return a strictly valid JSON matching the schema.
CRITICAL: Bounding boxes MUST use Gemini native format [ymin, xmin, ymax, xmax] in normalized 0..1000 coordinates.
Find visible elements:
- Health / HP bar (type: 'bar', color_hint: 'lime'/'green'/'red', orientation: 'ltr')
- Shield / Armor bar (type: 'bar', color_hint: 'blue'/'cyan')
- Stamina / Energy / Boost bar (type: 'bar', color_hint: 'yellow'/'orange')
- Speedometer / Speed (type: 'number', unit: 'km/h')
- Gear / RPM (type: 'number' or 'text')
- Ammo / Magazine counter (type: 'number')
- Hotbar / Item slots count (type: 'number')
- Compass / Minimap (type: 'region')
"""

CROP_READ_PROMPT = "Read the exact digits or short text in this game HUD crop. Return ONLY the number or text, nothing else."


async def handle_hud_map(websocket, data: dict, ctx: dict) -> None:
    """Обрабатывает запрос клиента на авто-разметку интерфейса через Gemini 3.5 Flash-Lite."""
    rid = data.get("request_id")
    dev = data.get("device_id") or "laptop"
    game_name = str(data.get("game_name") or "Игра")[:60]
    genre = str(data.get("genre") or "")[:40]
    img_b64 = data.get("image")

    if not img_b64 or not isinstance(img_b64, str):
        await _send_err(websocket, rid, "bad_request", "нет кадра изображения")
        return

    try:
        raw_jpeg = base64.b64decode(img_b64, validate=True)
    except (binascii.Error, ValueError):
        await _send_err(websocket, rid, "bad_request", "кадр не в base64")
        return

    model_name = getattr(config, "MAIN_MODEL", "gemini-3.5-flash-lite")
    prompt = HUD_MAP_PROMPT.format(game_name=game_name, genre=genre)

    t0 = time.monotonic()
    try:
        resp_text = await generate(
            [
                T.Part(inline_data=T.Blob(mime_type="image/jpeg", data=raw_jpeg)),
                T.Part(text=prompt),
            ],
            model=model_name,
            response_mime_type="application/json",
            max_tokens=1000,
            safety=False,
            thinking=False,
        )

        parsed = json.loads(resp_text or "{}")
        elements = parsed.get("elements") or []

        elapsed = time.monotonic() - t0
        log.info("[hud_mapper_vlm] Размечен HUD для '%s' за %.2fc (найдено %d элементов)", game_name, elapsed, len(elements))

        reply = {
            "type": "hud_map_reply",
            "request_id": rid,
            "game_id": data.get("game_id", ""),
            "elements": elements,
            "model": model_name,
        }
        await websocket.send(json.dumps(reply, ensure_ascii=False))

    except Exception as e:
        log.error("[hud_mapper_vlm] Ошибка VLM маппинга: %s", e)
        await _send_err(websocket, rid, "vlm_error", str(e))


async def handle_hud_crop_read(websocket, data: dict, ctx: dict) -> None:
    """Чтение стилизованного кропа через Gemini 3.1 Flash-Lite."""
    rid = data.get("request_id")
    crop_b64 = data.get("crop_image")

    if not crop_b64:
        await _send_err(websocket, rid, "bad_request", "нет кропа")
        return

    try:
        raw_crop = base64.b64decode(crop_b64, validate=True)
    except Exception:
        await _send_err(websocket, rid, "bad_request", "битый base64")
        return

    # Модель для быстрого чтения мелких кропов — Gemini 3.1 Flash-Lite из config.py
    model_name = getattr(config, "FALLBACK_MODEL", "gemini-3.1-flash-lite")

    try:
        text = await generate(
            [
                T.Part(inline_data=T.Blob(mime_type="image/jpeg", data=raw_crop)),
                T.Part(text=CROP_READ_PROMPT),
            ],
            model=model_name,
            max_tokens=25,
            safety=False,
            thinking=False,
        )
        clean_text = (text or "").strip()
        await websocket.send(json.dumps({
            "type": "hud_crop_read_reply",
            "request_id": rid,
            "text": clean_text,
        }, ensure_ascii=False))

    except Exception as e:
        log.debug("[hud_mapper_vlm] Ошибка crop_read: %s", e)
        await _send_err(websocket, rid, "crop_error", str(e))


async def _send_err(ws, rid: str, code: str, msg: str):
    try:
        await ws.send(json.dumps({
            "type": "error",
            "request_id": rid,
            "code": code,
            "message": msg,
        }, ensure_ascii=False))
    except Exception:
        pass
