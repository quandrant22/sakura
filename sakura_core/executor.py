"""Исполнитель v3 (этап 3): решение роутера → vps-хендлер или команда агенту.

Регистрация хендлеров — декоратором или явной таблицей, без цепочек if.
На провод к агенту уходит только канонический id: двух имён у одной
способности (находка 1 v2) и таблиц перевода больше не существует.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

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

    async def execute(self, action_id: str, ctx: ExecutionContext):
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
            return (f"{decl.desc}? Подтверди, пожалуйста.", True)

        fn = _HANDLERS.get(action_id)
        if fn is None:
            raise RuntimeError(f"нет хендлера для '{action_id}'")
        # Хендлер может быть вызываемым, а может быть данными (например,
        # готовой AgentCommand в явной таблице домена).
        result = fn(ctx) if callable(fn) else fn
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, AgentCommand):
            return await self._send_command(result, ctx)
        return result
