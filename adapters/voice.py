"""Голосовой адаптер v3 (этап 4): честный стриминг LLM → TTS.

В v2 stream_llm_to_tts (modules/tts_server.py:563) называется «стримингом»,
но дренирует итератор до конца (asyncio.to_thread _drain) и только потом
зовёт синтез; переменные buf/sentences для посентенсной отдачи объявлены
и не использованы (ruff F841). Бюджет «первый звук 800 мс» при таком коде
недостижим.

Здесь стриминг — основа: предложение готово → сразу в синтез. Стадии
синтезируются параллельно, пакеты уходят на устройство строго по порядку
стадий (обобщение правильного _stream_two_stage из v2 на N стадий).
Примитивы синтеза берутся из v2 как есть (переносятся на этапе 6):
_make_audio_sender, _live_synthesize, _stream_two_stage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import websockets
from typing import AsyncIterator, Optional

from sakura_core import budget
from sakura_core import llm as _llm
from modules.tts_server import (
    _make_audio_sender,
    _live_synthesize,
    _stream_two_stage,
)
from modules.ws_auth import check_token, is_master_device, reject
from modules.device_manager import set_device_offline
from modules.state import connected_devices, _pending_commands, _plan_cancel
from modules.presence_sync import set_offline as ps_offline
from modules.rituals import should_farewell, get_farewell_prompt
from modules.app_mapping import find_vip_by_name
from sakura_core.memory_tasks import clean_slate
from sakura_core.apps import analyze_apps, analyze_screen_context
from sakura_core.llm import ask_gemini, ask_gemini_voice

PLAN_WAIT_ACK = True

log = logging.getLogger("sakura.voice")

_SENT_END = re.compile(r"(?<=[.!?…])\s+")
_NL_WS = re.compile(r"\s*\n\s*")
_EMOTION_LINE = re.compile(r"^EMOTION:\s*(.+?)\s*$", re.MULTILINE)


async def iter_sentences(tokens: AsyncIterator[str]) -> AsyncIterator[str]:
    """Ассемблер стрима: токены → готовые предложения.

    Предложение высвобождается сразу, как только встречен разделитель —
    поток не дожидается конца (это и есть честный стриминг).
    """
    buf = ""
    async for tok in tokens:
        buf += tok
        while True:
            m = _SENT_END.search(buf)
            if not m:
                break
            head, buf = buf[: m.end()], buf[m.end():]
            if head.strip():
                yield head.strip()
    if buf.strip():
        yield buf.strip()


async def stream_llm_to_tts(
    contents,
    system: str = "",
    websocket=None,
    device_id=None,
    client=None,
    model: Optional[str] = None,
    max_tokens: int = 200,
    temperature: float = 0.85,
    api_key: Optional[str] = None,
    emotion: str = "спокойная",
    stop=None,
) -> tuple[str, str]:
    """Стриминг LLM→TTS: предложение готово → сразу в синтез.

    Сигнатура совместима с вызовами v2 (main.py ask_gemini_voice): голосовой
    путь идёт через этот адаптер. Возвращает (полный текст, эмоция).
    stop — опциональный callable(): True между пакетами → обрыв озвучки.
    """
    key = _llm.pick_key(api_key)
    if client is None:
        client = _llm.get_client(key)
    t0 = time.monotonic()
    parts: list[str] = []
    queues: list[asyncio.Queue] = []
    producers: list[asyncio.Task] = []
    first_audio_logged = False
    synth_failed = False

    async def _produce(text: str, q: asyncio.Queue, stage: int) -> None:
        try:
            await _live_synthesize(text, emotion, q.put, label=f"стадия {stage}")
        except Exception as e:
            log.error(f"[voice] стадия {stage}: синтез упал: {e}")
            await q.put(e)
        finally:
            await q.put(None)

    def _new_stage(text: str) -> None:
        q: asyncio.Queue = asyncio.Queue()
        queues.append(q)
        producers.append(asyncio.create_task(_produce(text, q, len(queues))))

    async def _drain(q: asyncio.Queue) -> bool:
        """Выкачать стадию на устройство до sentinel-а. True — дочитана."""
        nonlocal first_audio_logged, synth_failed
        while True:
            data = await q.get()
            if data is None:
                return True
            if isinstance(data, Exception):
                synth_failed = True
                return True
            if stop is not None and stop():
                return False
            try:
                await _make_audio_sender(websocket, device_id)(data)
            except Exception as e:
                log.error(f"[voice] отправка пакета: {e}")
                return True
            if not first_audio_logged:
                first_audio_logged = True
                _ms = (time.monotonic() - t0) * 1000
                log.info(f"[voice] первый звук за {_ms:.0f}мс")
                budget.check("voice_first_audio", _ms)


    try:
        tokens = _llm.stream_tokens(
            contents, system=system, model=model, max_tokens=max_tokens,
            temperature=temperature, api_key=key,
        )
        async for sentence in iter_sentences(tokens):
            m = _EMOTION_LINE.match(sentence)
            if m:
                emotion = m.group(1)
                continue
            parts.append(sentence)
            _new_stage(sentence)
    except Exception as e:
        log.error(f"[voice] стрим LLM упал: {e}")

    # Ни одного предложения — фолбэк: обычная генерация → двухстадийный путь v2
    if not parts:
        text = (await _llm.generate(contents, system=system, model=model,
                                    max_tokens=max_tokens, temperature=temperature,
                                    api_key=key)).strip()
        if not text:
            return "", emotion
        clean = text
        for line in text.split("\n"):
            if line.strip().startswith("EMOTION:"):
                emotion = line.strip().replace("EMOTION:", "").strip()
        clean = _NL_WS.sub(" ", _EMOTION_LINE.sub("", clean)).strip()
        first, _, rest = clean.partition(". ")
        if rest.strip():
            await _stream_two_stage(first.strip() + ".", rest.strip(), websocket,
                                    device_id, emotion, t0, stop=stop)
        elif websocket:
            await _live_synthesize(clean, emotion,
                                   _make_audio_sender(websocket, device_id))
        return clean, emotion

    # Пакеты уходят строго по порядку стадий
    for q in queues:
        if not await _drain(q):
            break

    for t in producers:
        if not t.done():
            t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.debug(f"[voice] продюсер: {e}")

    if not synth_failed:
        budget.timed("voice_total", t0)
    full_text = " ".join(parts)
    log.info(f"[voice] ответ за {time.monotonic() - t0:.1f}с, {len(full_text)} симв")
    return full_text, emotion


# ── WebSocket-команды (перенесено из main.py, commit 6) ──────────────────

import uuid

from modules.state import _pending_commands, connected_devices


def _cleanup_pending_commands():
    """Удаляет команды старше 5 минут."""
    now = time.monotonic()
    expired = [k for k, v in _pending_commands.items() if now - v["ts"] > 300]
    for k in expired:
        del _pending_commands[k]


def _register_command(action: str, device: str) -> str:
    """Регистрирует команду и возвращает её id."""
    cmd_id = uuid.uuid4().hex[:12]
    _pending_commands[cmd_id] = {
        "action": action,
        "device": device,
        "ts": time.monotonic(),
        "status": "sent",
    }
    _cleanup_pending_commands()
    return cmd_id


def _resolve_command_status(device: str, ok: bool, detail: str) -> str:
    """Находит последнюю pending-команду (status==sent) для устройства, обновляет статус."""
    now = time.monotonic()
    best_id = None
    best_ts = -1
    for cmd_id, cmd in _pending_commands.items():
        if cmd["status"] == "sent" and cmd["device"] == device and now - cmd["ts"] < 300:
            if cmd["ts"] > best_ts:
                best_ts = cmd["ts"]
                best_id = cmd_id
    if best_id:
        _pending_commands[best_id]["status"] = "executed" if ok else "failed"
        _pending_commands[best_id]["detail"] = detail
        return _pending_commands[best_id]["status"]
    return "executed" if ok else "failed"


def _get_active_ws():
    """Возвращает websocket активного подключённого устройства.
    Порядок: активное по presence_sync → первое онлайн → None.
    """
    try:
        from modules.presence_sync import get_active_device
        dev = get_active_device()
        if dev and dev in connected_devices:
            return connected_devices[dev], dev
    except Exception as e:
        log.debug(f"[voice] _get_active_ws: {type(e).__name__}: {e}")
    for dev_id, ws in connected_devices.items():
        return ws, dev_id
    return None, None


# ── TG-утилиты для голосового пути ────────────────────────────────────

_TG_MSG_LIMIT = 4096


def split_tg(text: str) -> list[str]:
    """Режет текст на куски ≤4096, не рвя внутри строки (каждая строка —
    пункт списка). Строку длиннее лимита (редкость) режем по пробелу."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= _TG_MSG_LIMIT:
        return [text]
    chunks, cur = [], ""
    for line in text.splitlines():
        while len(line) >= _TG_MSG_LIMIT:
            cut = line.rfind(" ", 0, _TG_MSG_LIMIT)
            if cut <= 0:
                cut = _TG_MSG_LIMIT
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:cut].strip())
            line = line[cut:].strip()
        nxt = (cur + "\n" + line) if cur else line
        if len(nxt) > _TG_MSG_LIMIT:
            chunks.append(cur)
            cur = line
        else:
            cur = nxt
    if cur:
        chunks.append(cur)
    return chunks


