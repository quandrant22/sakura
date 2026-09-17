"""Домен «браузер» (этап 5): 10 действий, все executor=agent.

На провод уходит только канонический id (browser.*) — без легаси-написаний
и таблиц перевода. Агент принимает канонические имена в дополнение к старым.
"""

from sakura_core.executor import AgentCommand, register_table

# 10 браузерных действий реестра (browser.*)
BROWSER_AGENT_ACTIONS = (
    "browser.back",
    "browser.forward",
    "browser.scroll_down",
    "browser.scroll_up",
    "browser.tab_close",
    "browser.tab_dup",
    "browser.tab_new",
    "browser.tab_next",
    "browser.tab_prev",
    "browser.tab_reload",
)

BROWSER_COMMANDS = {aid: AgentCommand(aid) for aid in BROWSER_AGENT_ACTIONS}

register_table(BROWSER_COMMANDS)
