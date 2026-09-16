"""Домен «файлы» (этап 6, коммит 7B-2): files.open.

Поиск и открытие файлов на устройстве. executor=agent, reversible=true.
confirm: false — пользователь осознанно запрашивает файл.
"""

from sakura_core.executor import AgentCommand, register_table

FILES_AGENT_ACTIONS = (
    "files.open",
)

FILES_COMMANDS = {aid: AgentCommand(aid) for aid in FILES_AGENT_ACTIONS}

register_table(FILES_COMMANDS)
