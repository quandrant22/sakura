"""Домен «календарь» (этап 6, коммит 7B-5): calendar.list.

Чтение событий из Google Calendar. executor=agent, reversible=true.
confirm: false.

Запись событий (calendar.add, calendar.delete) пока не реализована —
модуль modules/calendar_module.py поддерживает только чтение.
"""

from sakura_core.executor import AgentCommand, register_table

CALENDAR_AGENT_ACTIONS = (
    "calendar.list",
)

CALENDAR_COMMANDS = {aid: AgentCommand(aid) for aid in CALENDAR_AGENT_ACTIONS}

register_table(CALENDAR_COMMANDS)
