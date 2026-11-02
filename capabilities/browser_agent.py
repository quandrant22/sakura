"""browser.task / browser.stop — задача browser agent (sakura_core/browser_step.py).

browser.task: цель из фразы → задача на сервере → browser.do на desktop;
дальше шаги ведёт сервер. browser.stop: «стоп» → browser.cancel активной
задаче. Обе — только при BROWSER_AGENT=1 (иначе декларации не попадают в
роутер, sakura_core/bridge.py).
"""

from sakura_core.executor import ExecutionContext, register_table


async def _browser_task(ctx: ExecutionContext):
    from sakura_core import browser_step
    goal = (ctx.param or "").strip()
    if not goal:
        raise ValueError("browser.task: не извлечена цель (что сделать?)")
    return await browser_step.start(goal, ctx.device_ws, ctx.device_id)


async def _browser_stop(ctx: ExecutionContext):
    from sakura_core import browser_step
    return await browser_step.stop(ctx.device_id or None)


register_table({"browser.task": _browser_task, "browser.stop": _browser_stop})
