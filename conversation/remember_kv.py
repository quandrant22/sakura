"""«Запомнить» (этап 5, 3/3): приложение по пути («запомни app = path»)
и правила обращения/стиля (modules/rules). Команда агенту и подтверждение
через LLM — в Reply."""

from __future__ import annotations

from modules.rules import apply_rule, detect_rule

from . import Reply


def try_handle(text: str, ctx: dict) -> "Reply | None":
    if text.lower().startswith("запомни ") and "=" in text:
        parts = text.split("=", 1)
        name = parts[0].replace("запомни", "").strip().lower()
        path = parts[1].strip()
        if name and path:
            return Reply(
                prompt=f"Запомнила '{name}' = '{path}'. Подтверди коротко.",
                ws_command=f"remember_app:{name}={path}",
                fallback_text="Ноутбук оффлайн.",
            )

    rule = detect_rule(text)
    if rule:
        apply_rule(rule)
        rtype, rval = rule["type"], rule["value"] or ""
        if rtype == "address":
            prompt = (f"Мастер попросил называть его «{rval}». "
                      f"Подтверди что запомнила — коротко, своими словами.")
        elif rtype == "address_reset":
            prompt = "Мастер вернул обращение «Мастер». Подтверди коротко."
        elif rtype == "style":
            prompt = f"Мастер установил правило: {rval}. Подтверди одним предложением."
        elif rtype == "permission":
            prompt = f"Мастер разрешил: {rval}. Подтверди коротко."
        elif rtype == "cancel":
            prompt = f"Мастер отменил правило про «{rval}». Подтверди коротко."
        else:
            return None
        return Reply(prompt=prompt)
    return None