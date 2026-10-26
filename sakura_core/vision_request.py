"""vision_request — «Спросить про окно» настольного клиента.

Клиент по явному нажатию шлёт один кадр окна:
  {"type": "vision_request", "request_id", "image": <JPEG|PNG base64>,
   "question": "Что в этом окне?"}
Ответ — reply с тем же request_id:
  {"type": "reply", "request_id", "text", "kind": "llm", "ts"}
Ошибка — {"type": "error", "request_id", "code", "message"}.

Только master-устройства. Кадр не пишется в лог и на диск, живёт только
на время запроса; в лог — размер кадра и длина вопроса.

source: необязательное поле — "window" (по умолчанию, кадр окна) или "camera"
(кадр с камеры телефона: JPEG base64, лимит тот же). Для камеры свой промпт
(«кадр с камеры телефона Мастера») с теми же правилами краткости и приватности;
остальное — как у кадра окна, включая «кадр не логируется».
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time

import config

log = logging.getLogger(__name__)

MAX_B64 = 2_000_000            # как у клиента (WINDOW_ASK_MAX_B64)
QUESTION_MAX = 500
DEFAULT_QUESTION = "Что в этом окне?"
SOURCES = ("window", "camera")
CAMERA_QUESTION = "Что на кадре?"

PROMPT = (
    "Это кадр одного окна на компьютере Мастера, он сам попросил на него "
    "посмотреть. Вопрос Мастера: «{question}». Ответь по-русски коротко и по "
    "делу (до трёх предложений), опираясь только на то, что видно в кадре; "
    "чего не видно — так и скажи. Пароли и личные данные не пересказывай."
)
CAMERA_PROMPT = (
    "Это кадр с камеры телефона Мастера, он сам попросил на него посмотреть. "
    "Вопрос Мастера: «{question}». Ответь по-русски коротко и по делу (до трёх "
    "предложений), опираясь только на то, что видно в кадре; чего не видно или "
    "не разобрать — так и скажи. Людей не опознавай и не называй по имени, лиц "
    "не описывай подробно; тексты документов, номера карт и паспортов, пароли "
    "и личные данные не пересказывай."
)


def _mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


async def _send(ws, obj: dict) -> None:
    try:
        await ws.send(json.dumps(obj, ensure_ascii=False))
    except Exception as e:
        log.debug(f"[vision_request] ответ не отправлен: {type(e).__name__}: {e}")


async def handle(websocket, data: dict) -> None:
    rid = data.get("request_id")
    device_id = data.get("device_id")

    async def error(code: str, message: str) -> None:
        await _send(websocket, {"type": "error", "request_id": rid,
                                "code": code, "message": message})

    from modules.ws_auth import is_master_device
    if not is_master_device(device_id):
        await error("not_master", "vision_request: только для master-устройств")
        return
    from sakura_core.proto_v2 import connection_secure
    if not connection_secure(websocket) and getattr(config, "PRIVATE_REQUIRES_SECURE", True):
        await error("secure_channel_required", "кадр экрана — только по защищённому каналу")
        return
    source = data.get("source", "window")
    if source not in SOURCES:
        await error("bad_request", "source: window или camera")
        return
    camera = source == "camera"
    image = data.get("image")
    if not isinstance(image, str) or not image or len(image) > MAX_B64:
        await error("bad_request", "нет кадра или он слишком большой")
        return
    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        await error("bad_request", "кадр не в base64")
        return
    mime = _mime(raw)
    if mime is None:
        await error("bad_request", "кадр не JPEG и не PNG")
        return
    default_q = CAMERA_QUESTION if camera else DEFAULT_QUESTION
    question = str(data.get("question") or default_q).strip()[:QUESTION_MAX] or default_q
    log.info(f"[vision_request] {device_id}: {source} кадр {len(raw) // 1024} КиБ ({mime}), "
             f"вопрос {len(question)} симв")

    from google.genai import types as T
    from sakura_core.llm import clean_reply, generate
    from sakura_core.voice_turns import reply_text
    t0 = time.monotonic()
    try:
        text = await generate(
            [T.Part(inline_data=T.Blob(mime_type=mime, data=raw)),
             T.Part(text=(CAMERA_PROMPT if camera else PROMPT).format(question=question))],
            chain=config.VISION_MODEL_CHAIN, max_tokens=300,
            safety=False, thinking=False)
    except Exception as e:
        log.error(f"[vision_request] {device_id}: модель: {type(e).__name__}")
        await error("internal", "не получилось рассмотреть окно")
        return
    finally:
        raw = image = None          # кадр дальше не живёт
    text = reply_text(clean_reply(text or ""))
    if not text:
        await error("internal", "модель не ответила")
        return
    log.info(f"[vision_request] {device_id}: ответ {len(text)} симв за "
             f"{time.monotonic() - t0:.1f}с")
    await _send(websocket, {"type": "reply", "request_id": rid, "device_id": device_id,
                            "text": text, "kind": "llm", "ts": round(time.time(), 3)})
