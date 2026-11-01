"""Домен «зрение» (feat/vision): vision.ask, vision.glance.on, vision.glance.off.

vision.ask (legacy: screenshot.describe) — executor=vps: сервер сам
запрашивает кадр у ПК (vision.capture) и отвечает на вопрос. Клиент без
vision.capture (старый agent/) получает прежнюю команду screenshot.describe
с отметкой st._pending_describe — ответ придёт через command_result.

vision.glance.on/off — выключатель редкого «взгляда» (sakura_core/vision/glance.py).
"""

from __future__ import annotations

from sakura_core.executor import AgentCommand, ExecutionContext, register_table


async def _vision_ask(ctx: ExecutionContext):
    from sakura_core.vision import ask, capture
    question = ask.question_from((ctx.extra or {}).get("text") or "")
    device = ask.pick_device(ctx.device_id or None)
    if device is None:
        return ("Не понимаю, на какой компьютер смотреть: ни один не в сети или их несколько.",
                False)
    if capture.supports(device):
        return await ask.answer(device, question)
    # Старый клиент: кадр придёт command_result, ответ — describe_legacy.
    if device != ctx.device_id or ctx.device_ws is None:
        return ("Клиент на этом компьютере не умеет показывать мне экран.", False)
    import modules.state as st
    st._pending_describe[device] = question
    return AgentCommand("screenshot.describe")


async def _glance_on(_ctx: ExecutionContext) -> tuple[str, bool]:
    import config
    from sakura_core.vision import glance, settings
    settings.set_glance(True)
    glance.instance().on_enabled()
    if not config.VISION_GLANCE:
        return ("Запомнила, но подглядывание сейчас выключено на сервере.", False)
    return ("Хорошо, буду иногда поглядывать на экран.", True)


async def _glance_off(_ctx: ExecutionContext) -> tuple[str, bool]:
    from sakura_core.vision import settings
    settings.set_glance(False)
    return ("Хорошо, больше не подглядываю.", True)


register_table({
    "vision.ask": _vision_ask,
    "vision.glance.on": _glance_on,
    "vision.glance.off": _glance_off,
})
