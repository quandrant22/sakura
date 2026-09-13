"""Домен «youtube» (этап 5): 12 действий, все executor=agent.

На провод уходит только канонический id (youtube.*). Агент принимает
канонические имена в дополнение к старым youtube_* (этап 5, аналогично
музыке на этапе 3); удаление старых написаний — этап 8.
"""

from sakura_core.executor import AgentCommand, register_table

YOUTUBE_AGENT_ACTIONS = (
    "youtube.forward",
    "youtube.fullscreen",
    "youtube.like",
    "youtube.mini",
    "youtube.next",
    "youtube.pause",
    "youtube.rewind",
    "youtube.speed_down",
    "youtube.speed_up",
    "youtube.sub_toggle",
    "youtube.theater",
    "youtube.trending",
)

YOUTUBE_COMMANDS = {aid: AgentCommand(aid) for aid in YOUTUBE_AGENT_ACTIONS}

register_table(YOUTUBE_COMMANDS)
