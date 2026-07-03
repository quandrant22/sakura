"""
modules/planner.py — Планировщик произвольных задач.

Строит план из атомарных примитивов, когда команда не найдена в каталоге.
"""

import asyncio
import json
import logging

log = logging.getLogger("sakura.planner")

PRIMITIVES = {
    "open_app":     "открыть приложение по имени",
    "close_window": "закрыть окно приложения",
    "focus_window": "переключиться на окно приложения",
    "hotkey":       "нажать комбинацию клавиш (например ctrl+shift+esc)",
    "type_text":    "напечатать текст в активное окно",
    "volume_set":   "установить громкость (0-100)",
    "volume_up":    "прибавить громкость",
    "volume_down":  "убавить громкость",
    "music_play_pause": "включить/поставить паузу",
    "music_next":   "следующий трек",
    "music_prev":   "предыдущий трек",
    "wait":         "пауза между шагами (секунды, макс 10)",
    "powershell":   "выполнить команду в PowerShell (опасно)",
    "say":          "произнести текст голосом",
}

MAX_STEPS = 6
MAX_WAIT_TOTAL = 20

PLAN_PROMPT = """Ты — планировщик действий для голосового ассистента Сакура (Windows ПК).
Получаешь реплику Мастера и список доступных примитивов.
Строй ПОСЛЕДОВАТЕЛЬНЫЙ план из примитивов для выполнения задачи.

ДОСТУПНЫЕ ПРИМИТИВЫ:
{primitives}

Активное окно: {active_window}
Известные приложения: {apps}

Ответ — ТОЛЬКО JSON:
{{"steps": [{{"action": "примитив", "arg": "аргумент"}}], "summary": "одно предложение что будет сделано"}}

Если задача невыполнима примитивами → {{"steps": []}}.
Максимум {max_steps} шагов. Не используй powershell/type_text без крайней необходимости."""


def is_master_source(source: str, sender_id) -> bool:
    """Проверяет что источник — прямая реплика Мастера."""
    if source == "telegram":
        from config import MASTER_ID
        return sender_id == MASTER_ID
    if source == "voice":
        from modules.ws_auth import is_master_device
        return is_master_device(sender_id)
    return False


def _validate_plan(plan: dict) -> dict | None:
    """Валидирует план: макс 6 шагов, известные примитивы, wait ≤ 20с."""
    if not plan or not isinstance(plan, dict):
        return None
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        return None
    if len(steps) > MAX_STEPS:
        log.warning(f"[planner] план из {len(steps)} шагов — отклонён (макс {MAX_STEPS})")
        return None

    wait_total = 0
    for step in steps:
        action = step.get("action", "")
        if action not in PRIMITIVES:
            log.warning(f"[planner] неизвестный примитив: {action}")
            return None
        if action == "wait":
            try:
                wait_total += int(step.get("arg", "1"))
            except (ValueError, TypeError):
                return None

    if wait_total > MAX_WAIT_TOTAL:
        log.warning(f"[planner] суммарный wait {wait_total}с > {MAX_WAIT_TOTAL}с")
        return None

    plan["summary"] = plan.get("summary", "выполнить задачу")
    return plan


def _is_plan_risky(plan: dict) -> bool:
    """Определяет опасность плана: powershell, type_text или необратимые примитивы."""
    from modules.command_router import is_irreversible
    for step in plan.get("steps", []):
        action = step.get("action", "")
        if action in ("powershell", "type_text"):
            return True
        if is_irreversible(action):
            return True
    return False


async def build_plan(text: str, context: dict, source: str = "voice",
                     sender_id=None) -> dict | None:
    """
    Строит план из примитивов для выполнения задачи.
    Возвращает {"steps": [...], "risky": bool, "summary": str} или None.
    """
    if not is_master_source(source, sender_id):
        log.info(f"[planner] источник не Master: source={source}, sender={sender_id}")
        return None

    from config import get_active_key, mark_key_used
    key = get_active_key()
    if not key:
        return None

    active_window = context.get("active_window", "")
    apps = context.get("known_apps", [])
    apps_str = ", ".join(apps[:50]) if apps else "нет данных"

    primitives_str = "\n".join(f"- {k}: {v}" for k, v in PRIMITIVES.items())
    prompt = PLAN_PROMPT.format(
        primitives=primitives_str,
        active_window=active_window or "неизвестно",
        apps=apps_str,
        max_steps=MAX_STEPS,
    ) + f'\n\nЗадача: "{text}"'

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=400,
            )
        )
        mark_key_used(key)
        raw = (response.text or "").strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        plan = json.loads(raw)
    except json.JSONDecodeError:
        log.debug(f"[planner] JSON parse error: {raw!r}")
        return None
    except Exception as e:
        log.debug(f"[planner] error: {e}")
        return None

    plan = _validate_plan(plan)
    if not plan:
        return None

    plan["risky"] = _is_plan_risky(plan)
    log.info(f"[planner] план: {len(plan['steps'])} шагов, risky={plan['risky']}, summary={plan['summary']!r}")
    return plan
