"""Домены VPS (этап 5): steam (6), task (3), memory (1), weather (1),
vps (2), music_stats (2), briefing (1), capsule (1), reminder (2).

19 действий реестра, все executor=vps. Исполнение — через общую шину
capabilities/_vps.py: канонический id «domain.verb» → легаси «domain:verb» →
modules/voice_info.handle() → (текст, ok). Правило честности v2
(ok=False = источник недоступен, говорим прямо) сохраняется.

ext.* — executor=agent, живут в capabilities/ext.py, здесь их нет.
"""

from capabilities._vps import vps_answer  # noqa: F401  (шина домена)
from sakura_core.executor import ExecutionContext, Handler, register_table

# 19 VPS-действий реестра (все executor=vps).
VPS_DOMAIN_ACTIONS = (
    "steam.achievements",
    "steam.current",
    "steam.last",
    "steam.playtime",
    "steam.progress",
    "steam.recent",
    "task.add",
    "task.done",
    "task.list",
    "memory.forget",
    "weather.now",
    "vps.feeling",
    "vps.status",
    "music_stats.recent",
    "music_stats.top",
    "briefing.now",
    "capsule.list",
    "reminder.add",
    "reminder.list",
)


def _make_vps_handler(aid: str) -> Handler:
    async def _handle(_ctx: ExecutionContext) -> tuple[str, bool]:
        # Исходная фраза Мастера нужна voice_info: reminder/task парсят текст
        # («напомни через N минут X»), а не фиксированный arg из реестра.
        text = ((_ctx.extra or {}).get("text") or "").strip()
        return await vps_answer(aid, "", text)

    _handle.__name__ = f"vps_{aid.replace('.', '_')}"
    return _handle


VPS_HANDLERS = {aid: _make_vps_handler(aid) for aid in VPS_DOMAIN_ACTIONS}

register_table(VPS_HANDLERS)