async def answer_voice_info(action: str, arg: str, text: str,
                            ws_dev, device_id, ask_gemini, bot) -> None:
    """Информационные команды (steam:/vps:/reminder:/task:/weather:/music_stats:/
    capsule:/briefing:): факты берём из модуля-источника и озвучиваем/отправляем.

    Работает БЕЗ устройства. Честность: если источник недоступен или пуст —
    говорим это прямо (literal), НЕ пропуская через LLM-стилизацию."""
    from modules.tts_server import stream_tts_to_device, strip_tone
    from config import MASTER_ID

    try:
        if action == "briefing:now":
            from modules.briefing import build_briefing_prompt
            bp = await build_briefing_prompt()
            reply = await ask_gemini(
                bp + "\nОтветь Мастеру коротко: 3-4 самых важного пункта.",
                save_history=False) if bp else ""
            if not reply:
                reply = "Брифинг сейчас собрать не удалось."
            ok = bool(reply and "не удалось" not in reply)
        else:
            from modules import voice_info as _vinfo
            reply, ok = await _vinfo.handle(action, arg, text)
    except Exception as e:
        log.error(f"[voice_info] {action}: {type(e).__name__}: {e}")
        reply, ok = "Не смогла получить данные — источник недоступен.", False

    if (isinstance(reply, str)
            and action in ("steam:achievements:full",
                           "steam:achievements:todo",
                           "steam:achievements:done")):
        from modules import voice_info as _vi
        from modules.state import tts_stop_requested
        mode = action.split(":")[-1]
        want_read = bool(re.search(
            r"(?<!\w)(?:зачитай|прочитай|перечисли|назови\s+все|читай\s+вслух)\w*",
            (text or "").lower()))
        summary = (reply or "").strip().splitlines()
        summary = summary[0] if summary else reply
        if ws_dev and want_read:
            parts, ok_read = await _vi.steam_achievements_read(arg, mode)
            if ok_read:
                from modules.state import tts_reading_start, tts_reading_end
                tts_reading_start(device_id or "laptop")
                try:
                    for p in parts:
                        if tts_stop_requested(device_id or "laptop"):
                            break
                        await stream_tts_to_device(p, ws_dev, device_id or "laptop",
                                                   literal=True)
                finally:
                    tts_reading_end(device_id or "laptop")
            return
        if ws_dev:
            await stream_tts_to_device(
                f"{summary}. Полный список отправила в Telegram.",
                ws_dev, device_id or "laptop", literal=True)
        tl = strip_tone(reply)[1]
        for chunk in split_tg(tl):
            await bot.send_message(MASTER_ID, chunk)
        return

    if ok and reply:
        try:
            styled = await ask_gemini(
                f"Факты:\n{reply}\n\n"
                "Передай это Мастеру коротко и точно. НИЧЕГО не выдумывай, "
                "не добавляй и не меняй числа и названия. Если данных мало — "
                "скажи об этом прямо.",
                save_history=False)
        except Exception as e:
            log.debug(f"[voice_info] стилизация не удалась: {e}")
            styled = None
        final = (styled or "").strip() or reply
    else:
        final = (reply or "").strip() or "Не нашла данных."

    if ws_dev:
        await stream_tts_to_device(final, ws_dev, device_id or "laptop", literal=True)
    else:
        await bot.send_message(MASTER_ID, strip_tone(final)[1])


