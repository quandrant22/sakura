"""Фоновые задачи памяти: extract_and_remember, summarize_session, daily_analysis.

Перенесено из main.py (stage 7D).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from config import get_active_key, mark_key_used, MAIN_MODEL
from memory.memory import (
    add_to_history, get_history, clear_history,
    needs_daily_analysis, mark_analysis_done,
    save_session_summary, clear_session_summary,
)
from modules.jsonio import save_json
from modules.tasks import add_task, extract_tasks_from_text
from modules.threads import extract_threads
from memory.db import add_to_category as db_add_to_category

log = logging.getLogger(__name__)


async def clean_slate():
    """Полный сброс памяти Сакуры."""
    clear_history()
    clear_session_summary()

    from memory.memory import MEMORY_FILE, _atomic_write
    empty = {
        "master":        {k: [] for k in ["facts","interests","preferences","achievements","patterns","events","notes"]},
        "last_updated":  str(datetime.now()),
        "last_analysis": None,
    }
    _atomic_write(MEMORY_FILE, empty)

    empty_rules = {
        "address":     None,
        "style":       [],
        "permissions": [],
        "behaviors":   [],
        "updated":     str(datetime.now()),
    }
    save_json("memory/rules.json", empty_rules)

    log.info("[Протокол] Чистый лист выполнен.")


def guarded_add(cat: str, item: str):
    """Обёртка для reflection_loop: два барьера."""
    from modules.intimacy_mode import consume_check, is_intimate_content
    if consume_check():
        log.info("[memory] reflection write skipped: intimacy in window")
        return False
    if is_intimate_content(item):
        log.info(f"[memory] интимный фильтр (reflection): {item[:40]}")
        return False
    return db_add_to_category(cat, item)


async def extract_and_remember(user_message: str, reply: str):
    await asyncio.sleep(3)
    from modules.intimacy_mode import is_active as _im_active
    if _im_active():
        log.info("[memory] extraction skipped: intimacy mode")
        return
    key = get_active_key()
    if not key:
        return
    try:
        from sakura_core.llm import get_client
        from sakura_core.llm import generate as _llm_generate
        from google.genai import types

        client = get_client(key)
        prompt = (
            f"Сообщение Мастера: {user_message}\nОтвет Сакуры: {reply}\n\n"
            "Извлеки ТОЛЬКО то что Мастер явно сказал о себе. "
            "НЕ домысливай, НЕ делай выводов, НЕ интерпретируй. "
            "Только прямые факты из его слов. "
            "Игровой контекст (LEGO, Minecraft, GTA и т.д.) — это игра, не реальность. "
            "Команды ассистенту (следующий трек, пауза, открой и т.д.) — не записывать.\n"
            "Каждый факт помечай префиксом слоя:\n"
            "[L] — устойчивое: предпочтения, факты о Мастере, повторяющиеся паттерны, важные события жизни;\n"
            "[W] — временное: текущие задачи, состояния на этой неделе, незакрытые дела;\n"
            "Сиюминутное НЕ выводи вовсе: эмоции момента, обсуждения кода и архитектуры Sakura, "
            "разовые бытовые события, темы одного разговора.\n"
            'Верни JSON: {"facts":[],"interests":[],"preferences":[],'
            '"achievements":[],"patterns":[],"events":[],"notes":[],'
            '"entities":[{"name":"","type":"person|project|place|game|org|event|thing","date":""}],'
            '"relations":[{"from":"","to":"","rel":""}]}\n'
            "entities — люди/проекты/места/игры/события упомянутые в диалоге; "
            "date заполняй только для type=event в формате YYYY-MM-DD.\n"
            "relations — связи между ними.\n"
            "Если ничего нового — все массивы пустые. Максимум 2 пункта на массив."
        )
        r = await _llm_generate(
            [types.Content(role="user", parts=[types.Part(text=prompt)])],
            model=MAIN_MODEL,
        )
        raw       = r.replace("```json", "").replace("```", "").strip()
        extracted = json.loads(raw)

        ents = extracted.pop("entities", []) or []
        rels = extracted.pop("relations", []) or []
        if ents or rels:
            try:
                from modules.graph import ingest as graph_ingest
                await asyncio.to_thread(graph_ingest, ents, rels)
            except Exception as _ge:
                log.debug(f"graph ingest: {_ge}")

        saved = []
        for cat, items in extracted.items():
            for item in items:
                if item and isinstance(item, str):
                    try:
                        from modules.memory_validator import validate_and_check
                        is_valid, reason, contradiction = await asyncio.to_thread(
                            validate_and_check, item, cat
                        )
                        if not is_valid:
                            log.debug(f"[memory] пропущено ({reason}): {item[:40]}")
                            continue
                        if contradiction:
                            log.warning(f"[memory] противоречие: {item[:40]} — {contradiction}")
                    except Exception:
                        pass

                    layer = "long_term"
                    if item.startswith("[L]"):
                        layer = "long_term"
                        item = item[3:].strip()
                    elif item.startswith("[W]"):
                        layer = "working"
                        item = item[3:].strip()

                    from modules.intimacy_mode import is_intimate_content
                    if is_intimate_content(item):
                        log.info(f"[memory] интимный контент отфильтрован: {item[:40]}")
                        continue
                    ok = await asyncio.to_thread(db_add_to_category, cat, item, layer)
                    if ok is not False:
                        saved.append(f"{cat}: {item[:40]}")
        if saved:
            log.info(f"[memory] сохранено: {saved}")
        else:
            log.info("[memory] ничего нового не извлечено")
        mark_key_used(key)
        for t in extract_tasks_from_text(user_message):
            add_task(t["text"], t.get("due_date"), t.get("due_time"))

        try:
            await asyncio.to_thread(extract_threads, user_message, reply)
        except Exception as _te:
            log.debug(f"threads: {_te}")

        try:
            from modules.capsules import should_create_sakura_capsule, create_sakura_capsule
            hint = should_create_sakura_capsule(user_message, reply)
            if hint:
                await asyncio.to_thread(
                    create_sakura_capsule,
                    hint["observation"], hint["days"],
                    user_message[:80]
                )
        except Exception as _ce:
            log.debug(f"sakura capsule: {_ce}")

    except Exception as e:
        log.error(f"Memory extraction error: {e}")


async def summarize_session():
    history = get_history()
    if len(history) < 10:
        return
    key = get_active_key()
    if not key:
        return
    try:
        from sakura_core.llm import generate as _llm_generate
        from google.genai import types

        hist_text = "\n".join([
            f"{'Мастер' if m['role'] == 'user' else 'Сакура'}: {m['parts'][0]}"
            for m in history[-40:]
        ])
        r = await _llm_generate(
            [types.Content(role="user", parts=[types.Part(
                text=f"Сделай краткое резюме диалога (макс 300 слов):\n{hist_text}"
            )])],
            model=MAIN_MODEL,
        )
        save_session_summary(r)
        mark_key_used(key)
        log.info("Резюме сессии обновлено")
    except Exception as e:
        log.error(f"Summarize error: {e}")


async def daily_analysis():
    while True:
        await asyncio.sleep(3600)
        from modules.intimacy_mode import is_active as _im_active_daily
        if _im_active_daily():
            log.info("[memory] daily analysis skipped: intimacy mode")
            continue
        if not needs_daily_analysis():
            continue
        key = get_active_key()
        if not key:
            continue
        history = get_history()
        if len(history) < 4:
            continue
        try:
            from sakura_core.llm import generate as _llm_generate
            from google.genai import types

            hist_text = "\n".join([f"{m['role']}: {m['parts'][0]}" for m in history[-40:]])
            r = await _llm_generate(
                [types.Content(role="user", parts=[types.Part(
                    text=f"Выводы о паттернах поведения Мастера:\n{hist_text}\n"
                         'Верни JSON: {"patterns":[],"preferences":[]}'
                )])],
                model=MAIN_MODEL,
            )
            mark_key_used(key)
            raw = r.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            for cat in ("patterns", "preferences"):
                for item in data.get(cat, []):
                    if item and isinstance(item, str):
                        db_add_to_category(cat, item)
            mark_analysis_done()
            log.info(f"[memory] daily analysis: {sum(len(v) for v in data.values())} items")
        except Exception as e:
            log.error(f"Daily analysis error: {e}")
