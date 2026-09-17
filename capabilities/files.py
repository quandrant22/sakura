"""Домен «файлы» (этап 6, коммит 7B-2): files.open — executor=agent.

Поиск и открытие файлов на устройстве (ноутбук): индекс файлов и запуск
живут в агенте (agent/file_index.py, agent/core/hands.py), поэтому
executor=agent. reversible=true, confirm: false — пользователь осознанно
запрашивает файл.

Развязка этапа 7: files.open был недостижим — агент не знает канонического
id files.open, а серверного пути для файлов и не было. Нового verb'а агенту
не нужно: в agent/core/hands.py уже есть open_file, который разбирается
командой execute_command как «open_file:<имя>», а file_index сам разрешает
имя по всему диску. Хендлер отдаёт на провод ровно тот формат, который
агент ждёт, — так же, как capabilities/kettle.py отдаёт «kettle:heat:60».
"""

from sakura_core.executor import AgentCommand, ExecutionContext, Handler, register_table

# Существующий verb агента (agent/core/hands.py:execute_command).
FILES_OPEN_VERB = "open_file"


def _open_file(ctx: ExecutionContext) -> AgentCommand:
    """files.open → open_file:<query> — знакомый агенту провод, без правок агента.

    Пустой query — ошибка, а не голая команда: реестр объявляет param
    required: ask, роутер в этом случае сначала спрашивает файл
    (registry_clarify). Сюда пустое значение доезжает только с LLM-пути;
    падение безопасно — вызывающий хендлер уходит на старый путь.
    """
    query = (ctx.param or "").strip()
    if not query:
        raise ValueError(
            "files.open: не извлечён параметр query (какой файл искать?)"
        )
    return AgentCommand(f"{FILES_OPEN_VERB}:{query}")


FILES_HANDLERS: dict[str, Handler] = {
    "files.open": _open_file,
}

register_table(FILES_HANDLERS)