async def speak_now_playing_result(cmd_id: str, ws_dev, device_id: str, bot) -> None:
    """music:now_playing: ждём command_result от агента (до 25с) и озвучиваем."""
    import asyncio
    import modules.state as st
    from modules.tts_server import stream_tts_to_device
    from config import MASTER_ID

    try:
        for _ in range(125):
            await asyncio.sleep(0.2)
            _cmd = st._pending_commands.get(cmd_id, {})
            if _cmd.get("spoken") or _cmd.get("status") in ("executed", "failed"):
                break
        _cmd    = st._pending_commands.get(cmd_id, {})
        _status = _cmd.get("status", "sent")
        _detail = (_cmd.get("detail") or "").strip()
        if _cmd.get("spoken"):
            return
        if _status == "executed" and _detail:
            _reply = _detail
        else:
            _reply = ("Не вижу, что сейчас играет — Яндекс Музыка не отвечает. "
                      "Похоже, она не запущена.")
        _cmd["answered"] = True
        log.info(f"[голос] ответ: {_reply!r}")
        if ws_dev:
            await stream_tts_to_device(_reply, ws_dev, device_id, literal=True)
        try:
            await bot.send_message(MASTER_ID, _reply)
        except Exception as e:
            log.debug(f"[music] now_playing tg: {type(e).__name__}: {e}")
    except Exception as e:
        log.debug(f"[music] now_playing: {type(e).__name__}: {e}")


