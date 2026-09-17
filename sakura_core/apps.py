"""Анализ приложений и скриншотов: analyze_apps, _analyze_screen_context.

Перенесено из main.py (stage 7D).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time

from config import get_active_key, mark_key_used, MAIN_MODEL
from modules.jsonio import save_json

log = logging.getLogger(__name__)


async def analyze_apps(apps: dict, device_id: str):
    try:
        mapping_file = f"memory/apps_mapping_{device_id}.json"
        if os.path.exists(mapping_file):
            age = time.time() - os.path.getmtime(mapping_file)
            if age < 86400:
                log.debug(f"[apps] маппинг {device_id} свежий ({age/3600:.1f}ч), пропускаю")
                return
        key = get_active_key()
        if not key:
            return
        exe_apps = {k: v for k, v in apps.items()
                    if isinstance(v, str) and (
                        v.lower().endswith((".exe", ".lnk", ".url"))
                        or v.startswith(("steam:", "shell:", "http")))}
        names    = list(exe_apps.keys())[:200]
        from sakura_core.llm import generate as _llm_generate
        from google.genai import types
        prompt   = (
            f"Список приложений (без .exe):\n{json.dumps(names, ensure_ascii=False)}\n\n"
            "Создай маппинг разговорных русских названий к именам из списка.\n"
            'Верни JSON: {"разговорное": "имя из списка"}\n'
            "Только очевидные совпадения. Максимум 60 записей."
        )
        r = await _llm_generate(
            [types.Content(role="user", parts=[types.Part(text=prompt)])],
            model=MAIN_MODEL,
            max_tokens=2000,
            response_mime_type="application/json",
        )
        raw           = r.replace("```json", "").replace("```", "").strip()
        mapping_names = json.loads(raw)
        mark_key_used(key)

        full: dict = {}
        for ru, app_key in mapping_names.items():
            ak = app_key.lower()
            if ak in exe_apps:
                full[ru.lower()] = exe_apps[ak]
            else:
                for name, path in exe_apps.items():
                    if ak in name.lower() or name.lower() in ak:
                        full[ru.lower()] = path
                        break
        for name, path in exe_apps.items():
            base = os.path.splitext(os.path.basename(name))[0].lower()
            full.setdefault(base, path)
            full.setdefault(name.lower(), path)

        save_json(f"memory/apps_mapping_{device_id}.json", full)
        log.info(f"Маппинг приложений ({device_id}): {len(full)} записей")
    except Exception as e:
        log.error(f"Apps analyze error: {e}")


async def analyze_screen_context(screenshot_b64: str, active_window: str, device_id: str):
    key = get_active_key()
    if not key:
        return

    try:
        img_bytes = base64.b64decode(screenshot_b64)
        if len(img_bytes) < 1000:
            return

        from sakura_core.llm import generate as _llm_generate
        from google.genai import types
        prompt = (
            "Кратко опиши что на этом скриншоте (1-2 предложения). "
            "Чем занят человек? Какая обстановка? "
            "Только факты, без советов."
        )

        r = await _llm_generate(
            [types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=img_bytes)),
                types.Part(text=prompt),
            ])],
            model=MAIN_MODEL,
            max_tokens=100,
        )
        description = r
        mark_key_used(key)

        if description:
            try:
                from modules.context import set_screen_context
                set_screen_context(active_window, description)
            except Exception as e:
                log.debug(f"[main] _analyze_screen_context: {type(e).__name__}: {e}")

            log.debug(f"[screen] Контекст: {description[:60]}")
    except Exception as e:
        log.debug(f"[screen] Анализ ошибки: {e}")
