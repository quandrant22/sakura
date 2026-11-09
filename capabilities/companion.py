"""Домен «companion» (Capri Suite): клипирование, чернила, режим звонков, совместный просмотр.
Все executor=agent.
"""

from sakura_core.executor import AgentCommand, register_table

COMPANION_COMMANDS = {
    "companion.clip": AgentCommand("clip:30"),
    "companion.ink_clear": AgentCommand("clear_ink:"),
    "companion.ink_draw": AgentCommand("draw_ink:"),
    "companion.call_mode_on": AgentCommand("call_mode:on"),
    "companion.call_mode_off": AgentCommand("call_mode:off"),
    "companion.watch_along_start": AgentCommand("watch_along:видео"),
    "companion.watch_along_stop": AgentCommand("watch_along:stop"),
}

register_table(COMPANION_COMMANDS)
