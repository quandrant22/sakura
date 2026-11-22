"""Домен «scrap_mechanic»: телепортация, отхил, бессмертие, навигация к вещам/лифту.
Все executor=agent.
"""

from sakura_core.executor import AgentCommand, register_table

SCRAP_MECHANIC_COMMANDS = {
    "scrap_mechanic.tp_bag": AgentCommand("sm:tp_bag"),
    "scrap_mechanic.tp_elevator": AgentCommand("sm:tp_elevator"),
    "scrap_mechanic.heal": AgentCommand("sm:heal"),
    "scrap_mechanic.godmode_on": AgentCommand("sm:godmode_on"),
    "scrap_mechanic.godmode_off": AgentCommand("sm:godmode_off"),
    "scrap_mechanic.kill_bots": AgentCommand("sm:kill_bots"),
    "scrap_mechanic.where_bag": AgentCommand("sm:nav_bag"),
    "scrap_mechanic.where_elevator": AgentCommand("sm:nav_elevator"),
}

register_table(SCRAP_MECHANIC_COMMANDS)
