"""Исполнитель v3 (этап 3): решение роутера → vps-хендлер или команда агенту.

Регистрация хендлеров — декоратором или явной таблицей, без цепочек if.
На провод к агенту уходит только канонический id: двух имён у одной
способности (находка 1 v2) и таблиц перевода больше не существует.

execute_critical_action — общий путь для опасных команд (kettle:/system:),
используется и голосовым каналом, и Telegram-текстом.
"""

from __future__ import annotations

import inspect
import json
import logging
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import modules.state as st
from sakura_core.registry import Declaration, load as _load_registry
from sakura_core.session import Session

log = logging.getLogger("sakura.executor")


@dataclass(frozen=True)
class AgentCommand:
    """Команда агенту: канонический id на проводе."""

    action: str
    arg: str = ""


@dataclass
class ExecutionContext:
    """Всё, что нужно хендлеру для исполнения (приходит от адаптера/моста)."""

    device_ws: Any = None                  # WS агента
    device_id: str = ""
    register_command: Optional[Callable[[str, str], str]] = None
    param: Optional[str] = None            # значение параметра из реестра
    extra: dict = field(default_factory=dict)


Handler = Callable[[ExecutionContext], object]

_HANDLERS: dict[str, Handler] = {}


def handler(action_id: str):
    """Декоратор регистрации хендлера действия."""

    def deco(fn: Handler) -> Handler:
        _register(action_id, fn)
        return fn

    return deco


def register_table(table: dict[str, Handler]) -> None:
    """Явная таблица: канонический id → хендлер."""
    for action_id, fn in table.items():
        _register(action_id, fn)


def _register(action_id: str, fn: Handler) -> None:
    if action_id in _HANDLERS:
        raise RuntimeError(f"хендлер действия '{action_id}' уже зарегистрирован")
    _HANDLERS[action_id] = fn


def get_handler(action_id: str) -> Optional[Handler]:
    return _HANDLERS.get(action_id)


def registered() -> tuple[str, ...]:
    return tuple(sorted(_HANDLERS))


class Executor:
    """Исполняет решение роутера: хендлер домена → команда агенту или vps."""

    def __init__(self, send_command: Optional[Callable] = None, *,
                 session: Optional[Session] = None,
                 declarations: Optional[list[Declaration]] = None):
        # send_command: async (AgentCommand, ExecutionContext) → cmd_id | None
        self._send_command = send_command or Executor._default_send
        self._session = session
        decls = list(declarations) if declarations is not None else _load_registry()
        self._declarations: dict[str, Declaration] = {d.id: d for d in decls}
        self._confirm_ids = {i for i, d in self._declarations.items() if d.confirm}

    @staticmethod
    async def _default_send(command: AgentCommand, ctx: ExecutionContext):
        if ctx.device_ws is None:
            raise RuntimeError("нет подключения к агенту")
        cmd_id = None
        if ctx.register_command is not None:
            cmd_id = ctx.register_command(command.action, ctx.device_id)
        payload: dict[str, object] = {
            "type": "command", "action": command.action, "id": cmd_id,
        }
        if command.arg:
            payload["arg"] = command.arg
        await ctx.device_ws.send(json.dumps(payload))
        return cmd_id

    async def execute(self, action_id: str, ctx: ExecutionContext, param: Optional[str] = None):
        # Необратимое действие не исполняется молча: выставляется ожидание
        # подтверждения, вместо исполнения возвращается вопрос. Исполнение
        # придёт следующим ходом — «да» роутер разрешит в Decision(source
        # ="session"), мост передаст confirmed=True. Ответ — (текст, ok):
        # та же форма, что у vps-хендлеров, мост доставит его как есть.
        if action_id in self._confirm_ids and not ctx.extra.get("confirmed"):
            decl = self._declarations[action_id]
            if self._session is not None:
                self._session.expect("confirm", action=action_id,
                                     device=ctx.device_id or None)
            log.info(f"[executor] confirm: {action_id} → ожидание «да»")
            prompt = decl.confirm_prompt or f"{decl.desc}?"
            return (prompt, True)

        fn = _HANDLERS.get(action_id)
        if fn is None:
            raise RuntimeError(f"нет хендлера для '{action_id}'")
        # Передаём param через ctx, чтобы хендлер мог его использовать
        if param is not None:
            ctx = ExecutionContext(
                device_ws=ctx.device_ws,
                device_id=ctx.device_id,
                register_command=ctx.register_command,
                param=param,
                extra=ctx.extra,
            )
        # Хендлер может быть вызываемым, а может быть данными (например,
        # готовой AgentCommand в явной таблице домена).
        result = fn(ctx) if callable(fn) else fn
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, AgentCommand):
            return await self._send_command(result, ctx)
        return result


# ── Опасные команды (kettle:/system:) ─────────────────────────────────

async def execute_critical_action(critical_action: str, ws_dev, device_id,
                                  text: str, active_window: str,
                                  ask_gemini) -> None:
    """Отправить критическую (kettle:/system:) команду агенту и записать эпизод.

    Общий путь выполнения — используется и голосовым каналом (после route_critical
    или после подтверждения "да"), и Telegram-текстом (main.py), чтобы опасные
    системные команды исполнялись одинаково независимо от канала.
    """
    st._last_command_ts = _time.monotonic()
    await ws_dev.send(json.dumps({"type": "command", "action": critical_action}))
    if critical_action.startswith("kettle:"):
        from modules.tts_server import stream_tts_to_device
        _kreply = await ask_gemini(
            f"Мастер попросил: {text}. Команда: {critical_action}. Скажи коротко.",
            save_history=False)
        if _kreply:
            await stream_tts_to_device(_kreply, ws_dev, device_id or "laptop", literal=True)
    try:
        from modules.disposition import current as _disp_ep
        from modules.episodes import add_episode
        _dep = _disp_ep()
        add_episode(
            text=f"Выполнила команду: {text[:80]} → {critical_action}",
            emotion=_dep["stance"],
            valence=_dep["valence"],
            arousal=_dep["arousal"],
            context=active_window,
        )
    except Exception as e:
        log.debug(f"[executor] execute_critical_action: {type(e).__name__}: {e}")
