"""settings — пользовательский выключатель взгляда.

memory/vision_settings.json: {"glance_enabled": bool}. По умолчанию взгляд
выключен: включает только Мастер («поглядывай на экран»).
"""

from __future__ import annotations

import json
import logging

import config

log = logging.getLogger("sakura.vision")

DEFAULTS = {"glance_enabled": False}


def load() -> dict:
    try:
        with open(config.VISION_SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError("не объект")
    except FileNotFoundError:
        return dict(DEFAULTS)
    except Exception as e:
        log.warning(f"[vision] настройки не прочитаны ({type(e).__name__}) — по умолчанию")
        return dict(DEFAULTS)
    return {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}


def glance_enabled() -> bool:
    return bool(load().get("glance_enabled"))


def set_glance(enabled: bool) -> None:
    from modules.jsonio import save_json
    data = load()
    data["glance_enabled"] = bool(enabled)
    save_json(config.VISION_SETTINGS_PATH, data)
    log.info(f"[vision] взгляд {'включён' if enabled else 'выключен'} Мастером")
