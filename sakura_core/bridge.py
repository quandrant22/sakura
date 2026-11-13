"""Мост v2 → v3 (этап 3): быстрый путь реестра для переехавших доменов.

Временный модуль (сверх задания — без него новый путь недостижим из v2,
не переписывая handle_message / handle_voice_command): оба хендлера дергают
v3_fast_path до своей диспетчеризации. На этапе 5 переехали ВСЕ домены
(у каждого из 67 id реестра есть хендлер), поэтому исполняется любое
решение реестра; старые ветки в хендлерах — мёртвый путь для реестровых
формулировок. На этапе 6, когда ветки старого пути вынуты, мост удаляется.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import config

from sakura_core.executor import ExecutionContext, Executor, get_handler
from sakura_core.llm import make_llm_parse
from sakura_core.registry import load as _load_registry
from sakura_core.router import Decision, Router

import conversation as conversation_layer

log = logging.getLogger("sakura.bridge")

_router: Router | None = None
_executor: Executor | None = None

# Загрузка таблиц actions (этап 5): без этого Executor._HANDLERS пуст и
# быстрый путь реестра не исполняет ничего (регистрация — на импорте модуля).
# Список обязан совпадать с доменами реестра: забытый домен — не «домен
# работает иначе», а восемь мёртвых id, о которых узнаёшь из отчёта
# (находка этапа 6). Проверку сторожит _load_registry() ниже.
def _load_capabilities() -> None:
    try:
        import capabilities.browser      # noqa: F401
        import capabilities.browser_agent  # noqa: F401
        import capabilities.calendar     # noqa: F401
        import capabilities.coding       # noqa: F401
        import capabilities.ext          # noqa: F401
        import capabilities.files        # noqa: F401
        import capabilities.kettle       # noqa: F401
        import capabilities.music        # noqa: F401
        import capabilities.pc_control   # noqa: F401
        import capabilities.schedule     # noqa: F401
        import capabilities.computer     # noqa: F401
        import capabilities.system       # noqa: F401
        import capabilities.vps_domains  # noqa: F401
        import capabilities.vision       # noqa: F401
        import capabilities.youtube      # noqa: F401
        import capabilities.companion    # noqa: F401
    except Exception:
        log.exception("[v3] не удалось загрузить таблицы доменов")


_load_capabilities()

# Стартовая проверка достижимости (этап 7): load() валидирует реестр с
# require_handlers=True — декларация без хендлера роняет импорт моста, а не
# уходит тихо на старый путь в бою. Импорт capabilities.* выше обязан быть
# до этой строки: пустая таблица также считается отсутствием исполнения.
BROWSER_AGENT_IDS = ("browser.task", "browser.stop")


def _gate(decls) -> tuple:
    out = []
    for d in decls:
        # computer.do — только при COMPUTER_USE=1: иначе фразы до него не доходят.
        if d.id == "computer.do" and not config.COMPUTER_USE:
            continue
        # browser agent — только при BROWSER_AGENT=1; подтверждение запуска —
        # за флагом BROWSER_CONFIRM_SENSITIVE (как и действий внутри задачи).
        if d.id in BROWSER_AGENT_IDS:
            if not config.BROWSER_AGENT:
                continue
            if d.id == "browser.task":
                d = dataclasses.replace(d, confirm=bool(config.BROWSER_CONFIRM_SENSITIVE))
        out.append(d)
    return tuple(out)


_declarations = _gate(_load_registry())


def get_router() -> Router:
    """Роутер: реестр → clarify → разговор → LLM-классификатор → разговор."""
    global _router
    if _router is None:
        _router = Router(
            declarations=_declarations,
            # Структурированный разбор намерений: план действий с параметрами.
            # Сбой или таймаут — LlmUnavailable, роутер уходит на локальный разбор.
            llm_parse=make_llm_parse(timeout=config.INTENT_TIMEOUT_S),
            conversation=conversation_layer.try_handle,
        )
    return _router


def get_executor() -> Executor:
    """Исполнитель с сессией роутера: confirm-действия ставят ожидание
    в ту же сессию, которую route() опрашивает на первом шаге."""
    global _executor
    if _executor is None:
        _executor = Executor(session=get_router().session, declarations=_declarations)
    return _executor


def resolve_context(active_window: str = "", current_track: dict | None = None):
    """Контекст для реестра: играющая музыка → активное окно.

    Приоритет playing:music первым: домен этапа 3 — музыка, и её действия
    с context (громче/тише/перемотай) должны срабатывать, пока играет трек,
    даже если Мастер смотрит в браузер.
    """
    if current_track:
        return "playing:music"
    win = (active_window or "").lower()
    if "youtube" in win:
        return "window:youtube"
    if any(b in win for b in ("chrome", "opera", "firefox", "edge", "браузер")):
        return "window:browser"
    return None


async def execute_decision(decision, *, device_ws, device_id, register_command,
                           text="", source: str | None = None):
    """Исполнить решение, если у его id есть хендлер (этап 5 — все 67).

    Возвращает (True, результат_хендлера) — исполнено; (False, None) — нет.
    Результат VPS-хендлеров — (текст, ok); агентных AgentCommand — cmd_id.
    """
    if not decision.action:
        return False, None
    if get_handler(decision.action) is None:
        return False, None
    ctx = ExecutionContext(device_ws=device_ws, device_id=device_id or "",
                           register_command=register_command,
                           extra={"text": text or "",
                                  "source": source,
                                  # «да» из диалога подтверждения — исполнять
                                  # без повторного вопроса (executor).
                                  "confirmed": decision.source == "session",
                                  "prepared_command": (decision.pending_payload or {}).get("command")})
    result = await get_executor().execute(decision.action, ctx,
                                          param=decision.param)
    pending = get_router().session.pending
    if (pending is not None and pending.kind == "confirm"
            and pending.action == decision.action):
        log.info(f"[v3] ожидает подтверждения: {decision.action} ({decision.source})")
    else:
        log.info(f"[v3] исполнено: {decision.action} ({decision.source})")
    return True, result


_WORK_LAPTOP = re.compile(
    r"[,\s]*на\s+рабоч(?:ем|ий)\s+(?:ноутбуке|ноуте|компьютере|компе|пк)\b", re.IGNORECASE)


def target_device(text: str) -> tuple[str, str | None]:
    """«… на рабочем ноутбуке» → (фраза без уточнения, WORK_LAPTOP_DEVICE).

    Без уточнения — (фраза, None): команда уходит устройству в фокусе
    (голос — источнику, Telegram — активному)."""
    if not text or not _WORK_LAPTOP.search(text):
        return text, None
    return _WORK_LAPTOP.sub("", text).strip(), config.WORK_LAPTOP_DEVICE


async def v3_fast_path(text, *, data, device_ws, device_id, register_command,
                       ack=None, speak=None, resolve_reply=None,
                       on_llm=None, on_command=None, on_agent_command=None,
                       on_chat=None, source: str | None = None) -> bool:
    """Быстрый путь: реестр (без LLM) → исполнение переехавших доменов.

    False — решение не для v3 (разговор или id без хендлера), старый путь
    продолжает в обычном порядке. ack — ответчик Telegram, speak — озвучка
    голосовой поверхности. resolve_reply — async-обработчик ответа
    разговорного слоя (LLM-подтверждения, отправки, steam): его даёт
    вызывающий хендлер со своими зависимостями; без него доставляется
    только готовый Reply.text. VPS-действие с текстовым результатом отвечает
    найденным текстом; по агентным командам «Готово.» — только в ack
    (Telegram): голос молчит, его ответ придёт через command_result.
    Ни один из ответчиков не обязателен.
    on_llm — хук Router.route: вызывается в момент старта LLM-классификатора
    (п.2: голосовой стрим стартует параллельно классификации).
    on_command — async-хук: вердикт «команда» (у решения есть action) или
    готовый ответ разговорного слоя (reply); зовётся до исполнения и
    озвучки — голосовой prefetch снимается сразу, а не после ответа
    (иначе шлюз открылся бы по таймауту и стрим звучал поверх).
    on_agent_command(decision, cmd_id) — async-хук: команда ушла агенту
    (результат исполнения — cmd_id); голос «вооружает» подтверждение.
    on_chat(text) — async-хук гибридной фразы («поставь чайник, а я пока
    расскажу…»): команды уже исполнены, вызывающий отвечает на реплику
    разговорной моделью; что сделано, она узнаёт из sakura_core/action_note.
    Без хука гибрид исполняется как обычный план, разговорная часть опускается.

    План из нескольких действий (decision.steps) исполняется по порядку,
    ответы собираются в один.
    """
    from modules.state import connected_devices, device_track, prompt_track
    from sakura_core.send import is_share_request

    if is_share_request(text):
        # «Скинь в телегу …» — явная просьба: мимо роутера и разговорного слоя
        # (страхи, шутки), её обрабатывает ветка отправки в Telegram вызывающего.
        log.info("[v3] просьба прислать в Telegram → ветка отправки")
        return False

    text, target = target_device(text)
    if target and target != device_id:
        target_ws = connected_devices.get(target)
        if target_ws is None:
            msg = "Рабочий ноутбук сейчас не в сети."
            for deliver in (ack, speak):
                if deliver is not None:
                    try:
                        await deliver(msg)
                        break
                    except Exception as e:
                        log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
            return True
        log.info(f"[v3] устройство из фразы: {target} (вместо {device_id})")
        device_ws, device_id = target_ws, target

    context = resolve_context(
        (data or {}).get("active_window", ""),
        device_track(device_id) or prompt_track() or None
    )
    route_source = {"source": source} if source is not None else {}
    decision = _vision_intent(text, (data or {}).get("active_window"))
    if decision is None:
        router = get_router()
        if _accepts_dialog(router):
            route_source["dialog"] = _dialog_context(data, device_id)
        decision = await router.route(text, context, on_llm=on_llm, **route_source)
    if on_command is not None and (decision.action or decision.reply is not None):
        await on_command()
    if isinstance(decision.reply, str):
        # Готовая фраза роутера: уточняющий вопрос, отказ от отложенной команды.
        await _deliver(decision.reply, ack, speak)
        return True
    # getattr: подменные решения в тестах старого контракта не знают о плане.
    if getattr(decision, "is_plan", False) or getattr(decision, "chat_tail", None):
        return await _run_plan(decision, text=text, device_ws=device_ws,
                               device_id=device_id, register_command=register_command,
                               ack=ack, speak=speak, on_agent_command=on_agent_command,
                               on_chat=on_chat, source=source)
    if decision.reply is not None:
        if resolve_reply is not None:
            await resolve_reply(decision.reply)
        elif decision.reply.text:
            for deliver in (ack, speak):
                if deliver is None:
                    continue
                try:
                    await deliver(decision.reply.text)
                    break
                except Exception as e:
                    log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
        return True
    executed, result = await execute_decision(
        decision, device_ws=device_ws, device_id=device_id,
        register_command=register_command, text=text, source=source,
    )
    if not executed:
        return False
    from sakura_core import power_confirm
    if result is power_confirm.DELIVERED:
        return True                        # вопрос о питании уже задан там, где Мастер
    if on_agent_command is not None and isinstance(result, str) and result:
        await on_agent_command(decision, result)

    # «Готово» звучит только тогда, когда после него НЕ последует ответ
    # от модели: followup == ack (реестр). При llm ответ придёт через
    # command_result, и «Готово» перед ним — регрессия (два ответа).
    # ack (Telegram) без speak «Готово» нужен всегда: результата
    # с компьютера пользователь не видит.
    from sakura_core.registry import followup_for
    from sakura_core.stylize import humanize_command_reply
    reply: str | None = None
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
        reply = result[0]
        if result[1] is True:
            reply = await humanize_command_reply(reply, action=decision.action)
    if reply:
        confirm_listen = None
        router = get_router()
        session = getattr(router, "session", None)
        pending = session.pending if session is not None else None
        if speak is not None and pending is not None and pending.kind == "confirm":
            confirm_listen = config.CONFIRM_LISTEN_SEC
        if ack is not None:
            try:
                await ack(reply)
            except Exception as e:
                log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
        elif speak is not None:
            try:
                await speak(reply, listen=confirm_listen)
            except TypeError:
                await speak(reply)
            except Exception as e:
                log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
    elif ack is not None and (speak is None or followup_for(decision.action) == "ack"):
        try:
            await ack("Готово.")
        except Exception as e:
            log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
    return True


async def _deliver(text: str, ack, speak, **speak_kw) -> None:
    """Отдать фразу первым доступным ответчиком (Telegram → голос)."""
    for deliver in (ack, speak):
        if deliver is None:
            continue
        try:
            if deliver is speak and speak_kw:
                try:
                    await deliver(text, **speak_kw)
                except TypeError:
                    await deliver(text)
            else:
                await deliver(text)
            return
        except Exception as e:
            log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")


def _accepts_dialog(router) -> bool:
    """Роутер принимает контекст хода (dialog)? Подменные роутеры со старой
    сигнатурой route() продолжают работать без него."""
    import inspect
    try:
        return "dialog" in inspect.signature(router.route).parameters
    except (TypeError, ValueError):
        return False


def _dialog_context(data, device_id) -> dict:
    """Контекст хода для LLM-разбора: окно, трек, последние реплики.

    Только дешёвые локальные чтения; любая ошибка — контекст просто беднее."""
    out: dict = {}
    try:
        window = (data or {}).get("active_window") or ""
        if window:
            out["window"] = window
        from modules.state import device_track, prompt_track
        track = device_track(device_id) or prompt_track()
        if track and track.get("title"):
            out["track"] = f"{track.get('artist', '')} — {track.get('title', '')}".strip(" —")
    except Exception as e:
        log.debug(f"[v3] контекст разбора: {type(e).__name__}: {e}")
    try:
        from modules import chat_log
        messages, _ = chat_log.history(limit=4)
        names = {"user": "Мастер", "assistant": "Сакура"}
        out["recent"] = [f"{names.get(m.get('role'), m.get('role'))}: {m.get('text', '')}"
                         for m in messages if m.get("text")]
    except Exception as e:
        log.debug(f"[v3] контекст разбора (журнал): {type(e).__name__}: {e}")
    return out


async def _run_plan(decision, *, text, device_ws, device_id, register_command,
                    ack, speak, on_agent_command, on_chat, source) -> bool:
    """Исполнить план по шагам и ответить один раз.

    Текстовые результаты (погода, расписание) склеиваются в один ответ;
    команды агенту подтверждает одна фраза — по результату последней.
    Шаг с вопросом подтверждения останавливает план: остальное подождёт
    ответа Мастера. Гибрид (chat_tail + on_chat) подтверждения не озвучивает —
    о сделанном скажет разговорный ответ.
    """
    from sakura_core import action_note, power_confirm
    from sakura_core.registry import followup_for

    texts: list[str] = []
    done: list[str] = []
    last_agent = None
    executed_any = False
    stopped_on_confirm = False
    by_id = {d.id: d for d in _declarations}
    for step in decision.plan:
        sub = Decision(step.action, decision.source, trigger=step.trigger, param=step.param)
        label = by_id[step.action].desc if step.action in by_id else step.action
        try:
            executed, result = await execute_decision(
                sub, device_ws=device_ws, device_id=device_id,
                register_command=register_command, text=step.text or text, source=source)
        except Exception as e:
            log.warning(f"[v3] шаг плана {step.action}: {type(e).__name__}: {e}")
            texts.append(f"Не получилось: {label.lower()}.")
            executed_any = True
            continue
        if not executed:
            log.info(f"[v3] шаг плана {step.action}: нет исполнителя — пропущен")
            continue
        executed_any = True
        if result is power_confirm.DELIVERED:
            return True
        pending = get_router().session.pending
        if pending is not None and pending.kind == "confirm" and pending.action == step.action:
            stopped_on_confirm = True
            if isinstance(result, tuple) and result and isinstance(result[0], str):
                texts.append(result[0])
            break
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
            texts.append(result[0])
            done.append(f"— {label}: {result[0]}")
        elif isinstance(result, str) and result:
            last_agent = (sub, result)
            done.append(f"— {label}" + (f" ({step.param})" if step.param else "")
                        + ": команда отправлена на устройство")
        else:
            done.append(f"— {label}")
    if not executed_any:
        return False
    log.info(f"[v3] план исполнен: {', '.join(decision.actions)} ({decision.source})"
             + (" + разговор" if decision.chat_tail else ""))

    if decision.chat_tail and on_chat is not None and not stopped_on_confirm:
        action_note.set_note("\n".join(done))
        try:
            await on_chat(text)
        except Exception as e:
            log.warning(f"[v3] разговорная часть гибрида: {type(e).__name__}: {e}")
            await _deliver(" ".join(texts) or "Готово.", ack, speak)
        finally:
            action_note.clear()
        return True

    reply = " ".join(t.strip() for t in texts if t and t.strip())
    if reply:
        listen = config.CONFIRM_LISTEN_SEC if (stopped_on_confirm and speak is not None) else None
        await _deliver(reply, ack, speak, **({"listen": listen} if listen else {}))
    elif last_agent is not None and on_agent_command is not None:
        await on_agent_command(*last_agent)
    elif ack is not None and (speak is None or last_agent is None
                              or followup_for(last_agent[0].action) == "ack"):
        try:
            await ack("Готово.")
        except Exception as e:
            log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
    return True


def _vision_intent(text: str, active_window: str | None):
    """Вопрос про игру во время игры → vision.ask до классификатора
    (sakura_core/vision/intent.py). Висит вопрос подтверждения — не трогаем:
    «да/нет» решает роутер."""
    try:
        if get_router().session.pending is not None:
            return None
        from sakura_core.vision.intent import wants_screen
        if not wants_screen(text, active_window):
            return None
    except Exception as e:
        log.debug(f"[v3] vision intent: {type(e).__name__}: {e}")
        return None
    from sakura_core.router import Decision
    log.info("[v3] вопрос про игру → vision.ask (до классификатора)")
    return Decision(action="vision.ask", source="vision_intent")


def confirms_via_executor(action: str | None) -> bool:
    """«да» исполняется через Executor (команда с "confirmed": true), а не
    старым путём execute_critical_action: действия управления компьютером."""
    from capabilities.pc_control import EXECUTOR_CONFIRMED
    return action in EXECUTOR_CONFIRMED


async def handle_v3_confirm(text, *, source: str | None = None,
                            on_execute, on_cancel, on_error=None,
                            on_execute_decision=None):
    """Handle v3 session confirm/deny dialog.

    Returns True if the text was handled by the v3 session, False otherwise.
    on_execute(action) — called when user confirms; should execute the action.
    on_execute_decision(decision) — для действий управления компьютером
    (confirms_via_executor): исполнить решение через execute_decision —
    готовая команда из ожидания уходит с "confirmed": true.
    on_cancel() — called when user denies.
    on_error(err) — called on exception (optional).
    """
    try:
        router = get_router()
        pending = router.session.pending
        if pending is None:
            return False
        dec = await router.route(text, None, source=source)
        if dec.source != "session" or dec.verdict is None:
            return False
        action = pending.action or dec.action or "unknown"
        if dec.verdict == "wrong_source":
            log.info("[confirm] отклонено: другой источник")
            return True
        if dec.verdict == "confirm" and dec.action:
            log.info(f"[confirm] принято: action={action} фраза={text!r}")
            if on_execute_decision is not None and confirms_via_executor(dec.action):
                await on_execute_decision(dec)
            else:
                await on_execute(dec.action)
        else:
            log.info(f"[confirm] отклонено: action={action} фраза={text!r}")
            await on_cancel()
        return True
    except Exception as e:
        if on_error:
            await on_error(e)
        else:
            log.debug(f"[v3] confirm: {type(e).__name__}: {e}")
        return False


async def resolve_conv_reply(reply, *, text, deliver, ask_gemini_fn,
                              get_active_ws_fn, clean_slate_fn,
                              strip_tone_fn=None, on_photo=None,
                              send_vip_fn=None, request_chain=None):
    """Resolve conversation-layer reply: clean slate, WS commands, steam, VIP, text.

    deliver(text) — send text to the user.
    on_photo(url) — optional, send a photo (TG-only).
    strip_tone_fn(text) — optional, strip tone for VIP sends.
    send_vip_fn(vip_id, text) — optional, send to VIP (TG-only).
    """
    if reply.run_clean_slate:
        await clean_slate_fn()
    if reply.ws_command:
        _ws, _dev = get_active_ws_fn()
        if not _ws:
            await deliver(reply.fallback_text or "Ноутбук оффлайн.")
            return
        import json as _json
        await _ws.send(_json.dumps(
            {"type": "command", "action": reply.ws_command}))
    composed = None
    if reply.prompt:
        composed = await ask_gemini_fn(
            reply.prompt, save_history=False,
            chain=request_chain or config.MODEL_CHAIN,
        )
    for _act in reply.actions:
        if _act[0] == "steam_recommend":
            from modules.steam_integration import recommend_games
            games = await recommend_games(limit=5)
            if games:
                game_list = "\n".join(
                    f"• {g['name']} ({g.get('playtime_forever', 0) // 60}ч)"
                    for g in games)
                reply_text = await ask_gemini_fn(
                    f"Мастер спрашивает во что поиграть. Вот его библиотека:\n{game_list}\n\n"
                    f"Порекомендуй 2-3 игры с коротким объяснением почему именно они. "
                    f"В своём стиле, не как список.")
                if reply_text:
                    await deliver(reply_text)
            return
        if _act[0] == "steam_guide":
            from modules.steam_integration import (
                _current_game, find_guide, get_library)
            game_name = _current_game.get("name") if _current_game else None
            if not game_name:
                for g in get_library():
                    if g["name"].lower() in text.lower():
                        game_name = g["name"]
                        break
            if game_name:
                guide = await find_guide(game_name, text)
                if guide["text"]:
                    guide_reply = await ask_gemini_fn(
                        f"Перескажи этот гайд по игре {game_name} своими словами, "
                        f"в своём стиле:\n{guide['text']}")
                    if guide_reply:
                        await deliver(guide_reply)
                    for img_url in guide.get("images", [])[:2]:
                        if on_photo:
                            await on_photo(img_url)
            return
    if reply.send_tg:
        vip_id, raw, vip_name = reply.send_tg
        try:
            to_send = strip_tone_fn(composed) if (raw is None and strip_tone_fn) else (composed if raw is None else raw)
            if send_vip_fn:
                await send_vip_fn(int(vip_id), to_send)
            await deliver(f"Передала {vip_name.capitalize()}: «{to_send}»" if strip_tone_fn
                          else reply.text or f"Передала {vip_name}.")
        except Exception as e:
            log.error(f"conv reply->vip SEND FAIL: {e}")
            await deliver("Не получилось отправить.")
        return
    _out = composed if composed is not None else reply.text
    if _out:
        await deliver(_out)
