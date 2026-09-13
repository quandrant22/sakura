"""Домен «система/приложения» (этап 5): game_mode.*, open.app,
close_window.*, screenshot.* — все executor=agent.

На провод уходит только канонический id. Агент принимает канонические
имена в дополнение к старым; удаление старых написаний — этап 8.
"""

from sakura_core.executor import AgentCommand, register_table

SYSTEM_AGENT_ACTIONS = (
    "game_mode.on",
    "game_mode.off",
    "open.app",
    "close_window.браузер",
    "screenshot.run",
    "screenshot.describe",
)

SYSTEM_COMMANDS = {aid: AgentCommand(aid) for aid in SYSTEM_AGENT_ACTIONS}

register_table(SYSTEM_COMMANDS)
