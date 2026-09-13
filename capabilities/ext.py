"""Домен «ext/страница» (этап 5): ext.page_content, ext.page_content_youtube.

Оба executor=agent. На провод — только канонический id.
"""

from sakura_core.executor import AgentCommand, register_table

EXT_AGENT_ACTIONS = (
    "ext.page_content",
    "ext.page_content_youtube",
)

EXT_COMMANDS = {aid: AgentCommand(aid) for aid in EXT_AGENT_ACTIONS}

register_table(EXT_COMMANDS)
