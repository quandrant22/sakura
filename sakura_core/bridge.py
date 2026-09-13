"""Мост v2 → v3 (этап 3): быстрый путь реестра для переехавших доменов.

Временный модуль (сверх задания — без него новый путь недостижим из v2,
не переписывая handle_message / handle_voice_command): оба хендлера дергают
v3_fast_path до своей диспетчеризации. Переехавшие домены (этап 3 — только
music.*) исполняются новым путём; остальное решение — v2 продолжает.
На этапах 5-6, когда ветки старого пути вынуты, мост сужается и удаляется.
"""

from __future__ import annotations

import logging

from sakura_core.executor import ExecutionContext, Executor
from sakura_core.router import Router

log = logging.getLogger("sakura.bridge")

_router: Router | None = None
_executor = Executor()

# Домены, переехавшие в v3 к текущему этапу (этап 3: только музыка).
_MOVED_DOMAINS = ("music.",)


def get_router() -> Router:
    """Роутер без LLM — на этапе 3 детерминированный путь."""
    global _router
    if _router is None:
        _router = Router(llm_classify=None)
    return _router


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


async def execute_decision(decision, *, device_ws, device_id, register_command) -> bool:
    """Исполнить решение, если его домен уже переехал в v3. True — исполнено."""
    if not decision.action:
        return False
    if not decision.action.startswith(_MOVED_DOMAINS):
        return False
    ctx = ExecutionContext(device_ws=device_ws, device_id=device_id or "",
                           register_command=register_command)
    await _executor.execute(decision.action, ctx)
    log.info(f"[v3] исполнено: {decision.action} ({decision.source})")
    return True


async def v3_fast_path(text, *, data, device_ws, device_id, register_command,
                       ack=None) -> bool:
    """Быстрый путь: реестр (без LLM) → исполнение переехавших доменов.

    False — решение не для v3 (разговор или домен ещё на v2), старый путь
    продолжает в обычном порядке. ack — необязательный ответчик поверхности
    (Telegram): короткое подтверждение без LLM; голосовой путь отвечает
    через command_result и ack ему не нужен.
    """
    from modules.state import _current_track

    context = resolve_context(
        (data or {}).get("active_window", ""), _current_track or None
    )
    decision = get_router().route(text, context)
    executed = await execute_decision(
        decision, device_ws=device_ws, device_id=device_id,
        register_command=register_command,
    )
    if executed and ack is not None:
        try:
            await ack("Готово.")
        except Exception as e:
            log.debug(f"[v3] ack не доставлен: {type(e).__name__}: {e}")
    return executed
