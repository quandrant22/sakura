"""Домен «система/приложения» (этап 5): game_mode.*, open.app,
close_window.*, screenshot.*, system.* — все executor=agent.

На провод уходит только канонический id. Агент принимает канонические
имена в дополнение к старым; удаление старых написаний — этап 8.
open.app из реестра — запуск музыки (триггеры «включи музыку» и т.п.):
агент без аргумента открывает Яндекс Музыку, как open_app:яндекс музыка.

system.shutdown / system.restart / system.sleep (этап 5, переезд 3/3):
опасные и необратимые (reversible: false) — в реестре у них confirm: true,
не исполняются молча (sakura_core/executor.py). До этого переезда они
жили только в v2 (`parse_system_command`, `_CRITICAL_EXACT`,
`_pending_system`) и в реестре их не было вовсе.
"""

from sakura_core.executor import AgentCommand, register_table

SYSTEM_AGENT_ACTIONS = (
    "game_mode.on",
    "game_mode.off",
    "open.app",
    "app.switch",
    "app.switch_open",
    "close_window.браузер",
    "screenshot.run",
    "screenshot.describe",
    "system.shutdown",
    "system.shutdown_cancel",
    "system.restart",
    "system.sleep",
    "system.lock",
    "system.volume",
)

SYSTEM_COMMANDS = {aid: AgentCommand(aid) for aid in SYSTEM_AGENT_ACTIONS}
SYSTEM_COMMANDS["open.app"] = AgentCommand("open.app", arg="яндекс музыка")


def _switch_app(ctx) -> AgentCommand:
    """app.switch / app.switch_open → switch_to_app:<имя> — знакомый агенту провод.

    Пустой app — ошибка, а не голая команда: обе декларации объявляют param
    required: ask, роутер в этом случае сначала спрашивает приложение
    (registry_clarify). Сюда пустое значение доезжает только с LLM-пути;
    падение безопасно — вызывающий хендлер уходит на старый путь.
    """
    app = (ctx.param or "").strip()
    if not app:
        raise ValueError(
            "app.switch: не извлечён параметр app (какое приложение?)"
        )
    return AgentCommand("switch_to_app", arg=app)


SYSTEM_COMMANDS["app.switch"] = _switch_app
SYSTEM_COMMANDS["app.switch_open"] = _switch_app


def _set_volume(ctx) -> AgentCommand:
    """Установить системную громкость на переданный процент."""
    level = (ctx.param or "").strip()
    if not level:
        raise ValueError("system.volume: не извлечён уровень громкости")
    return AgentCommand("volume", arg=level)


SYSTEM_COMMANDS["system.volume"] = _set_volume

register_table(SYSTEM_COMMANDS)
