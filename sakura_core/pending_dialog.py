"""Обработка pending-состояний: подтверждение системных команд,
забывание, план, уточнение. Вынесено из modules/ws_handlers.py."""

from __future__ import annotations

import json
import logging
import time as _time

import modules.tts_server as _tts
from modules.ws_auth import is_master_device
from modules.voice_info import pending_forget_active, memory_forget_confirm

log = logging.getLogger(__name__)

MASTER_ID = None  # Устанавливается при инициализации


def set_master_id(mid):
    global MASTER_ID
    MASTER_ID = mid


def _get_st():
    """Получить modules.state — лениво, чтобы тесты могли патчить через ws_handlers."""
    import modules.state
    return modules.state


async def _handle_pending(text, text_lower, _mk, ws_dev, device_id, ctx, data) -> bool:
    """Обрабатывает pending-состояния: подтверждение системной команды,
    забывание, план, отмену плана, уточнение. Возвращает True если реплика
    принадлежит pending-диалогу (обработана), False — если нет, и её надо
    пропустить в обычный путь (классификатор намерений и дальше)."""
    ask_gemini = ctx["ask_gemini"]
    _execute_plan = ctx["_execute_plan"]
    _register_command = ctx["_register_command"]
    bot = ctx["bot"]
    _now_ts = _time.monotonic()
    st = _get_st()

    # ── ПОДТВЕРЖДЕНИЕ СИСТЕМНОЙ КОМАНДЫ (выключение/перезагрузка/сон) ──
    if _mk in st._pending_system:
        _ps = st._pending_system[_mk]
        if _now_ts - _ps["ts"] < 60:
            _ps_result = st.check_confirmation(text)
            if _ps_result == "confirm":
                del st._pending_system[_mk]
                if ws_dev:
                    from sakura_core.executor import execute_critical_action
                    await execute_critical_action(_ps["action"], ws_dev, device_id, text, data.get("active_window", ""), ask_gemini)
                else:
                    await bot.send_message(MASTER_ID, "Устройство отключилось, не могу выполнить.")
                return True
            elif _ps_result == "deny":
                del st._pending_system[_mk]
                _ps_cancel_msg = "Хорошо, отменила."
                if ws_dev:
                    await _tts.stream_tts_to_device(_ps_cancel_msg, ws_dev, device_id or "laptop", literal=True)
                else:
                    await bot.send_message(MASTER_ID, _ps_cancel_msg)
                return True
            else:
                del st._pending_system[_mk]
        else:
            del st._pending_system[_mk]

    # ── ПОДТВЕРЖДЕНИЕ ЗАБЫВАНИЯ («забудь про Х» → «да») ──
    if pending_forget_active():
        _fg = memory_forget_confirm(text)
        if _fg is not None:
            if ws_dev:
                await _tts.stream_tts_to_device(_fg[0], ws_dev, device_id or "laptop", literal=True)
            else:
                await bot.send_message(MASTER_ID, _fg[0])
            return True

    if _mk in st._pending_plan:
        _pp = st._pending_plan[_mk]
        if _now_ts - _pp["ts"] < 60:
            _pp_text = text.lower().strip().rstrip(".!?,")
            if _pp_text in ("да", "давай", "делай", "точно", "ага", "угу", "конечно"):
                del st._pending_plan[_mk]
                _plan_result, _plan_msg = await _execute_plan(
                    _pp["plan"], _mk, ws_dev, device_id)
                if _plan_result:
                    from modules.user_commands import add as _uc_add
                    _uc_add(_pp["text"], {
                        "plan": _pp["plan"]["steps"],
                        "summary": _pp["plan"]["summary"],
                        "source": "plan",
                        "risky": _pp["plan"]["risky"],
                        "uses": 1,
                    }, source="plan")
                if ws_dev:
                    await _tts.stream_tts_to_device(
                        _plan_msg, ws_dev, device_id or "laptop", literal=True)
                else:
                    await bot.send_message(MASTER_ID, _plan_msg)
                return True
            elif _pp_text in ("нет", "стоп", "отмена", "хватит"):
                del st._pending_plan[_mk]
                _deny = "Хорошо, отменила."
                if ws_dev:
                    await _tts.stream_tts_to_device(
                        _deny, ws_dev, device_id or "laptop", literal=True)
                else:
                    await bot.send_message(MASTER_ID, _deny)
                return True
            else:
                del st._pending_plan[_mk]
        else:
            del st._pending_plan[_mk]

    # ── ОТМЕНА ПЛАНА: «стоп»/«отмена» во время исполнения ──
    if _mk in st._pending_plan:
        _tlow = text.lower().strip().rstrip(".!?,")
        if _tlow in ("стоп", "отмена", "хватит", "стоп план", "отмена плана"):
            del st._pending_plan[_mk]
            st._plan_cancel[_mk] = True

    # ── УТОЧНЕНИЕ: проверяем ответ на предыдущий вопрос ──
    if _mk in st._pending_clarify:
        _pc = st._pending_clarify[_mk]
        if _now_ts - _pc["ts"] < 60:
            _pc_text = text.lower().strip().rstrip(".!?,")
            _main_action = _pc["main"].get("action", "")
            _alt_action = _pc["alt"].get("action", "") if _pc["alt"] else ""

            _chose_main = False
            _chose_alt = False
            if _pc_text in ("да", "давай", "точно", "именно", "конечно", "ага", "угу"):
                _chose_main = True
            elif _pc_text in ("нет", "стоп", "отмена", "другое", "не то"):
                pass  # отбой
            elif _alt_action and _alt_action in _pc_text:
                _chose_alt = True
            elif _main_action and _main_action in _pc_text:
                _chose_main = True
            else:
                # Not an answer to the old clarification: route this new text
                # through the canonical registry in the caller.
                del st._pending_clarify[_mk]
                return False

            del st._pending_clarify[_mk]

            if _chose_main or _chose_alt:
                _chosen = _pc["main"] if _chose_main else _pc["alt"]
                from modules.user_commands import add as _uc_add
                _uc_add(_pc["text"], _chosen, source="auto")
                if ws_dev:
                    _chosen_action = _chosen.get("action", "")
                    _chosen_arg = _chosen.get("arg", "")
                    if _chosen_arg and ":" not in _chosen_action:
                        _chosen_full = f"{_chosen_action}:{_chosen_arg}"
                    else:
                        _chosen_full = _chosen_action
                    _cmd_id = _register_command(_chosen_full, device_id or "laptop")
                    await ws_dev.send(json.dumps({"type": "command", "action": _chosen_full, "id": _cmd_id}))
                return True
            return True
        else:
            del st._pending_clarify[_mk]

    return False