# ─────────────────────────────────────────────
#  WebSocket — устройства (moved from main.py)
# ─────────────────────────────────────────────

async def _execute_plan(plan: dict, master_key: str, ws_dev, device_id) -> tuple[bool, str]:
    """Исполняет план по шагам. Возвращает (успех, сообщение)."""
    import time as _pt
    steps = plan.get("steps", [])
    summary = plan.get("summary", "задача")

    for i, step in enumerate(steps):
        if _plan_cancel.get(master_key):
            _plan_cancel.pop(master_key, None)
            return False, f"План остановлен на шаге {i + 1} по запросу Мастера."

        action = step.get("action", "")
        arg = step.get("arg", "")

        if action == "wait":
            try:
                wait_sec = min(int(arg), 10)
            except (ValueError, TypeError):
                wait_sec = 1
            await asyncio.sleep(wait_sec)
            continue

        if not ws_dev:
            return False, "Устройство offline, план не может быть выполнен."

        full_action = f"{action}:{arg}" if arg and ":" not in action else action
        _cmd_id = _register_command(full_action, device_id or "laptop")
        await ws_dev.send(json.dumps({"type": "command", "action": full_action, "id": _cmd_id}))

        if PLAN_WAIT_ACK:
            for _ in range(50):
                await asyncio.sleep(0.2)
                cmd = _pending_commands.get(_cmd_id, {})
                if cmd.get("status") in ("executed", "failed"):
                    if cmd["status"] == "failed":
                        return False, f"План остановлен на шаге {i + 1}: {full_action} — {cmd.get('detail', 'ошибка')}"
                    break
            else:
                return False, f"План остановлен на шаге {i + 1}: {full_action} — таймаут ожидания"
        else:
            await asyncio.sleep(1.0)

    return True, f"План выполнен: {summary}"


async def ws_handler(websocket):
    from adapters.telegram import bot, send_to_master, send_safe
    from modules.ws_handlers import (
        handle_register, handle_ping, handle_apps_list, handle_screen_context,
        handle_command_result, handle_kettle_ready, handle_notification,
        handle_tg_message, handle_voice_command, update_current_track,
    )
    from modules.web_search import search_and_fetch, needs_search, search_image, download_bytes
    from modules.youtube import youtube_command
    device_id = None
    try:
        async for raw in websocket:
            try:
                data     = json.loads(raw)
                msg_type = data.get("type")

                if not check_token(data):
                    await reject(websocket, reason=f"invalid token on '{msg_type}'")
                    return

                dev_from_msg = data.get("device_id")
                if msg_type in ("voice_command", "apps_list"):
                    if not is_master_device(dev_from_msg):
                        await reject(websocket, reason=f"'{msg_type}' denied: not master device ({dev_from_msg!r})")
                        return

                _ctx = {
                    "ask_gemini": ask_gemini,
                    "ask_gemini_voice": ask_gemini_voice,
                    "send_safe": send_safe,
                    "_find_vip_by_name": find_vip_by_name,
                    "_translate_en": None,
                    "_clean_slate": clean_slate,
                    "_execute_plan": _execute_plan,
                    "_register_command": _register_command,
                    "_resolve_command_status": _resolve_command_status,
                    "_get_active_ws": _get_active_ws,
                    "analyze_apps": analyze_apps,
                    "_analyze_screen_context": analyze_screen_context,
                    "_gemini_client": None,
                    "bot": bot,
                    "PLAN_WAIT_ACK": PLAN_WAIT_ACK,
                }

                HANDLERS = {
                    "register": handle_register,
                    "ping": handle_ping,
                    "apps_list": handle_apps_list,
                    "screen_context": handle_screen_context,
                    "command_result": handle_command_result,
                    "kettle_ready": handle_kettle_ready,
                    "notification": handle_notification,
                    "tg_message": handle_tg_message,
                    "voice_command": handle_voice_command,
                }
                handler = HANDLERS.get(msg_type)
                if handler:
                    await handler(websocket, data, _ctx)
                else:
                    log.warning(f"unknown msg_type: {msg_type}")

                if msg_type in ("register", "ping", "voice_command"):
                    device_id = data.get("device_id")

                update_current_track(data)

            except Exception as e:
                log.error(f"[ws_handler] {e}")

    except websockets.exceptions.ConnectionClosed as e:
        log.debug(f"[ws_handler] {type(e).__name__}: {e}")
    finally:
        if device_id:
            set_device_offline(device_id)
            connected_devices.pop(device_id, None)
            await asyncio.to_thread(ps_offline, device_id)
            log.info(f"Устройство отключено: {device_id}")

            if is_master_device(device_id) and should_farewell():
                farewell = await ask_gemini(get_farewell_prompt(), save_history=False)
                if farewell:
                    await send_to_master(farewell)

