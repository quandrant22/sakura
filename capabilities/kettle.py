"""Домен «чайник» (этап 6, коммит 7B-1): kettle.boil, kettle.off, kettle.status,
kettle.heat, kettle.boil_heat.

Чайник — физическое устройство, executor=agent. reversible: false для boil
и heat (нагрев необратим), true для off и status. confirm: false — команда
ожидаемая, пользователь осознанно включает чайник.

kettle.heat и kettle.boil_heat используют param (температура) из реестра.
"""

from sakura_core.executor import AgentCommand, register_table

KETTLE_AGENT_ACTIONS = (
    "kettle.boil",
    "kettle.off",
    "kettle.status",
    "kettle.heat",
    "kettle.boil_heat",
)


def _make_kettle_command(action_prefix: str):
    """Создаёт хендлер, подставляющий param в action на проводе.

    Например, action_prefix='kettle:heat', param='60' → action='kettle:heat:60'.
    Это совместимо со старым форматом, который ожидает command_router.py агента.
    """
    def handler(ctx):
        temp = ctx.param or ""
        return AgentCommand(f"{action_prefix}:{temp}" if temp else action_prefix)
    return handler


KETTLE_COMMANDS = {
    "kettle.boil": AgentCommand("kettle:boil"),
    "kettle.off": AgentCommand("kettle:off"),
    "kettle.status": AgentCommand("kettle:status"),
    "kettle.heat": _make_kettle_command("kettle:heat"),
    "kettle.boil_heat": _make_kettle_command("kettle:boil_heat"),
}

register_table(KETTLE_COMMANDS)
