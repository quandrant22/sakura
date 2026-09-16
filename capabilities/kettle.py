"""Домен «чайник» (этап 6, коммит 7B-1): kettle.boil, kettle.off, kettle.status.

Чайник — физическое устройство, executor=agent. reversible: false для boil
(нагрев необратим), true для off и status. confirm: false — команда
ожидаемая, пользователь осознанно включает чайник.

kettle:heat:N и kettle:boil_heat:N (с аргументом температуры) — динамические
действия, не покрываются реестром. Остаются в parse_kettle_command как legacy.
"""

from sakura_core.executor import AgentCommand, register_table

KETTLE_AGENT_ACTIONS = (
    "kettle.boil",
    "kettle.off",
    "kettle.status",
)

KETTLE_COMMANDS = {aid: AgentCommand(aid) for aid in KETTLE_AGENT_ACTIONS}

register_table(KETTLE_COMMANDS)
