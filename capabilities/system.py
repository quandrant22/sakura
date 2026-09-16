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
    "close_window.браузер",
    "screenshot.run",
    "screenshot.describe",
    "system.shutdown",
    "system.shutdown_cancel",
    "system.restart",
    "system.sleep",
    "system.lock",
)

SYSTEM_COMMANDS = {aid: AgentCommand(aid) for aid in SYSTEM_AGENT_ACTIONS}
SYSTEM_COMMANDS["open.app"] = AgentCommand("open.app", arg="яндекс музыка")

register_table(SYSTEM_COMMANDS)
