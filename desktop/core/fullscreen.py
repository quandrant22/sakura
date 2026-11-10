"""desktop.core.fullscreen — «победить» полноэкранные игры честно, без внедрения в процесс игры.

Что вообще возможно. Поверх окна игры Windows рисует другие окна (сцену Сакуры), если игра идёт:
  • в оконном режиме без рамки (borderless) — всегда;
  • в «полноэкранном» режиме DX11/DX12 с оптимизациями полноэкранного режима (FSO) — почти всегда:
    Windows на самом деле показывает игру как окно без рамки и умеет класть поверх оверлеи (так работает
    Xbox Game Bar);
  • в настоящем эксклюзивном режиме (старые DX9, DX11 с отключёнными FSO, часть Vulkan/OpenGL) — нет.
    Тут поверх может нарисовать только внедрение в игру (как Steam/Discord-оверлей) — его не делаем:
    античиты за это банят.

Поэтому:
  1. exclusive_active() — Windows сама говорит, что сейчас идёт эксклюзивное D3D-приложение
     (SHQueryUserNotificationState → QUNS_RUNNING_D3D_FULL_SCREEN);
  2. fso_disabled_for(exe) — у игры в «Совместимости» стоит галка «Отключить оптимизацию во весь экран»
     (флаг DISABLEDXMAXIMIZEDWINDOWEDMODE в AppCompatFlags\\Layers) → enable_fso_for(exe) её снимает
     (HKCU, без прав администратора; HKLM — только подсказкой);
  3. global_fso_disabled() — FSO выключены для всех игр (GameConfigStore) → подсказка и починка по кнопке;
  4. иначе — подсказка «оконный без рамки» и сцена на втором мониторе, голос — как обычно.
Ничего не меняется без явного действия Мастера (кнопка в настройках или «да» голосом).
"""
from __future__ import annotations

import logging
import sys

from desktop.core.platform import fso as _os

log = logging.getLogger("sakura.fullscreen")

FSO_FLAG = "DISABLEDXMAXIMIZEDWINDOWEDMODE"

# SHQueryUserNotificationState
QUNS_RUNNING_D3D_FULL_SCREEN = 3


def strip_flag(value: str, flag: str = FSO_FLAG) -> str:
    """Убрать флаг из строки слоёв совместимости: '~ DISABLEDXMAXIMIZEDWINDOWEDMODE HIGHDPIAWARE' → '~ HIGHDPIAWARE'.
    Пустая строка (или только '~') — значение можно удалить целиком."""
    parts = [p for p in (value or "").split() if p.upper() != flag.upper()]
    if parts == ["~"] or not parts:
        return ""
    return " ".join(parts)


def has_flag(value: str, flag: str = FSO_FLAG) -> bool:
    return any(p.upper() == flag.upper() for p in (value or "").split())


def exclusive_active() -> bool:
    """Идёт ли эксклюзивное полноэкранное D3D-приложение (поверх него сцену не видно)."""
    return _os.notification_state() == QUNS_RUNNING_D3D_FULL_SCREEN


def fso_disabled_for(exe_path: str) -> dict:
    """{'user': bool, 'machine': bool} — где у игры выключены оптимизации полноэкранного режима."""
    if not exe_path:
        return {"user": False, "machine": False}
    return {"user": has_flag(_os.read_layer(exe_path)), "machine": has_flag(_os.read_layer(exe_path, machine=True))}


def enable_fso_for(exe_path: str) -> dict:
    """Снять «Отключить оптимизацию во весь экран» у игры (HKCU). Нужно перезапустить игру."""
    if sys.platform != "win32" or not exe_path:
        return {"ok": False, "status": "unsupported", "detail": "только в Windows"}
    state = fso_disabled_for(exe_path)
    if state["machine"] and not state["user"]:
        return {"ok": False, "status": "unsupported",
                "detail": "флаг стоит для всех пользователей — снимите галку в свойствах exe → «Совместимость» "
                          "(нужны права администратора)"}
    if not state["user"]:
        return {"ok": True, "status": "noop", "detail": "оптимизации полноэкранного режима уже включены"}
    try:
        _os.write_layer(exe_path, strip_flag(_os.read_layer(exe_path)))
    except OSError as e:
        return {"ok": False, "status": "failed", "detail": f"реестр не дал изменить флаг: {type(e).__name__}"}
    log.info("[fullscreen] FSO включены для %s", exe_path)
    return {"ok": True, "status": "done", "detail": "Оптимизации полноэкранного режима включены — перезапусти игру"}


def global_fso_disabled() -> bool:
    """FSO выключены для всех игр (GameDVR_FSEBehaviorMode = 2 в HKCU\\System\\GameConfigStore)."""
    return _os.fse_behavior_mode() == 2


def enable_global_fso() -> dict:
    if sys.platform != "win32":
        return {"ok": False, "status": "unsupported", "detail": "только в Windows"}
    try:
        _os.set_fse_behavior_mode(0)
    except OSError as e:
        return {"ok": False, "status": "failed", "detail": f"реестр не дал изменить настройку: {type(e).__name__}"}
    return {"ok": True, "status": "done",
            "detail": "Оптимизации полноэкранного режима включены для всех игр — перезапусти игру"}


def advice(exe_path: str, exclusive: bool) -> dict:
    """Что подсказать, если сцену поверх игры не видно: {'exclusive', 'fix': 'game'|'global'|None, 'text'}."""
    if not exclusive:
        return {"exclusive": False, "fix": None, "text": ""}
    if fso_disabled_for(exe_path).get("user"):
        return {"exclusive": True, "fix": "game",
                "text": "У этой игры выключены оптимизации полноэкранного режима — могу включить, и я появлюсь "
                        "поверх неё после перезапуска игры."}
    if global_fso_disabled():
        return {"exclusive": True, "fix": "global",
                "text": "Оптимизации полноэкранного режима выключены для всех игр — могу включить обратно."}
    return {"exclusive": True, "fix": None,
            "text": "Игра в эксклюзивном полноэкранном режиме — поверх неё меня не видно. Включи в игре «Оконный "
                    "без рамки» (Borderless) — или я покажусь на втором мониторе."}
