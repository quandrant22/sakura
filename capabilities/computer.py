"""computer.do (feat/pc-control, п.3): агент выполняет задачу по шагам.

Команда агенту: {"action": "computer.do", "arg": <цель>, "confirmed": true}.
Дальше агент сам шлёт computer_step (кадр + история) и исполняет ответ
сервера (sakura_core/computer_use.py). Включается COMPUTER_USE=1.
"""

from sakura_core.executor import AgentCommand, ExecutionContext, register_table


def _computer_do(ctx: ExecutionContext) -> AgentCommand:
    goal = (ctx.param or "").strip()
    if not goal:
        raise ValueError("computer.do: не извлечена цель (что сделать?)")
    return AgentCommand("computer.do", arg=goal[:300])


register_table({"computer.do": _computer_do})
