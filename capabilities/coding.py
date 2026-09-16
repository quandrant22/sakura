"""Домен «кодинг» (этап 6, коммит 7B-3): coding.*

Кодинговые операции: создание модулей, фикс багов, чтение файлов,
коммиты, сборка. executor=agent, reversible=true, confirm: false.
"""

from sakura_core.executor import AgentCommand, register_table

CODING_AGENT_ACTIONS = (
    "coding.create_module",
    "coding.fix",
    "coding.read_file",
    "coding.commit",
    "coding.build",
    "coding.git_status",
)

CODING_COMMANDS = {aid: AgentCommand(aid) for aid in CODING_AGENT_ACTIONS}

register_table(CODING_COMMANDS)
