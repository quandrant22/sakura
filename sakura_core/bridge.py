"""Мост v2 → v3 (этап 3): быстрый путь реестра для переехавших доменов.

Временный модуль (сверх задания — без него новый путь недостижим из v2,
не переписывая handle_message / handle_voice_command): оба хендлера дергают
v3_fast_path до своей диспетчеризации. На этапе 5 переехали ВСЕ домены
(у каждого из 67 id реестра есть хендлер), поэтому исполняется любое
решение реестра; старые ветки в хендлерах — мёртвый путь для реестровых
формулировок. На этапе 6, когда ветки старого пути вынуты, мост удаляется.
"""

from __future__ import annotations

import logging

from sakura_core.executor import ExecutionContext, Executor, get_handler
from sakura_core.llm import make_llm_classify
from sakura_core.router import Router

import conversation as conversation_layer

log = logging.getLogger("sakura.bridge")

_router: Router | None = None
_executor: Executor | None = None

# Этап 5 завершён: хендлер есть у каждого из 67 действий реестра, поэтому
# решение исполняется по любому каноническому id, известному реестру.
_DOMAINS_MOVED = True

# Загрузка таблиц actions (этап 5): без этого Executor._HANDLERS пуст и
# быстрый путь реестра не исполняет ничего (регистрация — на импорте модуля).
def _load_capabilities() -> None:
    try:
        import capabilities.browser  # noqa: F401
        import capabilities.ext      # noqa: F401
        import capabilities.music    # noqa: F401
        import capabilities.system   # noqa: F401
        import capabilities.vps_domains  # noqa: F401
        import capabilities.youtube  # noqa: F401
    except Exception:
        log.exception("[v3] не удалось загрузить таблицы доменов")


_load_capabilities()


def get_router() -> Router:
    """Роутер: реестр → clarify → разговор → LLM-классификатор → разговор."""
    global _router
    if _router is None:
        _router = Router(
            llm_classify=make_llm_classify(timeout=5.0),
            conversation=conversation_layer.try_handle,
        )
    return _router


def get_executor() -> Executor:
    """Исполнитель с сессией роутера: confirm-действия ставят ожидание
    в ту же сессию, которую route() опрашивает на первом шаге."""
    global _executor
    if _executor is None:
        _executor = Executor(session=get_router().session)
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
                           text=""):
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
                                  # «да» из диалога подтверждения — исполнять
                                  # без повторного вопроса (executor).
                                  "confirmed": decision.source == "session"})
    result = await get_executor().execute(decision.action, ctx)
    log.info(f"[v3] исполнено: {decision.action} ({decision.source})")
    return True, result


async def v3_fast_path(text, *, data, device_ws, device_id, register_command,
                       ack=None, speak=None, resolve_reply=None) -> bool:
    """Быстрый путь: реестр (без LLM) → исполнение переехавших доменов.

    False — решение не для v3 (разговор или id без хендлера), старый путь
    продолжает в обычном порядке. ack — ответчик Telegram, speak — озвучка
    голосовой поверхности. resolve_reply — async-обработчик ответа
    разговорного слоя (LLM-подтверждения, отправки, steam): его даёт
    вызывающий хендлер со своими зависимостями; без него доставляется
    только готовый Reply.text. VPS-действие с текстовым результатом отвечает
    найденным текстом; агентные команды — коротким «Готово.». Ни один из
    ответчиков не обязателен: голосовой путь отвечает через command_result.
    """
    from modules.state import _current_track

    context = resolve_context(
        (data or {}).get("active_window", ""), _current_track or None
    )
    decision = get_router().route(text, context)
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
        register_command=register_command, text=text,
    )
    if not executed:
        return False

    # VPS-хендлеры возвращают (текст, ok) — отвечаем текстом, а не «Готово.»
    reply: str | None = None
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
        reply = result[0]
    for deliver in (ack, speak):
        if deliver is None:
            continue
        try:
            if reply:
                await deliver(reply)
            else:
                await deliver("Готово.")
            break
        except Exception as e:
            log.debug(f"[v3] ответ не доставлен: {type(e).__name__}: {e}")
    return True


async def handle_v3_confirm(text, *, on_execute, on_cancel, on_error=None):
    """Handle v3 session confirm/deny dialog.

    Returns True if the text was handled by the v3 session, False otherwise.
    on_execute(action) — called when user confirms; should execute the action.
    on_cancel() — called when user denies.
    on_error(err) — called on exception (optional).
    """
    try:
        router = get_router()
        if router.session.pending is None:
            return False
        dec = router.route(text, None)
        if dec.source != "session" or dec.verdict is None:
            return False
        if dec.verdict == "confirm" and dec.action:
            await on_execute(dec.action)
        else:
            await on_cancel()
        return True
    except Exception as e:
        if on_error:
            await on_error(e)
        else:
            log.debug(f"[v3] confirm: {type(e).__name__}: {e}")
        return False
